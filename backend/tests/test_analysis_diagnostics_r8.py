from app.services.analysis.service import _safe_analysis_exception


def test_unexpected_analysis_traceback_redacts_provider_key_and_keeps_type():
    secret = "TEST_ONLY_SECRET_SENTINEL"

    class Provider:
        api_key = secret

    try:
        raise TypeError(f"unexpected value {secret}")
    except TypeError as exc:
        diagnostic = _safe_analysis_exception(exc, Provider())

    assert "TypeError" in diagnostic
    assert "unexpected value" in diagnostic
    assert secret not in diagnostic
    assert "[REDACTED]" in diagnostic
