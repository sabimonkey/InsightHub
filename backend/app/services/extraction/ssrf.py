import ipaddress
import socket
from urllib.parse import urlsplit

from app.services.ingestion.errors import IngestionError


class SsrfError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.code = "SSRF_BLOCKED"
        self.message = message


def assert_public_http_url(url: str, resolver=None) -> str:
    parts = urlsplit(url.strip())
    if parts.scheme.lower() not in {"http", "https"}:
        raise SsrfError("只允许访问 http 或 https URL。")
    host = parts.hostname
    if not host:
        raise SsrfError("URL 缺少主机名。")
    lowered = host.lower().rstrip(".")
    if lowered in {"localhost", "localhost.localdomain"} or lowered.endswith(".localhost"):
        raise SsrfError("拒绝访问本地地址。")
    try:
        literal = ipaddress.ip_address(lowered)
    except ValueError:
        literal = None
    if literal is not None:
        _reject_ip(literal)
        return url
    lookup = resolver or _default_resolve
    try:
        addresses = lookup(lowered)
    except socket.gaierror as exc:
        raise SsrfError("无法解析主机名。") from exc
    if not addresses:
        raise SsrfError("主机名没有可用地址。")
    for address in addresses:
        _reject_ip(ipaddress.ip_address(address))
    return url


def _default_resolve(host: str) -> list[str]:
    infos = socket.getaddrinfo(host, None)
    return [item[4][0] for item in infos]


def _reject_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> None:
    if (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
        or not ip.is_global
    ):
        raise SsrfError("拒绝访问非公网地址。")


def ensure_not_ingestion_error(exc: Exception) -> None:
    if isinstance(exc, IngestionError):
        raise exc
