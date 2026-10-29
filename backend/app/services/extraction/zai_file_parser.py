"""Official Zhipu synchronous Prime parser adapter (opt-in, paid cloud extraction)."""

from __future__ import annotations

import json
from pathlib import Path

import httpx

from app.services.extraction.enums import ChunkType, ExtractorType
from app.services.extraction.types import ExtractedBlock, ExtractionPayload

ZAI_FILE_PARSER_URL = "https://open.bigmodel.cn/api/paas/v4/files/parser/sync"
SUPPORTED_FILE_TYPES = {
    ".pdf": "PDF",
    ".docx": "DOCX",
    ".doc": "DOC",
    ".png": "PNG",
    ".jpg": "JPG",
    ".jpeg": "JPEG",
    ".bmp": "BMP",
}


class ZaiFileParser:
    def __init__(self, *, api_key: str, timeout_seconds: float = 180, client: httpx.Client | None = None) -> None:
        if not api_key:
            raise ValueError("ZAI_API_KEY_REQUIRED")
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds
        self.client = client

    def parse(self, content: bytes, filename: str) -> ExtractionPayload:
        extension = Path(filename).suffix.lower()
        file_type = SUPPORTED_FILE_TYPES.get(extension)
        if file_type is None:
            raise ValueError("ZAI_FILE_TYPE_UNSUPPORTED")
        owns_client = self.client is None
        client = self.client or httpx.Client(timeout=self.timeout_seconds)
        try:
            response = client.post(
                ZAI_FILE_PARSER_URL,
                headers={"Authorization": f"Bearer {self.api_key}"},
                data={"tool_type": "prime-sync", "file_type": file_type},
                files={"file": (Path(filename).name, content, "application/octet-stream")},
            )
        except httpx.TimeoutException as exc:
            raise RuntimeError("ZAI_FILE_PARSER_TIMEOUT") from exc
        except httpx.HTTPError as exc:
            raise RuntimeError("ZAI_FILE_PARSER_UNAVAILABLE") from exc
        finally:
            if owns_client:
                client.close()
        if response.status_code == 401:
            raise RuntimeError("ZAI_CREDENTIAL_REJECTED")
        if response.status_code == 403:
            raise RuntimeError("ZAI_FILE_PARSER_PERMISSION_DENIED")
        if response.status_code == 429:
            raise RuntimeError("ZAI_FILE_PARSER_RATE_LIMITED")
        if response.status_code >= 400:
            raise RuntimeError(f"ZAI_FILE_PARSER_HTTP_{response.status_code}")
        try:
            body = response.json()
        except (json.JSONDecodeError, ValueError) as exc:
            raise RuntimeError("ZAI_FILE_PARSER_INVALID_RESPONSE") from exc
        if str(body.get("status", "")).lower() != "succeeded":
            raise RuntimeError("ZAI_FILE_PARSER_NOT_SUCCEEDED")
        text = body.get("content")
        if not isinstance(text, str) or not text.strip():
            raise RuntimeError("ZAI_FILE_PARSER_EMPTY_CONTENT")
        return ExtractionPayload(
            extractor_type=ExtractorType.PDF_TEXT.value if file_type == "PDF" else ExtractorType.DOCX.value if file_type in {"DOC", "DOCX"} else ExtractorType.IMAGE_OCR.value,
            extractor_version="zai-prime-sync-v1",
            title=Path(filename).stem,
            blocks=[ExtractedBlock(ChunkType.PARAGRAPH.value, text.strip(), metadata={"source_kind": "official_file_parser"})],
            metadata={
                "provider": "ZAI",
                "model": "glm-file-parser-prime-sync",
                "task_id": body.get("task_id"),
                "input_file_type": file_type,
                "billing_basis": "per_page",
                "source_location_precision": "parser_text_only",
            },
        )
