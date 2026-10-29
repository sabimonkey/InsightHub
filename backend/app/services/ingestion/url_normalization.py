from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from app.services.ingestion.errors import IngestionError

TRACKING_PARAMS = frozenset(
    {
        "utm_source",
        "utm_medium",
        "utm_campaign",
        "utm_term",
        "utm_content",
        "fbclid",
        "gclid",
    }
)
X_HOSTS = frozenset(
    {
        "x.com",
        "www.x.com",
        "mobile.x.com",
        "twitter.com",
        "www.twitter.com",
        "mobile.twitter.com",
    }
)


def canonicalize_url(raw: str) -> tuple[str, str]:
    original = raw.strip()
    if not original:
        raise IngestionError(400, "INVALID_URL", "URL 不能为空。")
    if len(original) > 8192:
        raise IngestionError(400, "INVALID_URL", "URL 过长。")
    try:
        parts = urlsplit(original)
    except ValueError as exc:
        raise IngestionError(400, "INVALID_URL", "URL 无法解析。") from exc

    scheme = parts.scheme.lower()
    if scheme not in {"http", "https"}:
        raise IngestionError(400, "INVALID_URL", "只接受 http 或 https URL。")
    host = parts.hostname
    if not host:
        raise IngestionError(400, "INVALID_URL", "URL 必须包含主机名。")
    host = host.lower()
    if host in X_HOSTS:
        host = "x.com"
    try:
        port = parts.port
    except ValueError as exc:
        raise IngestionError(400, "INVALID_URL", "URL 端口无效。") from exc

    if port is None or (scheme == "http" and port == 80) or (scheme == "https" and port == 443):
        netloc = host
    else:
        netloc = f"{host}:{port}"
    if parts.username or parts.password:
        auth = parts.username or ""
        if parts.password:
            auth = f"{auth}:{parts.password}"
        netloc = f"{auth}@{netloc}"

    path = parts.path or "/"
    if parts.hostname and parts.hostname.lower() in X_HOSTS:
        segments = path.split("/")
        if len(segments) >= 4 and segments[2].lower() == "status" and segments[3].isdigit():
            segments[1] = segments[1].lower()
            segments[2] = "status"
            path = "/".join(segments).rstrip("/")
    filtered: list[tuple[str, str]] = []
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        lowered = key.lower()
        if lowered in TRACKING_PARAMS:
            continue
        if lowered in {"s", "t"} and host in X_HOSTS:
            continue
        filtered.append((key, value))
    filtered.sort()
    query = urlencode(filtered, doseq=True)
    canonical = urlunsplit((scheme, netloc, path, query, ""))
    return original, canonical
