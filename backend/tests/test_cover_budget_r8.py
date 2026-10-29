import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.models.cover import CoverGenerationRun
from app.models.analysis import LLMModelDeployment, LLMProviderConfig
from app.models.extraction import ExtractedDocument, ExtractionRun
from app.models.source_item import SourceItem
from app.services.cover.service import CoverGenerationService, CoverServiceError


def test_project_cap_can_be_raised_above_historical_53_attempts(db_session, monkeypatch):
    now = datetime.now(timezone.utc)
    source = SourceItem(
        id=uuid.uuid4(),
        source_type="URL",
        original_url="https://example.test/cover-budget-r8",
        canonical_url="https://example.test/cover-budget-r8",
        display_name="Technology research with substantive extracted article content",
        status="STORED",
        privacy_level="PRIVATE",
        system_scope="USER",
        created_at=now,
        updated_at=now,
    )
    extraction = ExtractionRun(
        id=uuid.uuid4(), source_item_id=source.id, status="SUCCEEDED", trigger="REEXTRACT",
        extractor_type="WEB", extractor_version="test", is_current=True,
        created_at=now, updated_at=now,
    )
    db_session.add(source)
    db_session.flush()
    db_session.add(extraction)
    db_session.flush()
    doc = ExtractedDocument(
        id=uuid.uuid4(), extraction_run_id=extraction.id, source_item_id=source.id,
        source_asset_id=None, extractor_type="WEB", extractor_version="test", status="SUCCEEDED",
        title=source.display_name, plain_text="Substantive article text about a technology research topic.",
        structured_text="[]", language="en", metadata_json={"content_completeness": "complete"},
        content_hash="b" * 64, created_at=now, updated_at=now,
    )
    db_session.add(doc)
    db_session.commit()

    settings = get_settings().model_copy(update={"minimax_enable_fake": False, "cover_inline": False})
    service = CoverGenerationService(db_session, settings=settings)
    provider = db_session.scalar(select(LLMProviderConfig).where(LLMProviderConfig.provider_type == "MINIMAX_IMAGE"))
    if provider is None:
        provider = LLMProviderConfig(id=uuid.uuid4(), name="MiniMax", provider_type="MINIMAX_IMAGE", base_url="https://api.minimax.cn", model="image-01", is_local=False, enabled=True, api_key_env="MINIMAX_API_KEY", capabilities_json={})
        db_session.add(provider); db_session.flush()
    deployment = db_session.scalar(select(LLMModelDeployment).where(LLMModelDeployment.provider_config_id == provider.id))
    if deployment is None:
        deployment = LLMModelDeployment(id=uuid.uuid4(), provider_config_id=provider.id, display_name="image-01", model_id="image-01", enabled=True, capabilities_json={})
        db_session.add(deployment); db_session.flush()
    monkeypatch.setattr(
        service,
        "resolve_image_deployment",
        lambda: (deployment, provider),
    )
    monkeypatch.setattr("app.services.cover.service.lock_monthly_budget", lambda *_a, **_kw: (53, 100))
    monkeypatch.setattr("app.jobs.cover_generation.enqueue_cover_generation", lambda *_a, **_kw: None)

    run = service.enqueue(source.id, prompt=None, confirm_send=True, color_scheme="auto")

    assert run.status == "QUEUED"
    assert db_session.query(CoverGenerationRun).filter_by(source_item_id=source.id).count() == 1


def test_explicit_local_cap_still_blocks_when_reached(db_session, monkeypatch):
    now = datetime.now(timezone.utc)
    source = SourceItem(
        id=uuid.uuid4(), source_type="URL", original_url="https://example.test/cap-reached",
        canonical_url="https://example.test/cap-reached", display_name="Technology research cover budget",
        status="STORED", privacy_level="PRIVATE", system_scope="USER", created_at=now, updated_at=now,
    )
    extraction = ExtractionRun(id=uuid.uuid4(), source_item_id=source.id, status="SUCCEEDED", trigger="REEXTRACT",
        extractor_type="WEB", extractor_version="test", is_current=True, created_at=now, updated_at=now)
    db_session.add(source); db_session.flush(); db_session.add(extraction); db_session.flush()
    db_session.add(ExtractedDocument(id=uuid.uuid4(), extraction_run_id=extraction.id, source_item_id=source.id,
        source_asset_id=None, extractor_type="WEB", extractor_version="test", status="SUCCEEDED",
        title=source.display_name, plain_text="Substantive article text about technology.", structured_text="[]",
        language="en", metadata_json={"content_completeness": "complete"}, content_hash="c" * 64,
        created_at=now, updated_at=now))
    db_session.commit()
    service = CoverGenerationService(db_session, settings=get_settings().model_copy(update={"minimax_enable_fake": False}))
    monkeypatch.setattr(service, "resolve_image_deployment", lambda: (SimpleNamespace(id=uuid.uuid4()), SimpleNamespace(id=uuid.uuid4())))
    monkeypatch.setattr("app.services.cover.service.lock_monthly_budget", lambda *_a, **_kw: (53, 30))
    with pytest.raises(CoverServiceError) as caught:
        service.enqueue(source.id, prompt=None, confirm_send=True, color_scheme="auto")
    assert caught.value.code == "COVER_MONTHLY_BUDGET_EXCEEDED"
    assert "53/30" in caught.value.message
