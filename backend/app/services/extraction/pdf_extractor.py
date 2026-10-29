from pathlib import Path

from app.services.extraction.enums import ChunkType, ExtractorType
from app.services.extraction.types import ExtractedBlock, ExtractionPayload

PDF_TEXT_VERSION = "pdf-pymupdf-v1"
PDF_OCR_VERSION = "pdf-ocr-rapidocr-v1"


def extract_pdf(data: bytes, max_pages: int, ocr_image, derived_dir: Path | None) -> ExtractionPayload:
    import fitz

    document = fitz.open(stream=data, filetype="pdf")
    try:
        total_pages = document.page_count
        limited = total_pages > max_pages
        page_count = min(total_pages, max_pages)
        blocks: list[ExtractedBlock] = []
        page_methods: list[dict] = []
        empty_pages = 0
        ocr_pages = 0
        for index in range(page_count):
            page = document.load_page(index)
            text = page.get_text("text").strip()
            page_number = index + 1
            if len(text) >= 20:
                blocks.append(
                    ExtractedBlock(
                        ChunkType.PARAGRAPH.value,
                        text,
                        [f"Page {page_number}"],
                        {"page_number": page_number, "method": "text"},
                    )
                )
                page_methods.append({"page_number": page_number, "method": "text"})
                continue
            empty_pages += 1
            ocr_text = _ocr_page(document, page, page_number, ocr_image, derived_dir)
            if ocr_text:
                ocr_pages += 1
                blocks.append(
                    ExtractedBlock(
                        ChunkType.IMAGE_TEXT.value,
                        ocr_text,
                        [f"Page {page_number}"],
                        {"page_number": page_number, "method": "ocr"},
                    )
                )
                page_methods.append({"page_number": page_number, "method": "ocr"})
            else:
                page_methods.append({"page_number": page_number, "method": "empty"})
    finally:
        document.close()

    used_ocr = ocr_pages > 0
    status = "SUCCEEDED"
    error_code = None
    error_message = None
    if limited or (empty_pages and not blocks) or (empty_pages and used_ocr and empty_pages > ocr_pages):
        status = "PARTIAL"
        error_code = "PDF_PAGE_LIMIT" if limited else "PDF_PARTIAL_TEXT"
        error_message = (
            f"PDF 共 {total_pages} 页，已处理 {page_count} 页。"
            if limited
            else "部分页面没有可用文本。"
        )
    if not blocks:
        status = "FAILED"
        error_code = error_code or "PDF_NO_TEXT"
        error_message = error_message or "没有提取到可用文本。"
    return ExtractionPayload(
        extractor_type=ExtractorType.PDF_OCR.value if used_ocr else ExtractorType.PDF_TEXT.value,
        extractor_version=PDF_OCR_VERSION if used_ocr else PDF_TEXT_VERSION,
        title=None,
        blocks=blocks,
        metadata={
            "total_pages": total_pages,
            "processed_pages": page_count,
            "page_methods": page_methods,
            "truncated": limited,
        },
        status=status,
        error_code=error_code,
        error_message=error_message,
    )


def _ocr_page(document, page, page_number: int, ocr_image, derived_dir: Path | None) -> str:
    if ocr_image is None:
        return ""
    pixmap = page.get_pixmap(matrix=__import__("fitz").Matrix(2, 2), alpha=False)
    image_bytes = pixmap.tobytes("png")
    if derived_dir is not None:
        derived_dir.mkdir(parents=True, exist_ok=True)
        target = derived_dir / f"page-{page_number}.png"
        target.write_bytes(image_bytes)
    return ocr_image(image_bytes).strip()
