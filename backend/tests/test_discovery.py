import io
from pathlib import Path

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.discovery import OriginalSourceCandidate, SourceDiscoveryRun, SourceRelation
from app.models.enums import IngestionOrigin
from app.models.extraction import ExtractionRun
from app.models.ingestion_record import IngestionRecord
from app.models.source_item import SourceItem
from app.services.discovery.identifiers import find_identifiers
from app.services.discovery.ranking import merge_drafts
from app.services.discovery.resolvers import UrlSourceResolver
from app.services.discovery.search import DuckDuckGoHtmlProvider, SearchResult, SearchUnavailable
from app.services.discovery.service import DiscoveryService
from app.services.extraction.service import ExtractionService
from app.services.ingestion.service import IngestionService


class FakeSearch:
    name = "fake"

    def __init__(self, results=None, error: bool = False) -> None:
        self.results = results or []
        self.error = error
        self.queries: list[str] = []

    def search(self, query: str, limit: int = 5) -> list[SearchResult]:
        self.queries.append(query)
        if self.error:
            raise SearchUnavailable("down")
        return list(self.results)[:limit]


def _public(_host: str) -> list[str]:
    return ["93.184.216.34"]


def _discovery(session: Session, raw_root: Path, tmp_path: Path, search, http_client=None) -> DiscoveryService:
    ingest = IngestionService(session, raw_root, max_upload_size_bytes=2_000_000)
    extraction = ExtractionService(
        session,
        raw_root,
        tmp_path / "extracted",
        inline=True,
        chunk_max_chars=2000,
        chunk_overlap_chars=50,
        max_pdf_pages=5,
        web_timeout=2,
        web_max_bytes=100_000,
        web_max_redirects=2,
        http_client=http_client,
        resolver=_public,
    )
    return DiscoveryService(
        session,
        ingest,
        inline=True,
        search=search,
        extraction=extraction,
        timeout=2,
        max_bytes=100_000,
        max_redirects=2,
        http_client=http_client,
        resolver=_public,
    )


def test_identifier_doi_arxiv_github_and_x_status():
    hits = find_identifiers(
        "See 10.1145/1234567 and arXiv: 2609.22978 plus https://github.com/deepseek-ai/DeepEP "
        "https://x.com/alice/status/999?s=46&t=zz"
    )
    urls = [hit.url for hit in hits]
    assert "https://doi.org/10.1145/1234567" in urls
    assert "https://arxiv.org/abs/2609.22978" in urls
    assert "https://github.com/deepseek-ai/DeepEP" in urls
    assert "https://x.com/alice/status/999" in urls


def test_text_doi_and_arxiv_skip_search(db_session, raw_root, tmp_path):
    search = FakeSearch(error=True)
    service = _discovery(db_session, raw_root, tmp_path, search)
    ingest = service.ingestion
    doi = ingest.ingest_text("Paper note doi 10.1038/nature12373")
    run = service.start(doi.source_item.id)
    assert run.status == "SUCCEEDED"
    assert search.queries == []
    candidates = _candidates(db_session, run.id)
    assert candidates[0].normalized_candidate_url == "https://doi.org/10.1038/nature12373"
    assert candidates[0].candidate_type == "PAPER"
    assert candidates[0].status == "PROPOSED"
    arxiv = ingest.ingest_text("DeepSeek Elastic Compute\narXiv: 2609.22978")
    run = service.start(arxiv.source_item.id)
    urls = [row.normalized_candidate_url for row in _candidates(db_session, run.id)]
    assert "https://arxiv.org/abs/2609.22978" in urls


def test_url_metadata_canonical_og_and_referenced_link():
    html = """<html><head>
    <title>Repost</title>
    <link rel="canonical" href="https://publisher.example/original" />
    <meta property="og:url" content="https://publisher.example/original" />
    </head><body><p>Read the paper at https://arxiv.org/abs/2609.22978</p>
    <a href="https://github.com/deepseek-ai/DeepEP">code</a></body></html>"""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/start":
            return httpx.Response(302, headers={"location": "http://example.test/final"})
        return httpx.Response(200, text=html)

    client = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False)
    search = FakeSearch(error=True)
    drafts, _summary, error_code, _message = UrlSourceResolver(search, 2, 100_000, 3, client, _public).resolve(
        "http://example.test/start"
    )
    provenances = set()
    for item in drafts:
        provenances.add(item.evidence.get("provenance"))
        provenances.update(item.evidence.get("provenances") or [])
    assert "REDIRECT" in provenances
    assert "HTML_CANONICAL" in provenances
    assert "OG_URL" in provenances
    assert "REFERENCED_LINK" in provenances
    assert error_code is None
    assert search.queries == []


