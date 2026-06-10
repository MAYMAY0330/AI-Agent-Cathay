from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from ingestion.gemini.chunker import chunk_markdown_with_gemini
from ingestion.gemini.reader import GeminiTokenUsage, PageAnalysis
from ingestion import chunker, structure_detector
from ingestion.models import ChunkRecord, DocumentMetadata, FileInfo, SummaryResult
from ingestion.summary_generator import generate_summary

from ingestion.hybrid.readers import read_gemini_document, read_local_document


@dataclass(frozen=True)
class PreparedChunks:
    selected_strategy: str
    stage: str
    status: str
    chunks: list[ChunkRecord]
    summary: SummaryResult
    error_message: str | None = None
    artifact_paths: dict[str, str] = field(default_factory=dict)
    metrics: dict[str, int | str] = field(default_factory=dict)
    markdown: str | None = None


def prepare_local_chunks(
    file_info: FileInfo,
    metadata: DocumentMetadata,
    output_root: Path,
    *,
    parent_chunker: str = "rules",
) -> PreparedChunks:
    output_name = output_name_for_metadata(metadata)
    read_result = read_local_document(
        file_info,
        metadata,
        output_root,
        output_name=output_name,
    )
    blocks = read_result.blocks
    structure = structure_detector.detect_structure(blocks, metadata.document_type)
    artifact_paths = {"markdown_path": str(read_result.output_markdown_path)}
    metrics: dict[str, int | str] = {
        "local_blocks": len(blocks),
        "parse_engine": read_result.parse_engine,
        "table_repair_status": read_result.table_repair_status,
        "parent_chunker": parent_chunker,
    }

    if parent_chunker == "gemini":
        raw_chunks, summary, chunks_path, chunk_usage = chunk_markdown_with_gemini(
            read_result.markdown,
            metadata,
            output_root,
            output_name=output_name,
        )
        chunks = chunker.add_child_chunks(raw_chunks)
        usage_path = write_token_usage(output_root, output_name, [chunk_usage])
        artifact_paths["chunks_path"] = str(chunks_path)
        artifact_paths["usage_path"] = str(usage_path)
        metrics.update(summarize_token_usage([chunk_usage]))
        return PreparedChunks(
            selected_strategy="local",
            stage="llm_parent_chunking",
            status="success",
            chunks=chunks,
            summary=summary,
            artifact_paths=artifact_paths,
            metrics=metrics,
            markdown=read_result.markdown,
        )

    chunks = chunker.create_chunks(structure.sections)

    status = "success"
    stage = "local_chunking"
    error_message = None
    if structure.used_fallback:
        status = "partial_success"
        stage = "chunking"
        error_message = structure.warning

    try:
        summary = generate_summary(blocks, metadata)
    except Exception as exc:
        summary = SummaryResult(
            short_summary=None,
            keywords=metadata.keywords,
            main_topics=metadata.main_topics,
            summary_generated=False,
        )
        status = "partial_success"
        stage = "summary_generation"
        error_message = f"summary generation failed: {exc}"

    return PreparedChunks(
        selected_strategy="local",
        stage=stage,
        status=status,
        chunks=chunks,
        summary=summary,
        error_message=error_message,
        artifact_paths=artifact_paths,
        metrics=metrics,
        markdown=read_result.markdown,
    )


def prepare_gemini_chunks(
    file_info: FileInfo,
    metadata: DocumentMetadata,
    output_root: Path,
    *,
    max_pages: int | None,
    vision_mode: str,
    max_vision_pages: int | None,
) -> PreparedChunks:
    output_name = output_name_for_metadata(metadata)
    read_result = read_gemini_document(
        file_info,
        output_root,
        max_pages=max_pages,
        vision_mode=vision_mode,
        max_vision_pages=max_vision_pages,
        output_name=output_name,
    )
    page_analysis_path = write_page_analysis(
        output_root,
        output_name,
        read_result.page_analysis,
    )

    raw_chunks, summary, chunks_path, chunk_usage = chunk_markdown_with_gemini(
        read_result.markdown,
        metadata,
        output_root,
        output_name=output_name,
    )
    chunks = chunker.add_child_chunks(raw_chunks)
    token_usage = list(read_result.usage or []) + [chunk_usage]
    usage_path = write_token_usage(output_root, output_name, token_usage)
    usage_summary = summarize_token_usage(token_usage)

    artifact_paths = {
        "chunks_path": str(chunks_path),
        "usage_path": str(usage_path),
    }
    if read_result.output_markdown_path is not None:
        artifact_paths["markdown_path"] = str(read_result.output_markdown_path)
    if page_analysis_path is not None:
        artifact_paths["page_analysis_path"] = str(page_analysis_path)

    return PreparedChunks(
        selected_strategy="gemini",
        stage="gemini_chunking",
        status="success",
        chunks=chunks,
        summary=summary,
        artifact_paths=artifact_paths,
        metrics=usage_summary,
        markdown=read_result.markdown,
    )


def write_page_analysis(
    output_root: Path,
    title: str,
    pages: list[PageAnalysis],
) -> Path | None:
    if not pages:
        return None
    path = output_root / "page_analysis" / f"{safe_name(title)}.pages.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [
        {
            "page": page.page,
            "text_chars": page.text_chars,
            "image_count": page.image_count,
            "route": page.route,
            "text_preview": page.text_preview,
        }
        for page in pages
    ]
    path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def write_token_usage(
    output_root: Path,
    title: str,
    usage: list[GeminiTokenUsage],
) -> Path:
    path = output_root / "token_usage" / f"{safe_name(title)}.usage.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "calls": [entry.to_dict() for entry in usage],
        "totals": summarize_token_usage(usage),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def summarize_token_usage(usage: list[GeminiTokenUsage]) -> dict[str, int]:
    return {
        "gemini_calls": len(usage),
        "input_tokens": sum(entry.input_tokens for entry in usage),
        "output_tokens": sum(entry.output_tokens for entry in usage),
        "total_tokens": sum(entry.total_tokens for entry in usage),
    }


def output_name_for_metadata(metadata: DocumentMetadata) -> str:
    return safe_name(f"{metadata.internal_code}__{metadata.title}__{metadata.file_type}")


def safe_name(value: str) -> str:
    return "".join("_" if char in '\\/:*?"<>|' else char for char in value).strip()
