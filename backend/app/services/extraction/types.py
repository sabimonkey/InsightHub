from dataclasses import dataclass, field


@dataclass
class ExtractedBlock:
    chunk_type: str
    content: str
    heading_path: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)


@dataclass
class ExtractionPayload:
    extractor_type: str
    extractor_version: str
    title: str | None
    blocks: list[ExtractedBlock]
    metadata: dict = field(default_factory=dict)
    status: str = "SUCCEEDED"
    error_code: str | None = None
    error_message: str | None = None
