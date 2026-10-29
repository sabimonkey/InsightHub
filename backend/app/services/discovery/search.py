import json
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Protocol
from urllib.parse import parse_qs, unquote, urlsplit

import httpx

from app.services.extraction.ssrf import SsrfError, assert_public_http_url


@dataclass
class SearchResult:
    url: str
    title: str | None
    snippet: str | None
    rank: int
    provider: str


class SearchProvider(Protocol):
    name: str

    def search(self, query: str, limit: int = 5) -> list[SearchResult]:
        ...


class SearchUnavailable(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.code = "SEARCH_UNAVAILABLE"
        self.message = message


class DisabledSearchProvider:
    name = "disabled"

    def search(self, query: str, limit: int = 5) -> list[SearchResult]:
        raise SearchUnavailable("搜索服务未启用。")


class ConfigurableSearchProvider:
    """Generic JSON search API. Results are untrusted data, not instructions."""

    name = "http"

    def __init__(self, endpoint: str, api_key: str = "", client: httpx.Client | None = None, timeout: float = 10) -> None:
        self.endpoint = endpoint
        self.api_key = api_key
        self.client = client
        self.timeout = timeout

    def search(self, query: str, limit: int = 5) -> list[SearchResult]:
        if not self.endpoint:
            raise SearchUnavailable("没有配置搜索接口。")
        owns = self.client is None
        client = self.client or httpx.Client(timeout=self.timeout, follow_redirects=False)
        try:
            headers = {"Accept": "application/json"}
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"
            response = client.post(self.endpoint, headers=headers, json={"query": query, "limit": limit})
            if response.status_code >= 400:
                raise SearchUnavailable(f"搜索接口返回 HTTP {response.status_code}")
            payload = response.json()
        except SearchUnavailable:
            raise
        except (httpx.HTTPError, json.JSONDecodeError) as exc:
            raise SearchUnavailable("搜索接口不可用。") from exc
        finally:
            if owns:
                client.close()
        rows = payload.get("results") if isinstance(payload, dict) else None
        if not isinstance(rows, list):
            raise SearchUnavailable("搜索接口响应无法识别。")
        results: list[SearchResult] = []
        for index, row in enumerate(rows[:limit], start=1):
            if not isinstance(row, dict) or not row.get("url"):
                continue
            results.append(
                SearchResult(
                    url=str(row["url"]),
                    title=str(row["title"]) if row.get("title") else None,
                    snippet=str(row["snippet"]) if row.get("snippet") else None,
                    rank=int(row.get("rank") or index),
                    provider=self.name,
                )
            )
        return results


class DuckDuckGoHtmlProvider:
    """Best-effort no-key search. Not an SLA and not a required project dependency."""

    name = "duckduckgo"

    def __init__(self, client: httpx.Client | None = None, timeout: float = 10, resolver=None) -> None:
        self.client = client
        self.timeout = timeout
        self.resolver = resolver

    def search(self, query: str, limit: int = 5) -> list[SearchResult]:
        owns = self.client is None
        client = self.client or httpx.Client(timeout=self.timeout, follow_redirects=False)
        try:
            target = "https://html.duckduckgo.com/html/"
            assert_public_http_url(target, self.resolver)
            response = client.post(target, data={"q": query}, headers={"User-Agent": "InsightHub/0.3"})
            if response.status_code >= 400:
                raise SearchUnavailable(f"DuckDuckGo HTML 返回 HTTP {response.status_code}")
            return parse_duckduckgo_html(response.text, limit)
        except SsrfError as exc:
            raise SearchUnavailable(exc.message) from exc
        except SearchUnavailable:
            raise
        except httpx.HTTPError as exc:
            raise SearchUnavailable("DuckDuckGo HTML 搜索不可用。") from exc
        finally:
            if owns:
                client.close()


class _ResultParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.anchors: list[tuple[str, str]] = []
        self.snippets: list[str] = []
        self._href: str | None = None
        self._class = ""
        self._text: list[str] = []
        self._snippet = False

    def handle_starttag(self, tag, attrs):
        mapping = {key: value or "" for key, value in attrs}
        classes = mapping.get("class", "")
        if tag == "a" and "result__a" in classes:
            self._href = mapping.get("href")
            self._class = classes
            self._text = []
        elif tag in {"a", "td", "div"} and "result__snippet" in classes:
            self._snippet = True
            self._text = []

    def handle_endtag(self, tag):
        if tag == "a" and self._href:
            self.anchors.append((self._href, " ".join(self._text).strip()))
            self._href = None
            self._text = []
        elif self._snippet and tag in {"a", "td", "div"}:
            snippet = " ".join(self._text).strip()
            if snippet:
                self.snippets.append(snippet)
            self._snippet = False
            self._text = []

    def handle_data(self, data):
        if self._href or self._snippet:
            self._text.append(data.strip())


def unwrap_duckduckgo_url(href: str) -> str:
    parts = urlsplit(href)
    if parts.path.startswith("/l/"):
        target = parse_qs(parts.query).get("uddg", [""])[0]
        if target:
            return unquote(target)
    return href


def parse_duckduckgo_html(html: str, limit: int) -> list[SearchResult]:
    parser = _ResultParser()
    parser.feed(html)
    results: list[SearchResult] = []
    for index, (href, title) in enumerate(parser.anchors):
        if len(results) >= limit:
            break
        url = unwrap_duckduckgo_url(href)
        if not url.startswith("http"):
            continue
        snippet = parser.snippets[index] if index < len(parser.snippets) else None
        results.append(SearchResult(url=url, title=title or None, snippet=snippet, rank=len(results) + 1, provider="duckduckgo"))
    return results
