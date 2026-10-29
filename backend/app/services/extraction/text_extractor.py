from app.services.extraction.enums import ChunkType, ExtractorType
from app.services.extraction.types import ExtractedBlock, ExtractionPayload

TEXT_VERSION = "text-v1"


def extract_text(raw_text: str) -> ExtractionPayload:
    normalized = raw_text.replace("\r\n", "\n").replace("\r", "\n")
    title = None
    stripped = normalized.strip()
    if stripped:
        title = stripped.splitlines()[0].strip()[:120] or None
    blocks = []
    if stripped:
        blocks.append(ExtractedBlock(ChunkType.PARAGRAPH.value, stripped, [], {}))
    return ExtractionPayload(
        extractor_type=ExtractorType.TEXT.value,
        extractor_version=TEXT_VERSION,
        title=title,
        blocks=blocks,
        metadata={"newline_normalized": True},
    )
