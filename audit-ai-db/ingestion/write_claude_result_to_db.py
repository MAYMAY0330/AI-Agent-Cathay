from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.append(str(Path(__file__).resolve().parents[1]))

from ingestion import db_writer, logger, version_checker
from ingestion.checksum import generate_file_checksum
from ingestion.claude_chunker import (
    _chunk_records_from_json,
    _optional_string,
    _string_list,
)
from ingestion.config import DBConfig
from ingestion.file_loader import load_file
from ingestion.legacy.local_ingestion import _try_log_failure
from ingestion.metadata_extractor import prepare_metadata
from ingestion.models import DocumentMetadata, FileInfo, IngestionError, SummaryResult


def write_claude_result_to_db(
    raw_metadata: dict[str, Any],
    *,
    chunks_path: str,
    dry_run: bool = False,
) -> dict[str, Any]:
    file_info: FileInfo | None = None
    metadata: DocumentMetadata | None = None
    file_checksum: str | None = None
    conn = None
    current_stage = "initializing"

    try:
        current_stage = "file_loading"
        file_info = load_file(raw_metadata["file_path"])

        current_stage = "claude_result_loading"
        parsed = _load_chunks_json(chunks_path)
        raw_metadata = _merge_metadata_defaults(raw_metadata, parsed)

        current_stage = "metadata_extraction"
        metadata = prepare_metadata(file_info, raw_metadata)
        current_stage = "checksum_generation"
        file_checksum = generate_file_checksum(file_info.file_path)

        current_stage = "claude_result_parsing"
        chunks = _chunk_records_from_json(parsed)
        if not chunks:
            raise IngestionError(
                "claude_result_parsing",
                "Claude result has no valid chunks to write",
            )
        summary = _summary_from_json(parsed)

        if dry_run:
            return {
                "status": "dry_run",
                "stage": "claude_result_parsing",
                "pipeline": "claude_result_import",
                "internal_code": metadata.internal_code,
                "file_name": file_info.file_name,
                "total_chunks": len(chunks),
                "summary_generated": summary.summary_generated,
            }

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
                "pipeline": "claude_result_import",
                "document_id": str(decision.document_id),
                "version_id": str(decision.current_version_id),
                "total_chunks": 0,
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
            "pipeline": "claude_result_import",
            "document_id": str(document_id),
            "version_id": str(version_id),
            "total_chunks": total_chunks,
            "summary_generated": summary.summary_generated,
        }

    except IngestionError as exc:
        if not dry_run:
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
        if not dry_run:
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


def _load_chunks_json(chunks_path: str) -> dict[str, Any]:
    path = Path(chunks_path).expanduser()
    if not path.exists() or not path.is_file():
        raise IngestionError(
            "claude_result_loading",
            f"chunks JSON does not exist: {path}",
        )
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise IngestionError(
            "claude_result_loading",
            f"chunks JSON is invalid: {exc}",
        ) from exc
    if not isinstance(parsed, dict):
        raise IngestionError(
            "claude_result_loading",
            "chunks JSON root must be an object",
        )
    return parsed


def _merge_metadata_defaults(
    raw_metadata: dict[str, Any],
    parsed: dict[str, Any],
) -> dict[str, Any]:
    merged = dict(raw_metadata)
    if not merged.get("document_type"):
        merged["document_type"] = _optional_string(parsed.get("document_type")) or "other"
    return merged


def _summary_from_json(parsed: dict[str, Any]) -> SummaryResult:
    short_summary = _optional_string(parsed.get("short_summary"))
    keywords = _string_list(parsed.get("keywords"))
    main_topics = _string_list(parsed.get("main_topics"))
    return SummaryResult(
        short_summary=short_summary,
        keywords=keywords,
        main_topics=main_topics,
        summary_generated=bool(short_summary or keywords or main_topics),
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Write an existing Claude chunks JSON result into PostgreSQL without "
            "calling Anthropic again."
        )
    )
    parser.add_argument("file_path", help="Original local .pdf or .docx file path")
    parser.add_argument(
        "--chunks-path",
        required=True,
        help="Path to data/processed/claude_pipeline/chunks/*.chunks.json",
    )
    parser.add_argument("--internal-code")
    parser.add_argument("--document-type")
    parser.add_argument("--language", default="zh-TW")
    parser.add_argument("--data-type")
    parser.add_argument("--title")
    parser.add_argument("--source-url")
    parser.add_argument("--source-system", default="claude_result_import")
    parser.add_argument("--source-record-id")
    parser.add_argument("--responsible-unit")
    parser.add_argument("--system-category")
    parser.add_argument("--status", default="active")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate file + chunks JSON only; do not write PostgreSQL.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    raw_metadata = vars(args)
    chunks_path = raw_metadata.pop("chunks_path")
    dry_run = raw_metadata.pop("dry_run")

    try:
        result = write_claude_result_to_db(
            raw_metadata,
            chunks_path=chunks_path,
            dry_run=dry_run,
        )
    except IngestionError as exc:
        print(f"FAILED stage={exc.stage} error={exc.message}", file=sys.stderr)
        return 1

    print(
        "CLAUDE_DB_WRITE_RESULT "
        + " ".join(f"{key}={value}" for key, value in result.items())
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
