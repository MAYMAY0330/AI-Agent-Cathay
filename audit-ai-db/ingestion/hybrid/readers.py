from __future__ import annotations

from pathlib import Path

from ingestion.gemini.reader import GeminiReadResult, read_document_with_gemini
from ingestion.models import FileInfo, TextBlock
from ingestion.text_extractor import extract_text


def read_local_blocks(file_info: FileInfo) -> list[TextBlock]:
    return extract_text(file_info.file_path, file_info.file_type)


def read_gemini_document(
    file_info: FileInfo,
    output_root: Path,
    *,
    max_pages: int | None,
    vision_mode: str,
    max_vision_pages: int | None,
    output_name: str,
) -> GeminiReadResult:
    return read_document_with_gemini(
        file_info.file_path,
        file_info.file_type,
        output_root,
        max_pages=max_pages,
        vision_mode=vision_mode,
        max_vision_pages=max_vision_pages,
        output_name=output_name,
    )
