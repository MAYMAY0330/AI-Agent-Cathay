from __future__ import annotations

from pathlib import Path
import re
from typing import Iterator

from ingestion.models import IngestionError, TextBlock
from ingestion.text_cleaner import clean_extracted_text


def extract_text(file_path: Path, file_type: str) -> list[TextBlock]:
    if file_type == "docx":
        return _extract_docx(file_path)
    if file_type == "pdf":
        return _extract_pdf(file_path)
    if file_type in {"xlsx", "xls", "csv"}:
        return _extract_markitdown_file(file_path, file_type)
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
            text = clean_extracted_text(block.text)
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
            cell_text = []
            for cell in row.cells:
                cleaned_cell = clean_extracted_text(cell.text).replace("\n", " ")
                if cleaned_cell:
                    cell_text.append(cleaned_cell)
            if cell_text:
                rows.append(" | ".join(cell_text))
        table_text = clean_extracted_text("\n".join(rows))
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
            text = clean_extracted_text(page.get_text("text"))
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
            text = clean_extracted_text(page.extract_text() or "")
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


def _extract_markitdown_file(file_path: Path, file_type: str) -> list[TextBlock]:
    if file_type == "csv":
        try:
            text = clean_extracted_text(file_path.read_text(encoding="utf-8-sig"))
        except UnicodeDecodeError:
            text = clean_extracted_text(file_path.read_text(encoding="big5", errors="ignore"))
        except OSError as exc:
            raise IngestionError("text_extraction", f"unable to open CSV: {exc}") from exc
        if not text:
            raise IngestionError("text_extraction", "CSV contains no extractable text")
        return [TextBlock(block_index=1, text=text, style="table")]

    try:
        from markitdown import MarkItDown
    except ImportError as exc:
        raise IngestionError(
            "text_extraction",
            "MarkItDown is required for spreadsheet extraction. Install dependencies with: pip install -r requirements.txt",
        ) from exc

    try:
        result = MarkItDown().convert(str(file_path))
        text = clean_extracted_text(result.text_content)
    except Exception as exc:
        raise IngestionError("text_extraction", f"unable to convert spreadsheet: {exc}") from exc

    if not text:
        raise IngestionError("text_extraction", "spreadsheet contains no extractable text")
    return [TextBlock(block_index=1, text=text, style="table")]


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
