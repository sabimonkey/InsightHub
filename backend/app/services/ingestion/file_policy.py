import mimetypes

from app.models.enums import SourceType
from app.services.ingestion.errors import IngestionError

FORBIDDEN_EXTENSIONS = frozenset(
    {".exe", ".bat", ".cmd", ".ps1", ".js", ".vbs", ".scr", ".com", ".msi"}
)
IMAGE_EXTENSIONS = frozenset(
    {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tif", ".tiff", ".svg", ".heic", ".heif"}
)


def validate_filename(filename: str | None) -> str:
    if filename is None or filename.strip() == "":
        raise IngestionError(400, "UNSAFE_FILENAME", "文件名不能为空。")
    name = filename.strip()
    if "\x00" in name or any(ord(char) < 32 for char in name):
        raise IngestionError(400, "UNSAFE_FILENAME", "文件名包含非法字符。")
    if name.startswith(("/", "\\")) or (len(name) >= 2 and name[1] == ":"):
        raise IngestionError(400, "UNSAFE_FILENAME", "文件名不能是绝对路径。")
    if ".." in name or "/" in name or "\\" in name:
        raise IngestionError(400, "UNSAFE_FILENAME", "文件名不能包含路径。")
    suffixes = [part.lower() for part in _suffixes(name)]
    if any(suffix in FORBIDDEN_EXTENSIONS for suffix in suffixes):
        raise IngestionError(400, "FORBIDDEN_EXTENSION", "该文件类型不允许进入收集流程。")
    return name


def classify_source_type(filename: str) -> SourceType:
    suffix = _final_suffix(filename)
    if suffix == ".pdf":
        return SourceType.PDF
    if suffix == ".docx":
        return SourceType.DOCX
    if suffix in {".md", ".markdown"}:
        return SourceType.MARKDOWN
    if suffix in IMAGE_EXTENSIONS:
        return SourceType.IMAGE
    return SourceType.FILE


def guess_mime_type(filename: str, content_type: str | None) -> str:
    guessed, _encoding = mimetypes.guess_type(filename)
    if guessed:
        return guessed
    if content_type and "/" in content_type and content_type != "application/octet-stream":
        return content_type.split(";", 1)[0].strip() or "application/octet-stream"
    return "application/octet-stream"


def _suffixes(filename: str) -> list[str]:
    parts = filename.lower().split(".")
    if len(parts) <= 1:
        return []
    return [f".{part}" for part in parts[1:] if part]


def _final_suffix(filename: str) -> str:
    suffixes = _suffixes(filename)
    if not suffixes:
        return ""
    return suffixes[-1]
