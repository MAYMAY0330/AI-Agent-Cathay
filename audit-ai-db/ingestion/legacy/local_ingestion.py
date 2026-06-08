from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.append(str(Path(__file__).resolve().parents[2]))

from ingestion import chunker, db_writer, logger, structure_detector, version_checker
from ingestion.checksum import generate_file_checksum
from ingestion.config import DBConfig
from ingestion.file_loader import load_file
from ingestion.metadata_extractor import prepare_metadata
from ingestion.models import DocumentMetadata, FileInfo, IngestionError
from ingestion.summary_generator import generate_summary
from ingestion.text_extractor import extract_text


def run_ingestion(raw_metadata: dict[str, Any]) -> dict[str, Any]:
    file_info: FileInfo | None = None
    metadata: DocumentMetadata | None = None
    file_checksum: str | None = None
    conn = None
    current_stage = "initializing"

    try:
        current_stage = "file_loading"
        file_info = load_file(raw_metadata["file_path"])
        current_stage = "metadata_extraction"
        metadata = prepare_metadata(file_info, raw_metadata)
        current_stage = "checksum_generation"
        file_checksum = generate_file_checksum(file_info.file_path)

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
                "document_id": str(decision.document_id),
                "version_id": str(decision.current_version_id),
                "total_chunks": 0,
            }

        current_stage = "text_extraction"
        blocks = extract_text(file_info.file_path, file_info.file_type)
        current_stage = "structure_detection"
        structure = structure_detector.detect_structure(blocks, metadata.document_type)
        current_stage = "chunking"
        chunks = chunker.create_chunks(structure.sections)

        status = "success"
        stage = "stored_in_db"
        error_message = None
        if structure.used_fallback:
            status = "partial_success"
            stage = "chunking"
            error_message = structure.warning

        current_stage = "summary_generation"
        try:
            summary = generate_summary(blocks, metadata)
        except Exception as exc:
            summary = None
            status = "partial_success"
            stage = "summary_generation"
            error_message = f"summary generation failed: {exc}"

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
            if summary is not None:
                db_writer.update_document_summary(conn, document_id, summary)

            logger.write_ingestion_log(
                conn,
                status=status,
                stage=stage,
                file_info=file_info,
                metadata=metadata,
                file_checksum=file_checksum,
                document_id=document_id,
                version_id=version_id,
                total_chunks=total_chunks,
                summary_generated=summary.summary_generated if summary else False,
                error_message=error_message,
            )

        return {
            "status": status,
            "stage": stage,
            "document_id": str(document_id),
            "version_id": str(version_id),
            "total_chunks": total_chunks,
            "summary_generated": summary.summary_generated if summary else False,
        }

    except IngestionError as exc:
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


def _try_log_failure(
    *,
    conn,
    file_info: FileInfo | None,
    metadata: DocumentMetadata | None,
    file_checksum: str | None,
    status: str,
    stage: str,
    error_message: str,
    raw_file_path: str | None = None,
) -> None:
    close_after_log = False
    if file_info is None and raw_file_path:
        file_info = _file_info_for_failure_log(raw_file_path)

    if conn is None:
        if stage == "database_connection":
            return
        try:
            conn = db_writer.connect(DBConfig.from_env())
            close_after_log = True
        except Exception:
            return

    try:
        with conn.transaction():
            logger.write_ingestion_log(
                conn,
                status=status,
                stage=stage,
                file_info=file_info,
                metadata=metadata,
                file_checksum=file_checksum,
                error_message=error_message,
            )
    except Exception:
        pass
    finally:
        if close_after_log:
            conn.close()


def _file_info_for_failure_log(raw_file_path: str) -> FileInfo:
    path = Path(raw_file_path).expanduser()
    extension = path.suffix.lower()
    file_size = path.stat().st_size if path.exists() and path.is_file() else 0
    return FileInfo(
        file_path=path,
        file_name=path.name,
        file_extension=extension,
        file_size=file_size,
        file_type=extension.removeprefix("."),
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Legacy local-only ingestion. Prefer: python -m ingestion.run_hybrid_ingestion"
        )
    )
    parser.add_argument("file_path", help="Local .pdf or .docx file path")
    parser.add_argument("--internal-code")
    parser.add_argument("--document-type", default="other")
    parser.add_argument("--language", default="zh-TW")
    parser.add_argument("--data-type")
    parser.add_argument("--title")
    parser.add_argument("--source-url")
    parser.add_argument("--source-system", default="manual_upload")
    parser.add_argument("--source-record-id")
    parser.add_argument("--responsible-unit")
    parser.add_argument("--system-category")
    parser.add_argument("--status", default="active")
    parser.add_argument("--short-summary")
    parser.add_argument(
        "--keywords",
        help="Comma-separated keywords. If omitted, a simple extracted keyword list is used.",
    )
    parser.add_argument(
        "--main-topics",
        help="Comma-separated topic tags. If omitted, document metadata is used.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    raw_metadata = vars(args)

    try:
        result = run_ingestion(raw_metadata)
    except IngestionError as exc:
        print(f"FAILED stage={exc.stage} error={exc.message}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"FAILED stage=unexpected error={exc}", file=sys.stderr)
        return 1

    print(
        "INGESTION_RESULT "
        + " ".join(f"{key}={value}" for key, value in result.items())
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
