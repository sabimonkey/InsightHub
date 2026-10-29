import json
import re
from html.parser import HTMLParser
from urllib.parse import urljoin

from app.services.discovery.identifiers import IdentifierHit, SearchClues, build_search_clues, find_identifiers
from app.services.discovery.ranking import CandidateDraft, classify_host, from_search_result, merge_drafts
from app.services.discovery.search import SearchProvider, SearchResult, SearchUnavailable
from app.services.extraction.web_extractor import fetch_public_page
from app.services.ingestion.errors import IngestionError
from app.services.ingestion.url_normalization import canonicalize_url

PRIMARY_HINTS = ("arxiv.org", "doi.org", "github.com", "pubmed.ncbi.nlm.nih.gov")
RESOLVER_VERSION = "discovery-v1"


class _MetaParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.canonical: str | None = None
        self.og_url: str | None = None
        self.title: str | None = None
        self.author: str | None = None
        self.publisher: str | None = None
        self.hrefs: list[str] = []
        self._title = False
        self._title_parts: list[str] = []
        self._json_ld: list[str] = []
        self._script = False
        self._script_type = ""
        self._script_parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        mapping = {key.lower(): value or "" for key, value in attrs}
        if tag == "link" and "canonical" in mapping.get("rel", "").lower():
            self.canonical = mapping.get("href") or self.canonical
        if tag == "meta":
            key = (mapping.get("property") or mapping.get("name") or "").lower()
            content = mapping.get("content")
            if key == "og:url" and content:
                self.og_url = content
            elif key in {"author", "article:author"} and content:
                self.author = content
            elif key in {"publisher", "og:site_name"} and content:
                self.publisher = content
        if tag == "a" and mapping.get("href"):
            self.hrefs.append(mapping["href"])
        if tag == "title":
            self._title = True
        if tag == "script":
            self._script = True
            self._script_type = mapping.get("type", "")
            self._script_parts = []

    def handle_endtag(self, tag):
        if tag == "title":
            self._title = False
            self.title = " ".join(self._title_parts).strip() or self.title
            self._title_parts = []
        if tag == "script" and self._script:
            if "ld+json" in self._script_type:
                self._json_ld.append("".join(self._script_parts))
            self._script = False

    def handle_data(self, data):
        if self._title:
            self._title_parts.append(data.strip())
        if self._script:
            self._script_parts.append(data)


def _draft_from_identifier(hit: IdentifierHit, source_text: str | None = None) -> CandidateDraft | None:
    try:
        _original, canonical = canonicalize_url(hit.url)
    except IngestionError:
        return None
    evidence = {"provenance": hit.provenance, "untrusted_content": True}
    if source_text:
        evidence["source_excerpt"] = source_text[:240]
    return CandidateDraft(
        url=hit.url,
        normalized_url=canonical,
        title=hit.title,
        author=hit.author,
        publisher=hit.publisher,
        candidate_type=hit.candidate_type,
        score=hit.score,
        confidence=min(hit.score, 0.99),
        match_reasons=[hit.reason],
        evidence=evidence,
    )


def _draft_from_url(url: str, provenance: str, reason: str, score: float, candidate_type: str, title: str | None, author: str | None, publisher: str | None) -> CandidateDraft | None:
    try:
        _original, canonical = canonicalize_url(url)
    except IngestionError:
        return None
    return CandidateDraft(
        url=url,
        normalized_url=canonical,
        title=title,
        author=author,
        publisher=publisher,
        candidate_type=candidate_type,
        score=score,
        confidence=min(score, 0.95),
        match_reasons=[reason],
        evidence={"provenance": provenance, "untrusted_content": True},
    )


def identifiers_from_text(text: str) -> list[CandidateDraft]:
    drafts = []
    for hit in find_identifiers(text):
        draft = _draft_from_identifier(hit, text)
        if draft is not None:
            drafts.append(draft)
    return drafts


class UrlSourceResolver:
    resolver_type = "URL"

    def __init__(self, search: SearchProvider, timeout: float, max_bytes: int, max_redirects: int, http_client=None, resolver=None) -> None:
        self.search = search
        self.timeout = timeout
        self.max_bytes = max_bytes
        self.max_redirects = max_redirects
        self.http_client = http_client
        self.resolver = resolver

    def resolve(self, url: str) -> tuple[list[CandidateDraft], str, str | None, str | None]:
        fetched = fetch_public_page(url, self.timeout, self.max_bytes, self.max_redirects, self.http_client, self.resolver)
        if fetched.error_code == "SSRF_BLOCKED":
            return [], "url", fetched.error_code, fetched.error_message
        drafts: list[CandidateDraft] = []
        access_error = None
        status = fetched.metadata.get("http_status")
        final_url = fetched.metadata.get("final_url")
        if final_url and final_url != url:
            draft = _draft_from_url(str(final_url), "REDIRECT", "HTTP redirect final URL", 0.55, "UNKNOWN", None, None, None)
            if draft:
                drafts.append(draft)
        if fetched.error_code == "WEB_HTTP_ERROR" and status in {401, 403}:
            access_error = ("SOURCE_ACCESS_FAILED", fetched.error_message or "来源访问失败。")
        elif fetched.error_code and fetched.error_code != "WEB_RESPONSE_TOO_LARGE":
            access_error = (fetched.error_code, fetched.error_message)
        html = (fetched.body or b"").decode(fetched.encoding or "utf-8", errors="replace")
        if html:
            drafts.extend(_metadata_candidates(html, final_url or url))
        strong = [item for item in drafts if item.evidence.get("provenance") in {"HTML_CANONICAL", "OG_URL", "REFERENCED_LINK", "IDENTIFIER"}]
        summary = "url metadata"
        error_code = None
        error_message = None
        if not strong:
            queries = [url]
            if access_error and ("x.com" in url or "twitter.com" in url):
                queries.append(url)
            try:
                drafts.extend(_search_queries(self.search, queries[:2], build_search_clues(html[:500] if html else url)))
                summary = "url metadata + search"
            except SearchUnavailable as exc:
                error_code, error_message = exc.code, exc.message
                if access_error and not drafts:
                    error_code, error_message = access_error
        elif access_error:
            error_code, error_message = None, None
        if access_error and not drafts:
            error_code, error_message = access_error
        return merge_drafts(drafts), summary, error_code, error_message


