"""Validate decoded cover image bytes."""

from __future__ import annotations

from io import BytesIO

from PIL import Image


class MinimaxImageValidationError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def validate_cover_image_bytes(data: bytes, *, max_bytes: int) -> None:
    if not data:
        raise MinimaxImageValidationError("EMPTY_IMAGE", "图片数据为空。")
    if len(data) > max_bytes:
        raise MinimaxImageValidationError("COVER_TOO_LARGE", "封面图片超过大小限制。")
    try:
        with Image.open(BytesIO(data)) as img:
            img.verify()
        with Image.open(BytesIO(data)) as img:
            width, height = img.size
    except Exception as exc:
        raise MinimaxImageValidationError("INVALID_IMAGE", "图片格式无效。") from exc
    if width < 32 or height < 32:
        raise MinimaxImageValidationError("IMAGE_TOO_SMALL", "图片尺寸过小。")
