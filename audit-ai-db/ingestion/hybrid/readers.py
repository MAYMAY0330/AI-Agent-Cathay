from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ingestion.advanced_markdown import parse_local_markdown
from ingestion.gemini.reader import GeminiReadResult, read_document_with_gemini
from ingestion.markdown_converter import write_markdown_artifact
from ingestion.models import DocumentMetadata, FileInfo, TextBlock
from ingestion.text_extractor import extract_text


@dataclass(frozen=True)
class LocalReadResult:
    blocks: list[TextBlock]
    markdown: str
    output_markdown_path: Path
    parse_engine: str
    table_repair_status: str


def read_local_blocks(file_info: FileInfo) -> list[TextBlock]:
    return extract_text(file_info.file_path, file_info.file_type)


def read_local_document(
    file_info: FileInfo,
    metadata: DocumentMetadata,
    output_root: Path,
    *,
    output_name: str,
) -> LocalReadResult:
    blocks = read_local_blocks(file_info)
    parsed = parse_local_markdown(file_info, metadata, blocks)
    markdown_path = write_markdown_artifact(parsed.markdown, output_root, output_name)
    return LocalReadResult(
        blocks=blocks,
        markdown=parsed.markdown,
        output_markdown_path=markdown_path,
        parse_engine=parsed.engine,
        table_repair_status=parsed.table_repair_status,
    )


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
