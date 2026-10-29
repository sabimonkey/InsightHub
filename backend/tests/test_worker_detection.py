from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.services.maintenance import system


def test_worker_detection_ignores_stale_rq_registry_entries(monkeypatch):
    now = datetime.now(timezone.utc)
    workers = [
        SimpleNamespace(last_heartbeat=now - timedelta(minutes=8), hostname="local", pid=123),
        SimpleNamespace(last_heartbeat=now - timedelta(minutes=8), hostname="local", pid=456),
    ]
    monkeypatch.setattr(system.Redis, "from_url", lambda _url: object())
    monkeypatch.setattr(system.Worker, "all", lambda **_kwargs: workers)
    monkeypatch.setattr(system.socket, "gethostname", lambda: "local")
    monkeypatch.setattr(system, "_local_worker_process_alive", lambda pid: pid == 456)

    assert system.worker_detected(SimpleNamespace(redis_url="redis://unused")) is True

    monkeypatch.setattr(system.Worker, "all", lambda **_kwargs: workers[:1])
    assert system.worker_detected(SimpleNamespace(redis_url="redis://unused")) is False


def test_worker_detection_accepts_recent_remote_heartbeat(monkeypatch):
    worker = SimpleNamespace(
        last_heartbeat=datetime.now(timezone.utc) - timedelta(seconds=15),
        hostname="remote-worker",
        pid=789,
    )
    monkeypatch.setattr(system.Redis, "from_url", lambda _url: object())
    monkeypatch.setattr(system.Worker, "all", lambda **_kwargs: [worker])
    monkeypatch.setattr(system.socket, "gethostname", lambda: "local")

    assert system.worker_detected(SimpleNamespace(redis_url="redis://unused")) is True


def test_local_recent_heartbeat_is_not_enough_without_a_live_process(monkeypatch):
    worker = SimpleNamespace(
        last_heartbeat=datetime.now(timezone.utc),
        hostname="local",
        pid=789,
    )
    monkeypatch.setattr(system.Redis, "from_url", lambda _url: object())
    monkeypatch.setattr(system.Worker, "all", lambda **_kwargs: [worker])
    monkeypatch.setattr(system.socket, "gethostname", lambda: "local")
    monkeypatch.setattr(system, "_local_worker_process_alive", lambda _pid: False)

    assert system.worker_detected(SimpleNamespace(redis_url="redis://unused")) is False
