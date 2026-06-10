from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.append(str(Path(__file__).resolve().parents[2]))

from ingestion import db_writer, logger, version_checker
from ingestion import chunker
from ingestion.checksum import generate_file_checksum
from ingestion.config import DBConfig
from ingestion.file_loader import load_file
from ingestion.gemini.chunker import chunk_markdown_with_gemini
from ingestion.gemini.reader import (
    GeminiTokenUsage,
    PageAnalysis,
    read_document_with_gemini,
)
from ingestion.legacy.local_ingestion import _try_log_failure
from ingestion.metadata_extractor import prepare_metadata
from ingestion.models import DocumentMetadata, FileInfo, IngestionError


def run_gemini_ingestion(
    raw_metadata: dict[str, Any],
    *,
    output_dir: str = "data/processed/gemini_pipeline",
    max_pages: int | None = None,
    vision_mode: str = "minimal",
    max_vision_pages: int | None = None,
    no_db: bool = False,
) -> dict[str, Any]:
    if max_pages is not None and not no_db:
        raise IngestionError(
            "gemini_configuration",
            "--max-pages can only be used with --no-db to avoid partial database ingestion",
        )

    file_info: FileInfo | None = None
    metadata: DocumentMetadata | None = None
    file_checksum: str | None = None
    conn = None
    current_stage = "initializing"
    output_root = Path(output_dir).expanduser().resolve()

    try:
        current_stage = "file_loading"
        file_info = load_file(raw_metadata["file_path"])
        current_stage = "metadata_extraction"
        metadata = prepare_metadata(file_info, raw_metadata)
        current_stage = "checksum_generation"
        file_checksum = generate_file_checksum(file_info.file_path)
        output_name = _output_name(metadata)

        if not no_db:
            current_stage = "database_connection"
            conn = db_writer.connect(DBConfig.from_env())
            current_stage = "version_check"
            decision = version_checker.check_version(
                conn,
                metadata.internal_code,
                file_checksum,
            )

            if decision.is_duplicate:
                with conn.transaction():
                    logger.write_ingestion_log(
                        conn,
                        status="skipped_duplicate",
                        stage="version_check",
                        file_info=file_info,
                        metadata=metadata,
                        file_checksum=file_checksum,
                        document_id=decision.document_id,
                        version_id=decision.current_version_id,
                        total_chunks=0,
                        summary_generated=False,
                    )
                return {
                    "status": "skipped_duplicate",
                    "stage": "version_check",
                    "pipeline": "gemini",
                    "document_id": str(decision.document_id),
                    "version_id": str(decision.current_version_id),
                    "total_chunks": 0,
                }
        else:
            decision = None

        current_stage = "gemini_reading"
        read_result = read_document_with_gemini(
            file_info.file_path,
            file_info.file_type,
            output_root,
            max_pages=max_pages,
            vision_mode=vision_mode,
            max_vision_pages=max_vision_pages,
            output_name=output_name,
        )
        _write_page_analysis(output_root, output_name, read_result.page_analysis)

        current_stage = "gemini_chunking"
        parent_chunks, summary, chunks_path, chunk_usage = chunk_markdown_with_gemini(
            read_result.markdown,
            metadata,
            output_root,
            output_name=output_name,
        )
        chunks = chunker.add_child_chunks(parent_chunks)
        token_usage = list(read_result.usage or []) + [chunk_usage]
        usage_path = _write_token_usage(output_root, output_name, token_usage)
        usage_summary = _summarize_token_usage(token_usage)

        if no_db:
            return {
                "status": "parsed_no_db",
                "stage": "gemini_chunking",
                "pipeline": "gemini",
                "markdown_path": str(read_result.output_markdown_path),
                "chunks_path": str(chunks_path),
                "total_chunks": len(chunks),
                "summary_generated": summary.summary_generated,
                "gemini_calls": usage_summary["gemini_calls"],
                "input_tokens": usage_summary["input_tokens"],
                "output_tokens": usage_summary["output_tokens"],
                "total_tokens": usage_summary["total_tokens"],
                "usage_path": str(usage_path),
            }

        current_stage = "database_write"
        with conn.transaction():
            if decision.action == "new_document":
                document_id = db_writer.insert_document(conn, metadata)
            else:
                document_id = decision.document_id
                db_writer.update_document_metadata(conn, document_id, metadata)
                db_writer.mark_versions_not_current(conn, document_id)

            version_id = db_writer.insert_document_version(
                conn,
                document_id,
                metadata,
                file_checksum,
                decision.next_version_label,
            )
            total_chunks = db_writer.insert_document_chunks(
                conn,
                document_id,
                version_id,
                chunks,
            )
            db_writer.update_document_summary(conn, document_id, summary)
            logger.write_ingestion_log(
                conn,
                status="success",
                stage="stored_in_db",
                file_info=file_info,
                metadata=metadata,
                file_checksum=file_checksum,
                document_id=document_id,
                version_id=version_id,
                total_chunks=total_chunks,
                summary_generated=summary.summary_generated,
                error_message=None,
            )

        return {
            "status": "success",
            "stage": "stored_in_db",
            "pipeline": "gemini",
            "document_id": str(document_id),
            "version_id": str(version_id),
            "markdown_path": str(read_result.output_markdown_path),
            "chunks_path": str(chunks_path),
            "total_chunks": total_chunks,
            "summary_generated": summary.summary_generated,
            "gemini_calls": usage_summary["gemini_calls"],
            "input_tokens": usage_summary["input_tokens"],
            "output_tokens": usage_summary["output_tokens"],
            "total_tokens": usage_summary["total_tokens"],
            "usage_path": str(usage_path),
        }

    except IngestionError as exc:
        if not no_db:
            _try_log_failure(
                conn=conn,
                file_info=file_info,
                metadata=metadata,
                file_checksum=file_checksum,
                status=exc.status,
                stage=exc.stage,
                error_message=exc.message,
                raw_file_path=raw_metadata.get("file_path"),
            )
        raise
    except Exception as exc:
        if not no_db:
            _try_log_failure(
                conn=conn,
                file_info=file_info,
                metadata=metadata,
                file_checksum=file_checksum,
                status="failed",
                stage=current_stage,
                error_message=str(exc),
                raw_file_path=raw_metadata.get("file_path"),
            )
        raise IngestionError(current_stage, str(exc)) from exc
    finally:
        if conn is not None:
            conn.close()


