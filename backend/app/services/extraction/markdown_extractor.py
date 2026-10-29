from app.services.extraction.enums import ChunkType, ExtractorType
from app.services.extraction.types import ExtractedBlock, ExtractionPayload

MARKDOWN_VERSION = "markdown-v1"


def extract_markdown(raw_text: str) -> ExtractionPayload:
    text = raw_text.replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n")
    heading_path: list[str] = []
    blocks: list[ExtractedBlock] = []
    title: str | None = None
    index = 0
    while index < len(lines):
        line = lines[index]
        if line.startswith("```"):
            language = line[3:].strip()
            index += 1
            body: list[str] = []
            while index < len(lines) and not lines[index].startswith("```"):
                body.append(lines[index])
                index += 1
            if index < len(lines):
                index += 1
            blocks.append(
                ExtractedBlock(
                    ChunkType.CODE.value,
                    "\n".join(body).strip("\n"),
                    list(heading_path),
                    {"language": language} if language else {},
                )
            )
            continue
        if _is_table_start(lines, index):
            table_lines = []
            while index < len(lines) and "|" in lines[index]:
                table_lines.append(lines[index])
                index += 1
            blocks.append(ExtractedBlock(ChunkType.TABLE.value, _table_text(table_lines), list(heading_path), {}))
            continue
        heading = _heading(line)
        if heading is not None:
            level, label = heading
            if title is None:
                title = label
            heading_path = heading_path[: level - 1]
            heading_path.append(label)
            blocks.append(ExtractedBlock(ChunkType.SECTION.value, label, list(heading_path), {"level": level}))
            index += 1
            continue
        if line.strip().startswith(("- ", "* ")) or _ordered_item(line):
            items: list[str] = []
            while index < len(lines) and (lines[index].strip().startswith(("- ", "* ")) or _ordered_item(lines[index])):
                item = lines[index].strip()
                item = item[2:].strip() if item.startswith(("- ", "* ")) else item.split(".", 1)[1].strip()
                items.append(item)
                index += 1
            blocks.append(ExtractedBlock(ChunkType.PARAGRAPH.value, "\n".join(items), list(heading_path), {"list": True}))
            continue
        if line.strip() == "":
            index += 1
            continue
        paragraph: list[str] = []
        while index < len(lines) and lines[index].strip() and not _starts_structure(lines, index):
            paragraph.append(lines[index].strip())
            index += 1
        if paragraph:
            blocks.append(ExtractedBlock(ChunkType.PARAGRAPH.value, " ".join(paragraph), list(heading_path), {}))
    plain = "\n\n".join(block.content for block in blocks if block.content)
    return ExtractionPayload(
        extractor_type=ExtractorType.MARKDOWN.value,
        extractor_version=MARKDOWN_VERSION,
        title=title,
        blocks=blocks,
        metadata={"plain_text_length": len(plain)},
    )


def _heading(line: str) -> tuple[int, str] | None:
    stripped = line.strip()
    if not stripped.startswith("#"):
        return None
    marks = 0
    for char in stripped:
        if char == "#":
            marks += 1
        else:
            break
    if marks < 1 or marks > 6 or len(stripped) <= marks or stripped[marks] != " ":
        return None
    label = stripped[marks + 1 :].strip()
    if not label:
        return None
    return marks, label


def _ordered_item(line: str) -> bool:
    stripped = line.strip()
    digits, _, rest = stripped.partition(".")
    return bool(digits) and digits.isdigit() and rest.startswith(" ")


def _is_table_start(lines: list[str], index: int) -> bool:
    if index + 1 >= len(lines):
        return False
    return "|" in lines[index] and set(lines[index + 1].replace("|", "").replace(":", "").strip()) <= {"-"} and "-" in lines[index + 1]


def _table_text(lines: list[str]) -> str:
    rows: list[str] = []
    for line in lines:
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if cells and set("".join(cells)) <= {"-", ":"}:
            continue
        rows.append(" | ".join(cells))
    return "\n".join(rows)


def _starts_structure(lines: list[str], index: int) -> bool:
    line = lines[index]
    return (
        line.startswith("```")
        or _heading(line) is not None
        or _is_table_start(lines, index)
        or line.strip().startswith(("- ", "* "))
        or _ordered_item(line)
    )
