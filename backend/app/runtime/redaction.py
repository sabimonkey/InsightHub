import re

SECRET_PATTERNS = [
    re.compile(r"(?i)(api[_-]?key|secret|password|token)\s*[:=]\s*\S+"),
    re.compile(r"sk-[a-zA-Z0-9]{8,}"),
    re.compile(r"postgresql\+psycopg://[^@\s]+:[^@\s]+@"),
]


def redact_text(text: str) -> str:
    cleaned = text
    for pattern in SECRET_PATTERNS:
        cleaned = pattern.sub("[REDACTED]", cleaned)
    return cleaned


def env_config_state(name: str, value: str | None) -> str:
    if value is None or str(value).strip() == "":
        return "MISSING"
    return "CONFIGURED"