def _write_page_analysis(
    output_root: Path,
    title: str,
    pages: list[PageAnalysis],
) -> Path | None:
    if not pages:
        return None
    path = output_root / "page_analysis" / f"{_safe_name(title)}.pages.json"
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


def _write_token_usage(
    output_root: Path,
    title: str,
    usage: list[GeminiTokenUsage],
) -> Path:
    path = output_root / "token_usage" / f"{_safe_name(title)}.usage.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "calls": [entry.to_dict() for entry in usage],
        "totals": _summarize_token_usage(usage),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _summarize_token_usage(usage: list[GeminiTokenUsage]) -> dict[str, int]:
    return {
        "gemini_calls": len(usage),
        "input_tokens": sum(entry.input_tokens for entry in usage),
        "output_tokens": sum(entry.output_tokens for entry in usage),
        "total_tokens": sum(entry.total_tokens for entry in usage),
    }


def _output_name(metadata: DocumentMetadata) -> str:
    return _safe_name(
        f"{metadata.internal_code}__{metadata.title}__{metadata.file_type}"
    )


def _safe_name(value: str) -> str:
    return "".join("_" if char in '\\/:*?"<>|' else char for char in value).strip()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Legacy Gemini-only ingestion. Prefer: python -m ingestion.run_hybrid_ingestion"
        )
    )
    parser.add_argument("file_path", help="Local .pdf or .docx file path")
    parser.add_argument("--internal-code")
    parser.add_argument("--document-type", default="other")
    parser.add_argument("--language", default="zh-TW")
    parser.add_argument("--data-type")
    parser.add_argument("--title")
    parser.add_argument("--source-url")
    parser.add_argument("--source-system", default="gemini_ingestion")
    parser.add_argument("--source-record-id")
    parser.add_argument("--responsible-unit")
    parser.add_argument("--system-category")
    parser.add_argument("--status", default="active")
    parser.add_argument(
        "--output-dir",
        default="data/processed/gemini_pipeline",
        help="Where Markdown, page analysis, and Gemini chunks JSON are written.",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        help="Only parse first N PDF pages. Requires --no-db.",
    )
    parser.add_argument(
        "--vision-mode",
        choices=["minimal", "full", "off"],
        default="minimal",
        help=(
            "PDF Vision routing. minimal sends only image-only pages to Gemini; "
            "full also sends mixed text+image pages; off never sends PDF pages to Gemini."
        ),
    )
    parser.add_argument(
        "--max-vision-pages-per-file",
        type=int,
        help="Skip a PDF if more than this many pages would need Gemini Vision.",
    )
    parser.add_argument(
        "--no-db",
        action="store_true",
        help="Parse with Gemini and write Markdown/JSON only; do not write PostgreSQL.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    raw_metadata = vars(args)
    output_dir = raw_metadata.pop("output_dir")
    max_pages = raw_metadata.pop("max_pages")
    vision_mode = raw_metadata.pop("vision_mode")
    max_vision_pages = raw_metadata.pop("max_vision_pages_per_file")
    no_db = raw_metadata.pop("no_db")

    try:
        result = run_gemini_ingestion(
            raw_metadata,
            output_dir=output_dir,
            max_pages=max_pages,
            vision_mode=vision_mode,
            max_vision_pages=max_vision_pages,
            no_db=no_db,
        )
    except IngestionError as exc:
        print(f"FAILED stage={exc.stage} error={exc.message}", file=sys.stderr)
        return 1

    print(
        "GEMINI_INGESTION_RESULT "
        + " ".join(f"{key}={value}" for key, value in result.items())
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
