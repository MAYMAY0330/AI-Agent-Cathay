from __future__ import annotations

from pathlib import Path
import re
from typing import Iterator

from ingestion.models import IngestionError, TextBlock


def extract_text(file_path: Path, file_type: str) -> list[TextBlock]:
    if file_type == "docx":
        return _extract_docx(file_path)
    if file_type == "pdf":
        return _extract_pdf(file_path)
    raise IngestionError("text_extraction", f"unsupported file type: {file_type}")


def _extract_docx(file_path: Path) -> list[TextBlock]:
    try:
        from docx import Document
        from docx.oxml.table import CT_Tbl
        from docx.oxml.text.paragraph import CT_P
        from docx.table import Table
        from docx.text.paragraph import Paragraph
    except ImportError as exc:
        raise IngestionError(
            "text_extraction",
            "python-docx is required for DOCX extraction. Install dependencies with: pip install -r requirements.txt",
        ) from exc

    def iter_block_items(document) -> Iterator[Paragraph | Table]:
        for child in document.element.body.iterchildren():
            if isinstance(child, CT_P):
                yield Paragraph(child, document)
            elif isinstance(child, CT_Tbl):
                yield Table(child, document)

    try:
        document = Document(str(file_path))
    except Exception as exc:
        raise IngestionError("text_extraction", f"unable to open DOCX: {exc}") from exc

    blocks: list[TextBlock] = []
    for block in iter_block_items(document):
        if isinstance(block, Paragraph):
            text = block.text.strip()
            if not text:
                continue
            style = block.style.name if block.style else "paragraph"
            blocks.append(
                TextBlock(
                    block_index=len(blocks) + 1,
                    text=text,
                    style=style.lower(),
                )
            )
            continue

        rows = []
        for row in block.rows:
            cell_text = [cell.text.strip() for cell in row.cells if cell.text.strip()]
            if cell_text:
                rows.append(" | ".join(cell_text))
        table_text = "\n".join(rows).strip()
        if table_text:
            blocks.append(
                TextBlock(
                    block_index=len(blocks) + 1,
                    text=table_text,
                    style="table",
                )
            )

    if not blocks:
        raise IngestionError("text_extraction", "DOCX contains no extractable text")
    return blocks


def _extract_pdf(file_path: Path) -> list[TextBlock]:
    try:
        import fitz
    except ImportError:
        return _extract_pdf_with_pypdf(file_path)

    try:
        document = fitz.open(str(file_path))
    except Exception as exc:
        raise IngestionError("text_extraction", f"unable to open PDF: {exc}") from exc

    blocks: list[TextBlock] = []
    try:
        for page_index in range(document.page_count):
            page = document.load_page(page_index)
            text = page.get_text("text").strip()
            if text:
                blocks.append(
                    TextBlock(
                        block_index=len(blocks) + 1,
                        text=text,
                        style="page",
                        page=page_index + 1,
                    )
                )
    finally:
        document.close()

    if not _has_meaningful_pdf_text(blocks):
        raise IngestionError(
            "text_extraction", "scanned PDF or no extractable text found"
        )
    return blocks


def _extract_pdf_with_pypdf(file_path: Path) -> list[TextBlock]:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise IngestionError(
            "text_extraction",
            "PyMuPDF or pypdf is required for PDF extraction. Install dependencies with: pip install -r requirements.txt",
        ) from exc

    try:
        reader = PdfReader(str(file_path))
    except Exception as exc:
        raise IngestionError("text_extraction", f"unable to open PDF: {exc}") from exc

    blocks: list[TextBlock] = []
    for page_index, page in enumerate(reader.pages):
        try:
            text = (page.extract_text() or "").strip()
        except Exception:
            continue
        if text:
            blocks.append(
                TextBlock(
                    block_index=len(blocks) + 1,
                    text=text,
                    style="page",
                    page=page_index + 1,
                )
            )

    if not _has_meaningful_pdf_text(blocks):
        raise IngestionError(
            "text_extraction", "scanned PDF or no extractable text found"
        )
    return blocks


def _has_meaningful_pdf_text(blocks: list[TextBlock]) -> bool:
    if not blocks:
        return False

    text = "\n".join(block.text for block in blocks)
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    unique_lines = set(lines)
    cjk_count = len(re.findall(r"[\u4e00-\u9fff]", text))
    word_count = len(re.findall(r"[A-Za-z0-9_]{2,}", text))

    if len(unique_lines) < 3:
        return False
    if cjk_count >= 80 or word_count >= 80:
        return True
    return len(text.strip()) >= 500 and len(unique_lines) >= 5
