import hashlib
import unicodedata

from app.services.ingestion.errors import IngestionError


def normalize_text_bytes(text: str) -> bytes:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    normalized = unicodedata.normalize("NFC", normalized)
    return normalized.encode("utf-8")


def text_content_hash(text: str) -> str:
    return hashlib.sha256(normalize_text_bytes(text)).hexdigest()


def ensure_text_acceptable(text: str, max_bytes: int) -> str:
    if text.strip() == "":
        raise IngestionError(400, "EMPTY_TEXT", "文本不能为空。")
    encoded = normalize_text_bytes(text)
    if len(encoded) > max_bytes:
        raise IngestionError(413, "TEXT_TOO_LARGE", f"文本超过大小限制（{max_bytes} 字节）。")
    return text


def text_display_name(text: str) -> str:
    line = text.strip().splitlines()[0].strip()
    if not line:
        return "未命名文本"
    if len(line) > 80:
        return f"{line[:80]}…"
    return line
