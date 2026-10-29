from types import SimpleNamespace

from fastapi.testclient import TestClient

from app import main
from app.core.config import get_settings


def test_automation_test_startup_never_scans_user_covers(monkeypatch):
    calls = []

    class SessionStub:
        def close(self):
            pass

    session = SessionStub()
    monkeypatch.setattr(main, "get_sessionmaker", lambda: lambda: session)
    monkeypatch.setattr(main, "recover_stale_jobs", lambda _session: None)
    monkeypatch.setattr("app.core.config.get_settings", lambda: get_settings().model_copy(update={"insighthub_system_scope": "AUTOMATION_TEST"}))
    monkeypatch.setattr("app.services.cover.settings_prefs.load_cover_prefs", lambda *_args, **_kwargs: SimpleNamespace(auto_enabled=True))
    monkeypatch.setattr("app.services.cover.auto.scan_and_enqueue_auto_covers", lambda *_args, **_kwargs: calls.append("scan"))

    with TestClient(main.app):
        pass

    assert calls == []


def test_user_startup_scan_can_be_suppressed_for_safe_runtime_update(monkeypatch):
    calls = []

    class SessionStub:
        def close(self):
            pass

    session = SessionStub()
    monkeypatch.setattr(main, "get_sessionmaker", lambda: lambda: session)
    monkeypatch.setattr(main, "recover_stale_jobs", lambda _session: None)
    monkeypatch.setattr(
        "app.core.config.get_settings",
        lambda: get_settings().model_copy(
            update={"insighthub_system_scope": "USER", "cover_auto_startup_scan_enabled": False}
        ),
    )
    monkeypatch.setattr(
        "app.services.cover.settings_prefs.load_cover_prefs",
        lambda *_args, **_kwargs: SimpleNamespace(auto_enabled=True),
    )
    monkeypatch.setattr(
        "app.services.cover.auto.scan_and_enqueue_auto_covers",
        lambda *_args, **_kwargs: calls.append("scan"),
    )

    with TestClient(main.app):
        pass

    assert calls == []
