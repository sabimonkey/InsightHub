from enum import StrEnum


class SourceType(StrEnum):
    URL = "URL"
    TEXT = "TEXT"
    IMAGE = "IMAGE"
    PDF = "PDF"
    DOCX = "DOCX"
    MARKDOWN = "MARKDOWN"
    FILE = "FILE"


class IngestionType(StrEnum):
    URL = "URL"
    TEXT = "TEXT"
    FILE = "FILE"
    TEXT_SUPPLEMENT = "TEXT_SUPPLEMENT"


class IngestionStatus(StrEnum):
    RECEIVED = "RECEIVED"
    STORED = "STORED"
    FAILED = "FAILED"


class DuplicateReason(StrEnum):
    CANONICAL_URL_DUPLICATE = "CANONICAL_URL_DUPLICATE"
    EXACT_TEXT_DUPLICATE = "EXACT_TEXT_DUPLICATE"
    EXACT_FILE_DUPLICATE = "EXACT_FILE_DUPLICATE"


class IngestionOrigin(StrEnum):
    USER_COLLECTION = "USER_COLLECTION"
    SYSTEM_DISCOVERY = "SYSTEM_DISCOVERY"
    USER_PROVIDED = "USER_PROVIDED"


class DiscoveryStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"


class CandidateStatus(StrEnum):
    PROPOSED = "PROPOSED"
    CONFIRMED = "CONFIRMED"
    REJECTED = "REJECTED"


class RelationType(StrEnum):
    RESOLVES_TO = "RESOLVES_TO"
    DERIVED_FROM = "DERIVED_FROM"
    REFERENCES = "REFERENCES"
    MIRROR_OF = "MIRROR_OF"
    REPOST_OF = "REPOST_OF"


class ConfirmedBy(StrEnum):
    USER = "USER"
    SYSTEM = "SYSTEM"
