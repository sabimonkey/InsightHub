from dataclasses import dataclass, field
from urllib.parse import urlsplit

from app.services.discovery.identifiers import SearchClues
from app.services.discovery.search import SearchResult

MIRROR_HOSTS = ("nitter.", "xcancel.com", "threadreaderapp.com")
PAPER_HOSTS = ("arxiv.org", "doi.org", "pubmed.ncbi.nlm.nih.gov")
ARCHIVE_HOSTS = ("web.archive.org", "archive.is", "archive.ph")


@dataclass
class CandidateDraft:
    url: str
    normalized_url: str
    title: str | None
    author: str | None
    publisher: str | None
    candidate_type: str
    score: float
    confidence: float
    match_reasons: list[str] = field(default_factory=list)
    evidence: dict = field(default_factory=dict)


def classify_host(url: str) -> str:
    host = (urlsplit(url).hostname or "").lower()
    if any(host == item or host.endswith("." + item) or item in host for item in PAPER_HOSTS):
        return "PAPER"
    if host == "github.com" or host.endswith(".github.com"):
        return "REPOSITORY"
    if any(item in host for item in MIRROR_HOSTS):
        return "MIRROR"
    if any(host == item or host.endswith(item) for item in ARCHIVE_HOSTS):
        return "ARCHIVE"
    return "UNKNOWN"


def from_search_result(result: SearchResult, clues: SearchClues) -> CandidateDraft:
    kind = classify_host(result.url)
    reasons = [f"search:{result.provider}", f"search rank {result.rank}"]
    score = 0.34 + max(0, 6 - result.rank) * 0.02
    if kind == "PAPER":
        score += 0.35
        reasons.append("paper host preferred over secondary pages")
    elif kind == "REPOSITORY":
        score += 0.18
        reasons.append("github repository")
    elif kind == "ARCHIVE":
        score += 0.05
        reasons.append("archive clue")
    elif kind == "MIRROR":
        score = min(score, 0.42)
        reasons.append("mirror is a clue, not the original")
    blob = " ".join(filter(None, [result.title, result.snippet])).lower()
    if clues.distinctive and clues.distinctive[:40].lower() in blob:
        score += 0.12
        reasons.append("unique phrase overlap")
    if clues.title and clues.title[:40].lower() in blob:
        score += 0.1
        reasons.append("title overlap")
    if clues.handles and any(handle.lower() in blob for handle in clues.handles):
        score += 0.12
        reasons.append("author handle match")
    score = max(0.0, min(score, 0.99))
    return CandidateDraft(
        url=result.url,
        normalized_url=result.url,
        title=result.title,
        author=clues.handles[0] if clues.handles else None,
        publisher=(urlsplit(result.url).hostname or None),
        candidate_type=kind if kind != "UNKNOWN" else "REPOST",
        score=score,
        confidence=round(min(score, 0.9), 4),
        match_reasons=reasons,
        evidence={"provenance": "SEARCH", "snippet": result.snippet, "untrusted_content": True, "provider": result.provider},
    )


def merge_drafts(drafts: list[CandidateDraft]) -> list[CandidateDraft]:
    merged: dict[str, CandidateDraft] = {}
    for draft in drafts:
        key = draft.normalized_url
        current = merged.get(key)
        if current is None:
            merged[key] = draft
            continue
        for reason in draft.match_reasons:
            if reason not in current.match_reasons:
                current.match_reasons.append(reason)
        provenances = current.evidence.setdefault("provenances", [current.evidence.get("provenance")])
        extra = draft.evidence.get("provenance")
        if extra and extra not in provenances:
            provenances.append(extra)
        if draft.score > current.score:
            current.score = draft.score
            current.confidence = draft.confidence
            current.candidate_type = draft.candidate_type
            current.title = draft.title or current.title
        current.evidence.update({key: value for key, value in draft.evidence.items() if key not in current.evidence})
    ordered = sorted(merged.values(), key=lambda item: (-item.score, item.normalized_url))
    return ordered