def test_image_ocr_text_builds_short_query_and_ranks_paper(db_session, raw_root, tmp_path):
    search = FakeSearch(
        results=[
            SearchResult("https://blog.example/post", "a blog about the paper", "keyword only", 1, "fake"),
            SearchResult("https://arxiv.org/abs/2609.22978", "Elastic Compute paper", "unique elastic phrase here", 2, "fake"),
        ]
    )
    service = _discovery(db_session, raw_root, tmp_path, search)
    created = service.ingestion.ingest_text("Screenshot OCR\n\nThis unique elastic phrase should not be the whole page. @alice")
    created.source_item.source_type = "IMAGE"
    db_session.commit()
    run = service.start(created.source_item.id)
    assert run.status == "SUCCEEDED"
    assert search.queries
    assert len(search.queries[0]) < len(created.ingestion_record.original_input)
    assert "unique elastic phrase" in search.queries[0]
    rows = _candidates(db_session, run.id)
    assert rows[0].normalized_candidate_url.startswith("https://arxiv.org/")
    assert rows[0].score > rows[1].score
    assert any("paper host" in reason for reason in rows[0].match_reasons_json)


def test_candidate_dedup_merges_reasons():
    from app.services.discovery.ranking import CandidateDraft

    first = CandidateDraft("https://arxiv.org/abs/1", "https://arxiv.org/abs/1", "t", None, None, "PAPER", 0.4, 0.4, ["title overlap"], {"provenance": "SEARCH"})
    second = CandidateDraft("https://arxiv.org/abs/1", "https://arxiv.org/abs/1", "t", None, None, "PAPER", 0.9, 0.9, ["DOI exact match"], {"provenance": "IDENTIFIER"})
    merged = merge_drafts([first, second])
    assert len(merged) == 1
    assert "title overlap" in merged[0].match_reasons
    assert "DOI exact match" in merged[0].match_reasons


def test_confirm_creates_or_reuses_and_is_idempotent(db_session, raw_root, tmp_path):
    service = _discovery(db_session, raw_root, tmp_path, FakeSearch())
    origin = service.ingestion.ingest_text("doi 10.1000/confirm-me")
    origin_type = origin.source_item.source_type
    run = service.start(origin.source_item.id)
    candidate = _candidates(db_session, run.id)[0]
    _candidate, relation, target = service.confirm(candidate.id)
    assert origin.source_item.source_type == origin_type
    assert target.source_type == "URL"
    assert target.canonical_url == "https://doi.org/10.1000/confirm-me"
    record = db_session.scalar(select(IngestionRecord).where(IngestionRecord.source_item_id == target.id))
    assert record.origin == IngestionOrigin.SYSTEM_DISCOVERY.value
    again_candidate, again_relation, again_target = service.confirm(candidate.id)
    assert again_relation.id == relation.id
    assert again_target.id == target.id
    assert again_candidate.status == "CONFIRMED"
    count = db_session.scalar(select(func.count()).select_from(SourceRelation).where(SourceRelation.from_source_id == origin.source_item.id))
    assert count == 1
    existing = service.ingestion.ingest_url("https://doi.org/10.1000/already")
    other = service.ingestion.ingest_text("doi 10.1000/already")
    other_run = service.start(other.source_item.id)
    other_candidate = _candidates(db_session, other_run.id)[0]
    _row, reused_relation, reused_target = service.confirm(other_candidate.id)
    assert reused_target.id == existing.source_item.id
    assert reused_relation.from_source_id == other.source_item.id


def test_reject_is_remembered_on_rediscover(db_session, raw_root, tmp_path):
    service = _discovery(db_session, raw_root, tmp_path, FakeSearch())
    created = service.ingestion.ingest_text("doi 10.1000/reject-me")
    first = service.start(created.source_item.id)
    candidate = _candidates(db_session, first.id)[0]
    rejected = service.reject(candidate.id)
    assert rejected.status == "REJECTED"
    second = service.start(created.source_item.id)
    assert second.id != first.id
    assert db_session.get(SourceDiscoveryRun, first.id) is not None
    again = _candidates(db_session, second.id)[0]
    assert again.evidence_json["previously_rejected"] is True
    assert "Previously Rejected" in again.match_reasons_json
    assert db_session.get(OriginalSourceCandidate, candidate.id).status == "REJECTED"


def test_search_failure_does_not_change_extraction(db_session, raw_root, tmp_path):
    service = _discovery(db_session, raw_root, tmp_path, FakeSearch(error=True))
    created = service.ingestion.ingest_text("no identifier just a pasted paragraph about widgets")
    extraction_run = service.extraction.schedule(created.source_item.id, "MANUAL", force=True)
    before = extraction_run.status
    ingest_status = created.ingestion_record.status
    run = service.start(created.source_item.id)
    assert run.status == "FAILED"
    assert run.error_code == "SEARCH_UNAVAILABLE"
    assert db_session.get(ExtractionRun, extraction_run.id).status == before
    assert db_session.get(IngestionRecord, created.ingestion_record.id).status == ingest_status
    assert db_session.get(SourceItem, created.source_item.id).source_type == "TEXT"


