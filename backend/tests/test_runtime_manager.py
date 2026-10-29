from app.runtime.classification import DependencyTier, HealthState, overall_state
from app.runtime.manifest import (
    is_stale_manifest_entry,
    new_managed_process,
    verify_process_identity,
)
from app.runtime.redaction import env_config_state, redact_text


def test_overall_failed_when_core_missing():
    states = {
        "postgresql": HealthState.READY.value,
        "redis": HealthState.READY.value,
        "backend": HealthState.FAILED.value,
        "rq_worker": HealthState.READY.value,
        "frontend": HealthState.READY.value,
    }
    assert overall_state(states) == HealthState.FAILED.value


def test_overall_degraded_when_bge_missing():
    states = {
        "postgresql": HealthState.READY.value,
        "redis": HealthState.READY.value,
        "backend": HealthState.READY.value,
        "rq_worker": HealthState.READY.value,
        "frontend": HealthState.READY.value,
        "bge_m3": HealthState.STOPPED.value,
        "chromium": HealthState.READY.value,
    }
    assert overall_state(states) == HealthState.DEGRADED.value


def test_manifest_identity_rejects_pid_reuse():
    proc = new_managed_process("api", 42, "app.main:app", r"C:\test\InsightHub", 8090, "2020-01-01T00:00:00Z")
    ok = verify_process_identity(
        pid=42,
        command_identity=proc.command_identity,
        project_root=proc.project_root,
        creation_time=proc.creation_time,
        process_creation_iso="2026-01-01T00:00:00Z",
        command_line=r"C:\Python311\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8090",
    )
    assert ok is False
    assert is_stale_manifest_entry(proc, alive=True, identity_ok=False) is True


def test_manifest_identity_accepts_matching_command():
    proc = new_managed_process("api", 42, "app.main:app", r"C:\test\InsightHub", 8090, "2020-01-01T00:00:00Z")
    cmd = r"C:\Python311\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8090"
    ok = verify_process_identity(
        pid=42,
        command_identity=proc.command_identity,
        project_root=proc.project_root,
        creation_time=proc.creation_time,
        process_creation_iso=proc.creation_time,
        command_line=cmd,
    )
    assert ok is True


def test_secret_redaction():
    raw = "DEEPSEEK_API_KEY=TEST_ONLY_NOT_A_CREDENTIAL"
    assert "[REDACTED]" in redact_text(raw)
    assert "test-credential" not in redact_text(raw)


def test_env_config_state_never_exposes_value():
    assert env_config_state("DEEPSEEK_API_KEY", "secret-value") == "CONFIGURED"
    assert env_config_state("DEEPSEEK_API_KEY", "") == "MISSING"


def test_lm_studio_optional_tier():
    assert DependencyTier.OPTIONAL == DependencyTier.OPTIONAL
