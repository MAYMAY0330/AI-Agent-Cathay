from __future__ import annotations

from pathlib import Path
from typing import Any

from ingestion import db_writer, logger, version_checker
from ingestion.checksum import generate_file_checksum
from ingestion.config import DBConfig
from ingestion.file_loader import load_file
from ingestion.legacy.local_ingestion import _try_log_failure
from ingestion.metadata_extractor import prepare_metadata
from ingestion.models import DocumentMetadata, FileInfo, IngestionError

from ingestion.hybrid.chunkers import (
    PreparedChunks,
    prepare_gemini_chunks,
    prepare_local_chunks,
)
from ingestion.hybrid.strategies import StrategyDecision, choose_ingestion_strategy


def run_hybrid_ingestion(
    raw_metadata: dict[str, Any],
    *,
    strategy: str = "auto",
    output_dir: str = "data/processed/hybrid_pipeline",
    max_pages: int | None = None,
    vision_mode: str = "minimal",
    max_vision_pages: int | None = None,
    no_db: bool = False,
) -> dict[str, Any]:
    requested_strategy = strategy.strip().lower()
    if max_pages is not None and not no_db:
        raise IngestionError(
            "hybrid_configuration",
            "--max-pages can only be used with --no-db to avoid partial database ingestion",
        )
    if max_pages is not None and requested_strategy == "local":
        raise IngestionError(
            "hybrid_configuration",
            "--max-pages is only supported by the Gemini preview path",
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

        current_stage = "strategy_selection"
        strategy_decision = choose_ingestion_strategy(
            file_info,
            requested_strategy,
            max_pages=max_pages,
        )

        if not no_db:
            current_stage = "database_connection"
            conn = db_writer.connect(DBConfig.from_env())
            current_stage = "version_check"
            version_decision = version_checker.check_version(
                conn,
                metadata.internal_code,
                file_checksum,
            )

            if version_decision.is_duplicate:
                with conn.transaction():
                    logger.write_ingestion_log(
                        conn,
                        status="skipped_duplicate",
                        stage="version_check",
                        file_info=file_info,
                        metadata=metadata,
                        file_checksum=file_checksum,
                        document_id=version_decision.document_id,
                        version_id=version_decision.current_version_id,
                        total_chunks=0,
                        summary_generated=False,
                    )
                return {
                    "status": "skipped_duplicate",
                    "stage": "version_check",
                    "pipeline": "hybrid",
                    "selected_strategy": strategy_decision.selected_strategy,
                    "strategy_reason": strategy_decision.reason,
                    "document_id": str(version_decision.document_id),
                    "version_id": str(version_decision.current_version_id),
                    "total_chunks": 0,
                }
        else:
            version_decision = None

        current_stage = f"{strategy_decision.selected_strategy}_preparation"
        prepared = _prepare_chunks(
            file_info,
            metadata,
            strategy_decision,
            output_root=output_root,
            max_pages=max_pages,
            vision_mode=vision_mode,
            max_vision_pages=max_vision_pages,
        )

        if no_db:
            return _build_result(
                status="parsed_no_db",
                stage=prepared.stage,
                strategy_decision=strategy_decision,
                prepared=prepared,
                total_chunks=len(prepared.chunks),
            )

        current_stage = "database_write"
        document_id, version_id, total_chunks, final_stage = _store_prepared_chunks(
            conn=conn,
            file_info=file_info,
            metadata=metadata,
            file_checksum=file_checksum,
            version_decision=version_decision,
            prepared=prepared,
        )

        result = _build_result(
            status=prepared.status,
            stage=final_stage,
            strategy_decision=strategy_decision,
            prepared=prepared,
            total_chunks=total_chunks,
        )
        result.update(
            {
                "document_id": str(document_id),
                "version_id": str(version_id),
                "summary_generated": prepared.summary.summary_generated,
            }
        )
        return result

    except IngestionError as exc:
        if (
            requested_strategy == "auto"
            and file_info is not None
            and metadata is not None
            and _should_fallback_to_gemini(file_info, exc)
        ):
            try:
                fallback_decision = StrategyDecision(
                    requested_strategy="auto",
                    selected_strategy="gemini",
                    reason=f"local_failed_{exc.stage}_fallback_gemini",
                    analysis={"local_error": exc.message},
                )
                prepared = _prepare_chunks(
                    file_info,
                    metadata,
                    fallback_decision,
                    output_root=output_root,
                    max_pages=max_pages,
                    vision_mode=vision_mode,
                    max_vision_pages=max_vision_pages,
                )
                if no_db:
                    return _build_result(
                        status="parsed_no_db",
                        stage=prepared.stage,
                        strategy_decision=fallback_decision,
                        prepared=prepared,
                        total_chunks=len(prepared.chunks),
                    )
                if conn is None:
                    raise
                document_id, version_id, total_chunks, final_stage = _store_prepared_chunks(
                    conn=conn,
                    file_info=file_info,
                    metadata=metadata,
                    file_checksum=file_checksum,
                    version_decision=version_decision,
                    prepared=prepared,
                )
                result = _build_result(
                    status=prepared.status,
                    stage=final_stage,
                    strategy_decision=fallback_decision,
                    prepared=prepared,
                    total_chunks=total_chunks,
                )
                result.update(
                    {
                        "document_id": str(document_id),
                        "version_id": str(version_id),
                        "summary_generated": prepared.summary.summary_generated,
                    }
                )
                return result
            except IngestionError as fallback_exc:
                if not no_db:
                    _try_log_failure(
                        conn=conn,
                        file_info=file_info,
                        metadata=metadata,
                        file_checksum=file_checksum,
                        status=fallback_exc.status,
                        stage=fallback_exc.stage,
                        error_message=fallback_exc.message,
                        raw_file_path=raw_metadata.get("file_path"),
                    )
                raise
            except Exception as fallback_exc:
                if not no_db:
                    _try_log_failure(
                        conn=conn,
                        file_info=file_info,
                        metadata=metadata,
                        file_checksum=file_checksum,
                        status="failed",
                        stage="gemini_fallback",
                        error_message=str(fallback_exc),
                        raw_file_path=raw_metadata.get("file_path"),
                    )
                raise IngestionError("gemini_fallback", str(fallback_exc)) from fallback_exc

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


def _store_prepared_chunks(
    *,
    conn,
    file_info: FileInfo,
    metadata: DocumentMetadata,
    file_checksum: str,
    version_decision,
    prepared: PreparedChunks,
) -> tuple[Any, Any, int, str]:
    with conn.transaction():
        if version_decision.action == "new_document":
            document_id = db_writer.insert_document(conn, metadata)
        else:
            document_id = version_decision.document_id
            db_writer.update_document_metadata(conn, document_id, metadata)
            db_writer.mark_versions_not_current(conn, document_id)

        version_id = db_writer.insert_document_version(
            conn,
            document_id,
            metadata,
            file_checksum,
            version_decision.next_version_label,
        )
        total_chunks = db_writer.insert_document_chunks(
            conn,
            document_id,
            version_id,
            prepared.chunks,
        )
        db_writer.update_document_summary(conn, document_id, prepared.summary)

        final_stage = _stored_stage(prepared)
        logger.write_ingestion_log(
            conn,
            status=prepared.status,
            stage=final_stage,
            file_info=file_info,
            metadata=metadata,
            file_checksum=file_checksum,
            document_id=document_id,
            version_id=version_id,
            total_chunks=total_chunks,
            summary_generated=prepared.summary.summary_generated,
            error_message=prepared.error_message,
        )
    return document_id, version_id, total_chunks, final_stage


def _prepare_chunks(
    file_info: FileInfo,
    metadata: DocumentMetadata,
    strategy_decision: StrategyDecision,
    *,
    output_root: Path,
    max_pages: int | None,
    vision_mode: str,
    max_vision_pages: int | None,
) -> PreparedChunks:
    if strategy_decision.selected_strategy == "local":
        return prepare_local_chunks(file_info, metadata)
    return prepare_gemini_chunks(
        file_info,
        metadata,
        output_root,
        max_pages=max_pages,
        vision_mode=vision_mode,
        max_vision_pages=max_vision_pages,
    )


def _should_fallback_to_gemini(file_info: FileInfo, exc: IngestionError) -> bool:
    if file_info.file_type != "pdf":
        return False
    return exc.stage in {
        "text_extraction",
        "structure_detection",
        "chunking",
        "summary_generation",
    }


def _stored_stage(prepared: PreparedChunks) -> str:
    if prepared.status == "success":
        return "stored_in_db"
    return prepared.stage


def _build_result(
    *,
    status: str,
    stage: str,
    strategy_decision: StrategyDecision,
    prepared: PreparedChunks,
    total_chunks: int,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "status": status,
        "stage": stage,
        "pipeline": "hybrid",
        "selected_strategy": strategy_decision.selected_strategy,
        "strategy_reason": strategy_decision.reason,
        "total_chunks": total_chunks,
        "summary_generated": prepared.summary.summary_generated,
    }
    if strategy_decision.analysis:
        result["strategy_analysis"] = strategy_decision.analysis
    if prepared.error_message:
        result["error_message"] = prepared.error_message
    result.update(prepared.artifact_paths)
    result.update(prepared.metrics)
    return result
