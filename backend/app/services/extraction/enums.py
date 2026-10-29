from enum import StrEnum


class ExtractionStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"


class ExtractionTrigger(StrEnum):
    AUTO = "AUTO"
    MANUAL = "MANUAL"
    REEXTRACT = "REEXTRACT"


class ChunkType(StrEnum):
    PARAGRAPH = "PARAGRAPH"
    SECTION = "SECTION"
    TABLE = "TABLE"
    CODE = "CODE"
    IMAGE_TEXT = "IMAGE_TEXT"


class ExtractorType(StrEnum):
    TEXT = "TEXT"
    MARKDOWN = "MARKDOWN"
    DOCX = "DOCX"
    PDF_TEXT = "PDF_TEXT"
    PDF_OCR = "PDF_OCR"
    IMAGE_OCR = "IMAGE_OCR"
    WEB = "WEB"
