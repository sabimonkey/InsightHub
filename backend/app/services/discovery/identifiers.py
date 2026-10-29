import re
from dataclasses import dataclass, field
from urllib.parse import urlsplit

DOI_RE = re.compile(r"\b(10\.\d{4,9}/[-._;()/:A-Z0-9]+)\b", re.IGNORECASE)
ARXIV_RE = re.compile(r"(?:arxiv(?:\.org/(?:abs|pdf)/|:)\s*)(\d{4}\.\d{4,5})(v\d+)?", re.IGNORECASE)
GITHUB_RE = re.compile(r"github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)", re.IGNORECASE)
X_STATUS_RE = re.compile(
    r"(?:https?://)?(?:www\.|mobile\.)?(?:x\.com|twitter\.com)/([A-Za-z0-9_]{1,15})/status/(\d+)",
    re.IGNORECASE,
)
HTTP_RE = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)


@dataclass
class IdentifierHit:
    url: str
    candidate_type: str
    reason: str
    provenance: str
    score: float
    title: str | None = None
    author: str | None = None
    publisher: str | None = None


def find_identifiers(text: str) -> list[IdentifierHit]:
    hits: list[IdentifierHit] = []
    seen: set[str] = set()

    def add(hit: IdentifierHit) -> None:
        key = hit.url.lower()
        if key in seen:
            return
        seen.add(key)
        hits.append(hit)

    for match in DOI_RE.finditer(text or ""):
        doi = match.group(1).rstrip(".,);")
        add(
            IdentifierHit(
                url=f"https://doi.org/{doi}",
                candidate_type="PAPER",
                reason="DOI exact match",
                provenance="IDENTIFIER",
                score=0.98,
                publisher="doi.org",
                title=doi,
            )
        )
    for match in ARXIV_RE.finditer(text or ""):
        arxiv_id = match.group(1)
        add(
            IdentifierHit(
                url=f"https://arxiv.org/abs/{arxiv_id}",
                candidate_type="PAPER",
                reason="arXiv id exact match",
                provenance="IDENTIFIER",
                score=0.97,
                publisher="arxiv.org",
                title=f"arXiv:{arxiv_id}",
            )
        )
    for match in X_STATUS_RE.finditer(text or ""):
        user, status_id = match.group(1), match.group(2)
        add(
            IdentifierHit(
                url=f"https://x.com/{user}/status/{status_id}",
                candidate_type="ORIGINAL",
                reason="X status id exact match",
                provenance="IDENTIFIER",
                score=0.96,
                author=user,
                publisher="x.com",
            )
        )
    for match in GITHUB_RE.finditer(text or ""):
        owner, repo = match.group(1), match.group(2).removesuffix(".git")
        if owner.lower() in {"features", "topics", "collections"}:
            continue
        add(
            IdentifierHit(
                url=f"https://github.com/{owner}/{repo}",
                candidate_type="REPOSITORY",
                reason="GitHub owner/repo exact match",
                provenance="IDENTIFIER",
                score=0.9,
                author=owner,
                publisher="github.com",
                title=f"{owner}/{repo}",
            )
        )
    for match in HTTP_RE.finditer(text or ""):
        raw = match.group(0).rstrip(".,);")
        host = (urlsplit(raw).hostname or "").lower()
        if host in {"x.com", "twitter.com", "www.x.com", "www.twitter.com", "mobile.x.com", "mobile.twitter.com"}:
            continue
        if "github.com" in host or host == "arxiv.org" or host == "doi.org":
            continue
        add(
            IdentifierHit(
                url=raw,
                candidate_type="UNKNOWN",
                reason="URL found in text",
                provenance="IDENTIFIER",
                score=0.7,
            )
        )
    return hits


@dataclass
class SearchClues:
    text: str
    queries: list[str] = field(default_factory=list)
    handles: list[str] = field(default_factory=list)
    title: str | None = None
    distinctive: str | None = None


def build_search_clues(text: str) -> SearchClues:
    body = (text or "").strip()
    lines = [line.strip() for line in body.splitlines() if line.strip()]
    title = lines[0][:120] if lines and len(lines[0]) <= 140 else None
    handles = re.findall(r"@([A-Za-z0-9_]{2,30})", body)
    sentences = [part.strip() for part in re.split(r"(?<=[.!?。])\s+|\n+", body) if part.strip()]
    distinctive = ""
    if sentences:
        distinctive = max(sentences, key=lambda item: (len(set(item.split())), len(item)))
    distinctive = distinctive[:160]
    queries: list[str] = []
    if distinctive and handles:
        queries.append(f"\"{distinctive[:80]}\" @{handles[0]}")
    elif distinctive:
        queries.append(f"\"{distinctive[:80]}\"")
    if title and title not in queries:
        queries.append(title)
    return SearchClues(text=body, queries=queries[:3], handles=handles, title=title, distinctive=distinctive or None)