def _metadata_candidates(html: str, base_url: str) -> list[CandidateDraft]:
    parser = _MetaParser()
    parser.feed(html)
    drafts: list[CandidateDraft] = []
    if parser.canonical:
        draft = _draft_from_url(urljoin(base_url, parser.canonical), "HTML_CANONICAL", "HTML canonical link", 0.8, "ORIGINAL", parser.title, parser.author, parser.publisher)
        if draft:
            drafts.append(draft)
    if parser.og_url:
        draft = _draft_from_url(urljoin(base_url, parser.og_url), "OG_URL", "og:url", 0.74, "ORIGINAL", parser.title, parser.author, parser.publisher)
        if draft:
            drafts.append(draft)
    for href in parser.hrefs:
        absolute = urljoin(base_url, href)
        if any(hint in absolute.lower() for hint in PRIMARY_HINTS):
            kind = classify_host(absolute)
            draft = _draft_from_url(absolute, "REFERENCED_LINK", "referenced primary link", 0.86, kind if kind != "UNKNOWN" else "ORIGINAL", None, None, None)
            if draft:
                drafts.append(draft)
    for blob in parser._json_ld:
        try:
            payload = json.loads(blob)
        except json.JSONDecodeError:
            continue
        _collect_json_ld(payload, drafts, parser)
    return drafts


def _collect_json_ld(payload, drafts: list[CandidateDraft], parser: _MetaParser) -> None:
    rows = payload if isinstance(payload, list) else [payload]
    for row in rows:
        if not isinstance(row, dict):
            continue
        url = row.get("url") or row.get("mainEntityOfPage")
        if isinstance(url, dict):
            url = url.get("@id") or url.get("url")
        if isinstance(url, str):
            draft = _draft_from_url(url, "STRUCTURED_METADATA", "structured metadata url", 0.78, "ORIGINAL", parser.title, parser.author, parser.publisher)
            if draft:
                drafts.append(draft)


class TextSourceResolver:
    resolver_type = "TEXT"

    def __init__(self, search: SearchProvider) -> None:
        self.search = search

    def resolve(self, text: str) -> tuple[list[CandidateDraft], str, str | None, str | None]:
        drafts = identifiers_from_text(text)
        clues = build_search_clues(text)
        if drafts:
            return merge_drafts(drafts), "identifier", None, None
        try:
            found = _search_queries(self.search, clues.queries, clues)
        except SearchUnavailable as exc:
            return [], "search", exc.code, exc.message
        return merge_drafts(found), "search:" + " | ".join(clues.queries), None, None


class ImageSourceResolver:
    resolver_type = "IMAGE"

    def __init__(self, search: SearchProvider) -> None:
        self.search = search

    def resolve(self, text: str) -> tuple[list[CandidateDraft], str, str | None, str | None]:
        return TextSourceResolver(self.search).resolve(text)


def _search_queries(search: SearchProvider, queries: list[str], clues: SearchClues) -> list[CandidateDraft]:
    drafts: list[CandidateDraft] = []
    last_error: SearchUnavailable | None = None
    for query in queries:
        if not query:
            continue
        try:
            results = search.search(query, limit=5)
        except SearchUnavailable as exc:
            last_error = exc
            continue
        for result in results:
            if _same_status_preferred(result, clues.text):
                result = SearchResult(
                    url=_canonical_status_url(result.url),
                    title=result.title,
                    snippet=result.snippet,
                    rank=result.rank,
                    provider=result.provider,
                )
            drafts.append(from_search_result(result, clues))
    if not drafts and last_error is not None:
        raise last_error
    return drafts


def _canonical_status_url(url: str) -> str:
    match = re.search(r"(?:x\.com|twitter\.com)/([A-Za-z0-9_]{1,15})/status/(\d+)", url, re.IGNORECASE)
    if not match:
        return url
    return f"https://x.com/{match.group(1)}/status/{match.group(2)}"


def _same_status_preferred(result: SearchResult, source_text: str) -> bool:
    source = re.search(r"/status/(\d+)", source_text or "")
    found = re.search(r"/status/(\d+)", result.url or "")
    return bool(source and found and source.group(1) == found.group(1))
