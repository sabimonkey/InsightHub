"""Persist generated cover images under data/covers."""

from __future__ import annotations

import hashlib
import imghdr
import uuid
from pathlib import Path

from app.core.config import PROJECT_ROOT, Settings, get_settings


class CoverStorageError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def covers_root(settings: Settings | None = None) -> Path:
    settings = settings or get_settings()
    return (PROJECT_ROOT / settings.cover_storage_subdir).resolve()


def _safe_source_dir(source_id: uuid.UUID, settings: Settings | None = None) -> Path:
    root = covers_root(settings)
    path = (root / str(source_id)).resolve()
    if not str(path).startswith(str(root)):
        raise CoverStorageError("PATH_TRAVERSAL", "封面路径无效。")
    path.mkdir(parents=True, exist_ok=True)
    return path


def save_cover_bytes(source_id: uuid.UUID, data: bytes, settings: Settings | None = None) -> tuple[str, str, str]:
    settings = settings or get_settings()
    if len(data) > settings.cover_max_bytes:
        raise CoverStorageError("COVER_TOO_LARGE", "封面图片超过大小限制。")
    kind = imghdr.what(None, h=data)
    if kind not in {"png", "jpeg", "gif", "webp"}:
        raise CoverStorageError("COVER_CONTENT_TYPE", "封面不是有效图片格式。")
    ext = "jpg" if kind == "jpeg" else kind
    content_hash = hashlib.sha256(data).hexdigest()
    asset_id = uuid.uuid4()
    relative = f"{settings.cover_storage_subdir}/{source_id}/{asset_id}.{ext}".replace("\\", "/")
    target = (PROJECT_ROOT / relative).resolve()
    root = covers_root(settings)
    if not str(target).startswith(str(root)):
        raise CoverStorageError("PATH_TRAVERSAL", "封面路径无效。")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return relative, content_hash, ext


def read_cover_file(relative_path: str, settings: Settings | None = None) -> tuple[bytes, str]:
    settings = settings or get_settings()
    root = covers_root(settings)
    target = (PROJECT_ROOT / relative_path).resolve()
    if not str(target).startswith(str(root)) or not target.is_file():
        raise CoverStorageError("NOT_FOUND", "找不到封面文件。")
    data = target.read_bytes()
    kind = imghdr.what(None, h=data) or "jpeg"
    media = "image/jpeg" if kind == "jpeg" else f"image/{kind}"
    return data, media
