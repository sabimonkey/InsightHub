import hashlib
import os
import uuid
from pathlib import Path
from typing import BinaryIO

from app.services.ingestion.errors import IngestionError

CHUNK_SIZE = 1024 * 1024


def relative_raw_path(sha256: str) -> str:
    return f"{sha256[:2]}/{sha256[2:4]}/{sha256}.bin"


def stream_to_temp(fileobj: BinaryIO, temp_path: Path, max_bytes: int) -> tuple[str, int]:
    hasher = hashlib.sha256()
    size = 0
    temp_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with temp_path.open("wb") as handle:
            while True:
                chunk = fileobj.read(CHUNK_SIZE)
                if not chunk:
                    break
                size += len(chunk)
                if size > max_bytes:
                    raise IngestionError(
                        413,
                        "FILE_TOO_LARGE",
                        f"文件超过大小限制（{max_bytes} 字节）。",
                    )
                hasher.update(chunk)
                handle.write(chunk)
    except IngestionError:
        temp_path.unlink(missing_ok=True)
        raise
    except OSError as exc:
        temp_path.unlink(missing_ok=True)
        raise IngestionError(500, "STORAGE_FAILED", "文件保存失败，未写入数据库。") from exc
    return hasher.hexdigest(), size


def place_content_addressed(temp_path: Path, destination: Path) -> bool:
    """Copy temp into destination without replacing an existing file.

    Returns True when this call created destination.
    """
    destination.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    try:
        fd = os.open(destination, flags)
    except FileExistsError:
        temp_path.unlink(missing_ok=True)
        return False
    try:
        with os.fdopen(fd, "wb") as handle, temp_path.open("rb") as source:
            while True:
                chunk = source.read(CHUNK_SIZE)
                if not chunk:
                    break
                handle.write(chunk)
    except OSError as exc:
        destination.unlink(missing_ok=True)
        raise IngestionError(500, "STORAGE_FAILED", "文件保存失败，未写入数据库。") from exc
    finally:
        temp_path.unlink(missing_ok=True)
    return True


def new_temp_path(raw_root: Path) -> Path:
    return raw_root / ".tmp" / f"{uuid.uuid4().hex}.part"


def file_sha256(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(CHUNK_SIZE)
            if not chunk:
                break
            hasher.update(chunk)
    return hasher.hexdigest()
