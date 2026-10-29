import uuid

import pytest

from app.core.config import get_settings
from app.services.cover.prompt import build_cover_prompt, prompt_hash
from app.services.cover.service import CoverGenerationService, CoverServiceError
from app.services.cover.storage import save_cover_bytes
from app.services.image.minimax import generate_image
from app.services.llm.deployments import sync_deployments


def test_build_cover_prompt_usable_with_title():
    prompt, usable = build_cover_prompt(
        title="OpenKB — AI 知识管理工具",
        categories=["knowledge"],
        source_type="URL",
        summary="",
        points=[],
    )
    assert usable is True
    assert "OpenKB" in prompt
    assert prompt_hash(prompt)


def test_minimax_fake_generates_png():
    settings = get_settings().model_copy(update={"minimax_enable_fake": True})
    result = generate_image("test prompt", settings=settings)
    assert result.ok is True
    assert result.image_bytes
    assert len(result.image_bytes) > 10


def test_save_cover_bytes_rejects_invalid(db_session, tmp_path, monkeypatch):
    settings = get_settings().model_copy(update={"cover_storage_subdir": str(tmp_path / "covers")})
    monkeypatch.setattr("app.services.cover.storage.get_settings", lambda: settings)
    with pytest.raises(Exception) as exc:
        save_cover_bytes(uuid.uuid4(), b"not-an-image", settings=settings)
    assert exc.value.code == "COVER_CONTENT_TYPE"


def test_execute_marks_failed_on_api_error(db_session, monkeypatch):
    from datetime import datetime, timezone

    from app.models.cover import CoverGenerationRun
    from app.models.source_item import SourceItem
    from app.services.image.minimax import MinimaxImageResult

    monkeypatch.setenv("MINIMAX_API_KEY", "fake")
    settings = get_settings().model_copy(update={"minimax_enable_fake": False, "minimax_api_key": "fake", "cover_inline": False})
    sync_deployments(db_session, settings)
    now = datetime.now(timezone.utc)
    source = SourceItem(
        id=uuid.uuid4(),
        source_type="URL",
        display_name="Cover failure path title",
        status="STORED",
        privacy_level="PRIVATE",
        system_scope="USER",
        created_at=now,
        updated_at=now,
    )
    db_session.add(source)
    db_session.commit()
    service = CoverGenerationService(db_session, settings=settings)
    deployment, _ = service.resolve_image_deployment()
    run = CoverGenerationRun(
        id=uuid.uuid4(),
        source_item_id=source.id,
        deployment_id=deployment.id,
        status="QUEUED",
        stage="QUEUED",
        prompt="editorial cover test",
        prompt_version="cover-v1",
        created_at=now,
        updated_at=now,
    )
    db_session.add(run)
    db_session.commit()

    monkeypatch.setattr(
        "app.services.cover.service.generate_image",
        lambda *_a, **_k: MinimaxImageResult(
            ok=False,
            image_bytes=None,
            latency_ms=10,
            model="image-01",
            code="INVALID_API_KEY",
            message="MiniMax API Key 无效。",
        ),
    )
    service.execute(run.id)
    db_session.refresh(run)
    assert run.status == "FAILED"
    assert run.error_code == "INVALID_API_KEY"


def test_enqueue_requires_confirmation(db_session, monkeypatch):
    from datetime import datetime, timezone

    from app.models.source_item import SourceItem

    monkeypatch.setenv("MINIMAX_API_KEY", "fake")
    settings = get_settings().model_copy(update={"minimax_enable_fake": True, "cover_inline": False})
    sync_deployments(db_session, settings)
    now = datetime.now(timezone.utc)
    source = SourceItem(
        id=uuid.uuid4(),
        source_type="URL",
        display_name="Long enough title for cover",
        status="STORED",
        privacy_level="PRIVATE",
        system_scope="USER",
        created_at=now,
        updated_at=now,
    )
    db_session.add(source)
    db_session.commit()
    service = CoverGenerationService(db_session, settings=settings)
    with pytest.raises(CoverServiceError) as exc:
        service.enqueue(source.id, prompt=None, confirm_send=False)
    assert exc.value.code == "CONFIRMATION_REQUIRED"
