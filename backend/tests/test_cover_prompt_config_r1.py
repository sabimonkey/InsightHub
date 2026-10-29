import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.main import app
from app.models.cover import CoverPromptRevision
from app.services.cover.prompt import DEFAULT_GLOBAL_PROMPT
from app.services.cover.service import CoverGenerationService


@pytest.fixture
def isolated_prompt_session():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    CoverPromptRevision.__table__.create(engine)
    session = Session(engine)
    session.add(CoverPromptRevision(revision=1, prompt=DEFAULT_GLOBAL_PROMPT, version="global-cover-r1", is_active=True))
    session.commit()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _override_session(session):
    app.dependency_overrides[get_db] = lambda: session


def test_preview_uses_shared_builder_without_enqueuing(client, isolated_prompt_session, monkeypatch):
    source = SimpleNamespace(id=uuid.uuid4(), system_scope="AUTOMATION_TEST", display_name="Robotics notes")
    monkeypatch.setattr(isolated_prompt_session, "get", lambda _model, _source_id: source)
    built_prompt = f"{DEFAULT_GLOBAL_PROMPT} Article topic and visual subject: robotics. Palette direction (cool): cool cobalt. For this image only: clear robotic hand."
    monkeypatch.setattr(
        CoverGenerationService,
        "build_prompt_for_source",
        lambda self, *_args, **_kwargs: (built_prompt, True, source),
    )
    monkeypatch.setattr(
        CoverGenerationService,
        "enqueue",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("preview must not enqueue")),
    )
    _override_session(isolated_prompt_session)

    response = client.post("/api/cover/prompt-preview", json={
        "source_id": str(source.id), "global_prompt": DEFAULT_GLOBAL_PROMPT,
        "color_scheme": "cool", "personalization": "clear robotic hand",
    })
    body = response.json()
    assert body["ok"] is True
    assert body["prompt"] == built_prompt
    assert body["prompt_char_count"] == len(" ".join(built_prompt.split()))
    assert body["prompt_char_count"] <= 1500
    assert body["topic"] == "robotics"
    assert body["palette_direction"] == "cool cobalt"
    assert body["prompt_version"] == "global-cover-r1"


def test_update_and_reset_create_immutable_revisions_in_database(client, isolated_prompt_session):
    _override_session(isolated_prompt_session)
    edited = "A user-selected style prompt with clear subject contrast and topic-led colors."

    response = client.put(
        "/api/cover/prompt-config",
        json={"prompt": edited},
        headers={"origin": "http://127.0.0.1:5174"},
    )
    saved = response.json()
    assert saved["ok"] is True
    assert saved["revision"] == 2
    assert saved["prompt"] == edited
    assert isolated_prompt_session.get(CoverPromptRevision, 1).prompt == DEFAULT_GLOBAL_PROMPT

    reset = client.post("/api/cover/prompt-config/reset", headers={"origin": "http://127.0.0.1:5174"}).json()
    assert reset["ok"] is True
    assert reset["revision"] == 3
    assert reset["prompt"] == DEFAULT_GLOBAL_PROMPT
    assert isolated_prompt_session.get(CoverPromptRevision, 2).prompt == edited

    reread = client.get("/api/cover/prompt-config").json()
    assert reread["revision"] == 3
    assert reread["prompt"] == DEFAULT_GLOBAL_PROMPT


def test_global_prompt_enforces_context_budget(client, isolated_prompt_session):
    _override_session(isolated_prompt_session)
    response = client.put(
        "/api/cover/prompt-config",
        json={"prompt": "x" * 801},
        headers={"origin": "http://127.0.0.1:5174"},
    )
    assert response.status_code == 422
