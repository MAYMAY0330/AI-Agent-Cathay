from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from ingestion.config import _load_dotenv_file
from ingestion.gemini.reader import call_gemini_text
from ingestion.markdown_converter import blocks_to_markdown
from ingestion.models import DocumentMetadata, FileInfo, IngestionError, TextBlock
from ingestion.text_cleaner import clean_extracted_text


@dataclass(frozen=True)
class MarkdownParseResult:
    markdown: str
    engine: str
    table_repair_status: str = "not_checked"


def parse_local_markdown(
    file_info: FileInfo,
    metadata: DocumentMetadata,
    blocks: list[TextBlock],
) -> MarkdownParseResult:
    fallback = blocks_to_markdown(blocks, file_info=file_info, metadata=metadata)

    if file_info.file_type == "pdf":
        markdown, engine = _try_docling_pdf(file_info.file_path, fallback)
        repaired, repair_status = repair_complex_tables(markdown)
        return MarkdownParseResult(
            markdown=_ensure_title(repaired, metadata.title),
            engine=engine,
            table_repair_status=repair_status,
        )

    if file_info.file_type in {"docx", "xlsx", "xls", "csv"}:
        markdown, engine = _try_markitdown(file_info.file_path, fallback)
        return MarkdownParseResult(
            markdown=_ensure_title(markdown, metadata.title),
            engine=engine,
        )

    return MarkdownParseResult(markdown=fallback, engine="local_blocks")


def repair_complex_tables(markdown: str) -> tuple[str, str]:
    if not detect_broken_table(markdown):
        return markdown, "not_needed"
    if not _gemini_key_available():
        return markdown, "skipped_no_gemini_key"

    try:
        result = call_gemini_text(
            prompt=_build_table_repair_prompt(markdown),
            system=(
                "You repair malformed Markdown tables in internal legal and audit documents. "
                "Return only the complete repaired Markdown document."
            ),
            max_tokens=20000,
            call_name="gemini_table_repair",
        )
    except IngestionError as exc:
        if exc.stage == "gemini_configuration":
            return markdown, "skipped_gemini_unavailable"
        return markdown, f"failed_{exc.stage}"
    except Exception:
        return markdown, "failed_unknown"

    repaired = result.text.strip()
    if len(repaired) < len(markdown) * 0.5:
        return markdown, "failed_too_short"
    return repaired + "\n", "repaired"


def detect_broken_table(markdown: str) -> bool:
    for table in _iter_markdown_tables(markdown):
        if _is_broken_table(table):
            return True
    return False


def _try_docling_pdf(file_path: Path, fallback: str) -> tuple[str, str]:
    try:
        from docling.document_converter import DocumentConverter
    except ImportError:
        return fallback, "local_blocks"

    try:
        result = DocumentConverter().convert(str(file_path))
        markdown = clean_extracted_text(result.document.export_to_markdown())
    except Exception:
        return fallback, "local_blocks_docling_failed"

    if not markdown:
        return fallback, "local_blocks_docling_empty"
    return markdown + "\n", "docling"


def _try_markitdown(file_path: Path, fallback: str) -> tuple[str, str]:
    try:
        from markitdown import MarkItDown
    except ImportError:
        return fallback, "local_blocks"

    try:
        result = MarkItDown().convert(str(file_path))
        markdown = clean_extracted_text(result.text_content)
    except Exception:
        return fallback, "local_blocks_markitdown_failed"

    if not markdown:
        return fallback, "local_blocks_markitdown_empty"
    return markdown + "\n", "markitdown"


def _iter_markdown_tables(markdown: str) -> list[list[str]]:
    tables: list[list[str]] = []
    current: list[str] = []

    for line in markdown.splitlines():
        stripped = line.strip()
        if stripped.startswith("|") and stripped.endswith("|"):
            current.append(stripped)
            continue
        if current:
            tables.append(current)
            current = []

    if current:
        tables.append(current)
    return tables


def _is_broken_table(table_lines: list[str]) -> bool:
    data_rows = [
        line
        for line in table_lines
        if not re.fullmatch(r"\|[\s\-:|]+\|", line.strip())
    ]
    if len(data_rows) < 2:
        return False

    rows = [[cell.strip() for cell in row.split("|")[1:-1]] for row in data_rows]
    expected_columns = len(rows[0])
    if expected_columns < 2:
        return False

    total_cells = sum(len(row) for row in rows)
    empty_cells = sum(1 for row in rows for cell in row if not cell)
    empty_ratio = empty_cells / total_cells if total_cells else 0
    column_mismatch = any(len(row) != expected_columns for row in rows)
    long_cell = any(len(cell) > 200 for row in rows for cell in row)
    repeated_empty_first_cell = _has_repeated_empty_first_cell(rows)

    return empty_ratio > 0.30 or column_mismatch or long_cell or repeated_empty_first_cell


def _has_repeated_empty_first_cell(rows: list[list[str]]) -> bool:
    consecutive = 0
    for row in rows:
        if row and not row[0]:
            consecutive += 1
            if consecutive >= 2:
                return True
        else:
            consecutive = 0
    return False


def _gemini_key_available() -> bool:
    project_root = Path(__file__).resolve().parents[1]
    _load_dotenv_file(project_root / ".env")
    return bool(os.getenv("GEMINI_API_KEY"))


def _ensure_title(markdown: str, title: str) -> str:
    cleaned = clean_extracted_text(markdown)
    if re.match(r"^#\s+", cleaned):
        return cleaned.strip() + "\n"
    return f"# {title}\n\n{cleaned}".strip() + "\n"


def _build_table_repair_prompt(markdown: str) -> str:
    return f"""
The Markdown document below may contain malformed tables caused by PDF or Office conversion.

Repair only malformed tables.

Rules:
- Preserve all non-table text exactly.
- Preserve all source numbers, dates, legal markers, and currency values.
- Rebuild malformed tables as valid Markdown tables with aligned rows and columns.
- If merged cells caused blank repeated cells, fill them with the correct repeated label when visible from context.
- Do not summarize, translate, add commentary, or remove content.
- Return the full repaired Markdown document only.

Markdown document:
{markdown}
""".strip()
