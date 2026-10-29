from app.services.extraction.enums import ChunkType, ExtractorType
from app.services.extraction.types import ExtractedBlock, ExtractionPayload

IMAGE_VERSION = "image-rapidocr-v1"
SUPPORTED = {".png", ".jpg", ".jpeg", ".webp"}


def extract_image(data: bytes, suffix: str, ocr_image) -> ExtractionPayload:
    normalized = suffix.lower()
    if normalized not in SUPPORTED:
        return ExtractionPayload(
            extractor_type=ExtractorType.IMAGE_OCR.value,
            extractor_version=IMAGE_VERSION,
            title=None,
            blocks=[],
            status="FAILED",
            error_code="UNSUPPORTED_IMAGE",
            error_message="当前只对 PNG、JPG、JPEG、WEBP 做文字识别。",
        )
    text = ocr_image(data).strip()
    blocks = []
    if text:
        blocks.append(ExtractedBlock(ChunkType.IMAGE_TEXT.value, text, [], {"method": "ocr"}))
    status = "SUCCEEDED" if text else "FAILED"
    return ExtractionPayload(
        extractor_type=ExtractorType.IMAGE_OCR.value,
        extractor_version=IMAGE_VERSION,
        title=None,
        blocks=blocks,
        metadata={"ocr": True},
        status=status,
        error_code=None if text else "OCR_EMPTY",
        error_message=None if text else "没有识别到文字。",
    )


def recognize_image_bytes(data: bytes) -> str:
    from io import BytesIO

    from PIL import Image
    from rapidocr_onnxruntime import RapidOCR

    image = Image.open(BytesIO(data)).convert("RGB")
    engine = _engine()
    result, _elapsed = engine(image)
    if not result:
        return ""
    return "\n".join(item[1] for item in result if len(item) > 1 and item[1])


_ENGINE = None


def _engine():
    global _ENGINE
    if _ENGINE is None:
        from rapidocr_onnxruntime import RapidOCR

        _ENGINE = RapidOCR()
    return _ENGINE