def test_private_candidate_and_redirect_are_blocked(db_session, raw_root, tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/bounce":
            return httpx.Response(302, headers={"location": "http://127.0.0.1/secret"})
        return httpx.Response(200, text="<html><title>x</title><body><p>short</p></body></html>")

    client = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False)
    search = FakeSearch(results=[SearchResult("http://127.0.0.1/hidden", "local", "no", 1, "fake")])
    service = _discovery(db_session, raw_root, tmp_path, search, http_client=client)
    created = service.ingestion.ingest_url("http://example.test/bounce")
    run = service.start(created.source_item.id)
    assert run.status == "FAILED"
    assert run.error_code == "SSRF_BLOCKED"
    pasted = service.ingestion.ingest_text("plain words without an identifier")
    search.results = [SearchResult("http://10.1.2.3/hidden", "local", "no", 1, "fake")]
    search.error = False
    found = service.start(pasted.source_item.id)
    assert _candidates(db_session, found.id) == []


def test_x_access_failure_is_not_source_not_found():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text="blocked")

    client = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False)
    search = FakeSearch(
        results=[
            SearchResult("https://nitter.example/alice/status/55", "mirror", "post", 1, "fake"),
            SearchResult("https://x.com/alice/status/55?s=1&t=2", "original", "post", 2, "fake"),
        ]
    )
    drafts, _summary, error_code, _message = UrlSourceResolver(search, 2, 10000, 2, client, _public).resolve(
        "https://x.com/alice/status/55?s=1&t=2"
    )
    assert error_code != "SOURCE_NOT_FOUND"
    urls = [item.normalized_url for item in drafts]
    assert "https://x.com/alice/status/55" in urls
    mirror = next(item for item in drafts if "nitter" in item.normalized_url)
    assert mirror.candidate_type == "MIRROR"


def test_confirm_extraction_is_independent(db_session, raw_root, tmp_path):
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="nope")

    client = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False)
    service = _discovery(db_session, raw_root, tmp_path, FakeSearch(), http_client=client)
    created = service.ingestion.ingest_text("doi 10.1000/extract-fail")
    run = service.start(created.source_item.id)
    candidate = _candidates(db_session, run.id)[0]
    _candidate, relation, target = service.confirm(candidate.id)
    extraction = db_session.scalar(select(ExtractionRun).where(ExtractionRun.source_item_id == target.id))
    assert relation.id is not None
    assert extraction is not None
    assert extraction.status == "FAILED"
    assert db_session.get(SourceRelation, relation.id) is not None


def test_duckduckgo_parser_unwraps_results():
    html = """
    <a class="result__a" href="/l/?uddg=https%3A%2F%2Farxiv.org%2Fabs%2F2609.22978&amp;rut=1">Paper</a>
    <a class="result__snippet">snippet text</a>
    """
    provider = DuckDuckGoHtmlProvider(
        client=httpx.Client(
            transport=httpx.MockTransport(lambda _request: httpx.Response(200, text=html)),
            follow_redirects=False,
        ),
        resolver=_public,
    )
    results = provider.search("arxiv", limit=3)
    assert results[0].url == "https://arxiv.org/abs/2609.22978"
    assert results[0].provider == "duckduckgo"


def test_manual_candidate_rejects_private_url(db_session, raw_root, tmp_path):
    service = _discovery(db_session, raw_root, tmp_path, FakeSearch())
    created = service.ingestion.ingest_text("manual later")
    try:
        service.add_manual(created.source_item.id, "http://127.0.0.1/secret")
        raise AssertionError("private url should fail")
    except Exception as exc:
        assert getattr(exc, "code", "") == "SSRF_BLOCKED"
    row = service.add_manual(created.source_item.id, "https://example.com/known?utm_source=abc")
    assert row.candidate_type == "MANUAL"
    assert row.normalized_candidate_url == "https://example.com/known"
    assert row.evidence_json["provenance"] == "MANUAL"


def test_start_returns_pending_until_worker_runs(db_session, raw_root, tmp_path):
    calls: list[str] = []
    ingest = IngestionService(db_session, raw_root, max_upload_size_bytes=10_000)
    created = ingest.ingest_text("doi 10.1000/queued")
    service = DiscoveryService(
        db_session,
        ingest,
        inline=False,
        search=FakeSearch(),
        enqueue=calls.append,
        timeout=2,
        max_bytes=1000,
        max_redirects=1,
        resolver=_public,
    )
    run = service.start(created.source_item.id)
    assert run.status == "PENDING"
    assert calls == [str(run.id)]
    finished = service.execute(run.id)
    assert finished.status == "SUCCEEDED"


def _candidates(session: Session, run_id) -> list[OriginalSourceCandidate]:
    return list(
        session.scalars(
            select(OriginalSourceCandidate).where(OriginalSourceCandidate.discovery_run_id == run_id).order_by(OriginalSourceCandidate.rank.asc())
        ).all()
    )
