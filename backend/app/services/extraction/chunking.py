from app.services.extraction.enums import ChunkType
from app.services.extraction.types import ExtractedBlock


def chunk_blocks(blocks: list[ExtractedBlock], max_chars: int, overlap_chars: int) -> list[ExtractedBlock]:
    if max_chars < 1:
        max_chars = 1
    overlap = min(max(overlap_chars, 0), max_chars // 4)
    chunks: list[ExtractedBlock] = []
    for block in blocks:
        text = block.content.strip()
        if not text:
            continue
        if len(text) <= max_chars:
            chunks.append(
                ExtractedBlock(block.chunk_type, text, list(block.heading_path), dict(block.metadata))
            )
            continue
        start = 0
        part = 0
        while start < len(text):
            end = min(start + max_chars, len(text))
            if end < len(text):
                split_at = text.rfind("\n", start, end)
                if split_at > start + max_chars // 2:
                    end = split_at
            piece = text[start:end].strip()
            if piece:
                metadata = dict(block.metadata)
                metadata["split_part"] = part
                chunks.append(ExtractedBlock(block.chunk_type or ChunkType.PARAGRAPH.value, piece, list(block.heading_path), metadata))
                part += 1
            if end >= len(text):
                break
            next_start = end - overlap
            start = next_start if next_start > start else end
    return chunks
