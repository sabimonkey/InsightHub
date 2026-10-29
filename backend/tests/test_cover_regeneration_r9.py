import io
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

from PIL import Image, ImageDraw
from sqlalchemy import select

from app.core.config import get_settings
from app.db.session import get_sessionmaker
from app.models.analysis import LLMModelDeployment, LLMProviderConfig
from app.models.cover import CoverGenerationRun, SourceCoverAsset
from app.models.extraction import ExtractedDocument, ExtractionRun
from app.models.source_item import SourceItem
from app.services.cover.service import CoverGenerationService
from app.services.cover.status_view import build_cover_status_payload
from app.services.image.minimax import MinimaxImageResult
from app.services.llm.deployments import sync_deployments


def _image_bytes(color: str) -> bytes:
    image = Image.new("RGB", (320, 200), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((80, 35, 240, 165), fill=color)
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def _source(db_session, tmp_path, monkeypatch, *, current_cover=True):
    from app.services.cover.storage import save_cover_bytes

    now = datetime.now(timezone.utc)
    source = SourceItem(
        id=uuid.uuid4(), source_type="TEXT", display_name="Robotics research with article content",
        status="STORED", privacy_level="PRIVATE", system_scope="AUTOMATION_TEST",
        created_at=now, updated_at=now,
    )
    db_session.add(source)
    db_session.flush()
    extraction = ExtractionRun(
        id=uuid.uuid4(), source_item_id=source.id, status="SUCCEEDED", trigger="MANUAL",
        extractor_type="TEXT", extractor_version="test", is_current=True, created_at=now, updated_at=now,
    )
    db_session.add(extraction)
    db_session.flush()
    db_session.add(ExtractedDocument(
        id=uuid.uuid4(), extraction_run_id=extraction.id, source_item_id=source.id,
        source_asset_id=None, extractor_type="TEXT", extractor_version="test", status="SUCCEEDED",
        title=source.display_name, plain_text="A robotics research article about a compact robotic arm.",
        structured_text="[]", language="en", metadata_json={"content_completeness": "complete"},
        content_hash="d" * 64, created_at=now, updated_at=now,
    ))
    settings = get_settings().model_copy(update={
        "minimax_enable_fake": True,
        "cover_inline": False,
        "cover_storage_subdir": get_settings().cover_storage_subdir,
        "insighthub_system_scope": "AUTOMATION_TEST",
    })
    monkeypatch.setattr("app.services.cover.storage.PROJECT_ROOT", tmp_path)
    if current_cover:
        relative, content_hash, _ = save_cover_bytes(source.id, _image_bytes("#182b4d"), settings)
        db_session.add(SourceCoverAsset(
            id=uuid.uuid4(), source_item_id=source.id, kind="GENERATED", provider_type="MINIMAX_IMAGE",
            model_id="image-01", content_hash=content_hash, relative_path=relative, is_current=True,
            created_at=now,
        ))
    sync_deployments(db_session, settings)
    db_session.commit()
    provider = db_session.scalar(select(LLMProviderConfig).where(LLMProviderConfig.provider_type == "MINIMAX_IMAGE"))
    deployment = db_session.scalar(select(LLMModelDeployment).where(LLMModelDeployment.provider_config_id == provider.id))
    service = CoverGenerationService(db_session, settings=settings)
    monkeypatch.setattr(service, "resolve_image_deployment", lambda: (deployment, provider))
    monkeypatch.setattr("app.jobs.cover_generation.enqueue_cover_generation", lambda *_a, **_kw: None)
    return source, service, settings


def test_generation_creates_candidate_and_preserves_current_until_user_applies(db_session, tmp_path, monkeypatch):
    source, service, settings = _source(db_session, tmp_path, monkeypatch)
    old = db_session.scalar(select(SourceCoverAsset).where(SourceCoverAsset.source_item_id == source.id, SourceCoverAsset.is_current.is_(True)))
    from app.api.cover import cover_prompt_preview
    preview = cover_prompt_preview(source.id, "auto", db_session)
    assert preview["ok"] is True
    assert preview["current_cover_url"].endswith(f"v={old.id}")
    monkeypatch.setattr("app.services.cover.service.generate_image", lambda *_a, **_kw: MinimaxImageResult(
        ok=True, image_bytes=_image_bytes("#246b84"), latency_ms=1, model="image-01",
    ))
    run = service.enqueue(source.id, prompt=None, confirm_send=True, color_scheme="cool")
    run = service.execute(run.id)

    db_session.refresh(old)
    candidate = db_session.get(SourceCoverAsset, run.asset_id)
    status = build_cover_status_payload(db_session, source.id, run=run)
    assert run.status == "SUCCEEDED"
    assert old.is_current is True
    assert candidate.is_current is False
    assert status["current_cover_url"].endswith(f"v={old.id}")
    assert status["candidate_asset_id"] == str(candidate.id)
    assert status["candidate_cover_url"].endswith(f"asset_id={candidate.id}")
    assert status["candidate_is_current"] is False

    service.apply_candidate(run.id)
    db_session.expire_all()
    assert db_session.get(SourceCoverAsset, old.id).is_current is False
    assert db_session.get(SourceCoverAsset, candidate.id).is_current is True
    assert db_session.get(CoverGenerationRun, run.id).candidate_review_state == "APPLIED"
    from app.services.library_preview import library_preview_proxy_path
    assert library_preview_proxy_path(db_session, source.id, None).endswith(f"v={candidate.id}")


def test_keep_old_is_persisted_and_does_not_move_current_pointer(db_session, tmp_path, monkeypatch):
    source, service, _settings = _source(db_session, tmp_path, monkeypatch)
    old = db_session.scalar(select(SourceCoverAsset).where(SourceCoverAsset.source_item_id == source.id, SourceCoverAsset.is_current.is_(True)))
    monkeypatch.setattr("app.services.cover.service.generate_image", lambda *_a, **_kw: MinimaxImageResult(
        ok=True, image_bytes=_image_bytes("#246b84"), latency_ms=1, model="image-01",
    ))
    run = service.enqueue(source.id, prompt=None, confirm_send=True)
    service.execute(run.id)
    candidate_id = run.asset_id

    service.keep_current(run.id)
    db_session.expire_all()
    assert db_session.get(SourceCoverAsset, old.id).is_current is True
    assert db_session.get(SourceCoverAsset, candidate_id).is_current is False
    assert db_session.get(CoverGenerationRun, run.id).candidate_review_state == "KEPT_OLD"
    assert build_cover_status_payload(db_session, source.id, run=db_session.get(CoverGenerationRun, run.id))["candidate_review_state"] == "KEPT_OLD"


def test_failed_regeneration_leaves_old_cover_current_and_no_candidate(db_session, tmp_path, monkeypatch):
    source, service, _settings = _source(db_session, tmp_path, monkeypatch)
    old = db_session.scalar(select(SourceCoverAsset).where(SourceCoverAsset.source_item_id == source.id, SourceCoverAsset.is_current.is_(True)))
    monkeypatch.setattr("app.services.cover.service.generate_image", lambda *_a, **_kw: MinimaxImageResult(
        ok=False, image_bytes=None, latency_ms=1, model="image-01", code="MINIMAX_ERROR", message="failed",
    ))
    run = service.enqueue(source.id, prompt=None, confirm_send=True)
    service.execute(run.id)
    db_session.refresh(old)
    assert run.status == "FAILED"
    assert old.is_current is True
    assert run.asset_id is None


def test_idempotency_key_reuses_run_and_budget_reservation(db_session, tmp_path, monkeypatch):
    source, service, _settings = _source(db_session, tmp_path, monkeypatch, current_cover=False)
    # Exercise the production reservation path without contacting MiniMax.
    source.system_scope = "USER"
    service.settings = service.settings.model_copy(update={"minimax_enable_fake": False})
    calls = []
    monkeypatch.setattr("app.services.cover.service.lock_monthly_budget", lambda *_a, **_kw: (calls.append(1) or 53, 100))
    key = str(uuid.uuid4())

    first = service.enqueue(source.id, prompt=None, confirm_send=True, idempotency_key=key)
    second = service.enqueue(source.id, prompt=None, confirm_send=True, idempotency_key=key)

    assert first.id == second.id == uuid.uuid5(source.id, key)
    assert len(calls) == 1
    assert db_session.scalar(select(CoverGenerationRun.id).where(CoverGenerationRun.source_item_id == source.id)) == first.id


def test_duplicate_job_delivery_does_not_generate_twice(db_session, tmp_path, monkeypatch):
    source, service, _ = _source(db_session, tmp_path, monkeypatch)
    calls = []
    def generate(*_a, **_kw):
        calls.append(1)
        return MinimaxImageResult(ok=True, image_bytes=_image_bytes("blue"), latency_ms=1, model="image-01")
    monkeypatch.setattr("app.services.cover.service.generate_image", generate)
    run = service.enqueue(source.id, prompt=None, confirm_send=True)
    service.execute(run.id)
    asset_id = run.asset_id
    service.execute(run.id)
    assert calls == [1]
    assert run.asset_id == asset_id


def test_saved_candidate_is_not_automatically_generated_again(db_session, tmp_path, monkeypatch):
    from app.services.cover.auto import classify_source_cover_bucket
    source, service, settings = _source(db_session, tmp_path, monkeypatch, current_cover=False)
    monkeypatch.setattr("app.services.cover.service.generate_image", lambda *_a, **_kw:
                        MinimaxImageResult(ok=True, image_bytes=_image_bytes("blue"), latency_ms=1, model="image-01"))
    monkeypatch.setattr("app.services.cover.auto.load_cover_prefs", lambda *_a, **_kw:
                        SimpleNamespace(requires_analysis=False, monthly_budget=100))
    run = service.enqueue(source.id, prompt=None, confirm_send=True)
    service.execute(run.id)
    assert classify_source_cover_bucket(db_session, source, settings=settings) == "candidate_saved"
    service.keep_current(run.id)
    assert classify_source_cover_bucket(db_session, source, settings=settings) == "candidate_saved"


def test_multiple_candidates_switch_atomically_and_rollback(db_session, tmp_path, monkeypatch):
    import pytest
    source, service, _ = _source(db_session, tmp_path, monkeypatch)
    monkeypatch.setattr("app.services.cover.service.generate_image", lambda *_a, **_kw:
                        MinimaxImageResult(ok=True, image_bytes=_image_bytes("blue"), latency_ms=1, model="image-01"))
    runs = []
    for _ in range(2):
        run = service.enqueue(source.id, prompt=None, confirm_send=True)
        service.execute(run.id)
        runs.append(run)
    for run in [runs[0], runs[1], runs[0]]:
        service.apply_candidate(run.id)
        db_session.expire_all()
        current = list(db_session.scalars(select(SourceCoverAsset.id).where(SourceCoverAsset.source_item_id == source.id, SourceCoverAsset.is_current.is_(True))))
        assert current == [run.asset_id]
    with monkeypatch.context() as patch:
        patch.setattr(db_session, "commit", lambda: (_ for _ in ()).throw(RuntimeError("commit failure")))
        with pytest.raises(RuntimeError, match="commit failure"):
            service.apply_candidate(runs[1].id)
    db_session.expire_all()
    current = list(db_session.scalars(select(SourceCoverAsset.id).where(SourceCoverAsset.source_item_id == source.id, SourceCoverAsset.is_current.is_(True))))
    assert current == [runs[0].asset_id]
