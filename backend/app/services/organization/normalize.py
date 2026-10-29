import re
import unicodedata

ENTITY_TYPES = {"PERSON", "COMPANY", "ORGANIZATION", "PRODUCT", "PROJECT", "MODEL", "TECHNOLOGY", "PAPER", "OTHER"}
DEFAULT_CATEGORIES = (
    ("project_discovery", "发现项目", 1),
    ("business", "商业", 2),
    ("knowledge", "知识", 3),
    ("other", "其他", 4),
)
CATEGORY_NAMES = {
    "project_discovery": "project_discovery",
    "发现项目": "project_discovery",
    "project": "project_discovery",
    "business": "business",
    "商业": "business",
    "knowledge": "knowledge",
    "知识": "knowledge",
    "other": "other",
    "其他": "other",
}
CLAIM_ROLES = {
    "FACT": "KEY_FACT",
    "SOURCE_CLAIM": "SOURCE_VIEW",
    "INFERENCE": "INFERENCE",
    "HYPOTHESIS": "HYPOTHESIS",
    "UNKNOWN": "UNKNOWN",
    "QUESTION": "QUESTION",
}


def normalize_taxonomy_name(value: str) -> str:
    text = unicodedata.normalize("NFKC", value or "")
    text = re.sub(r"\s+", " ", text).strip()
    return text.casefold()


def acceptable_taxonomy_name(value: str, *, limit: int = 80) -> bool:
    normalized = normalize_taxonomy_name(value)
    if not normalized or len(normalized) > limit:
        return False
    return any(character.isalnum() for character in normalized)


def category_slug(name: str) -> str | None:
    key = normalize_taxonomy_name(name)
    for label, slug in CATEGORY_NAMES.items():
        if normalize_taxonomy_name(label) == key:
            return slug
    return None
