from __future__ import annotations

from typing import Any

from ingestion.models import DocumentMetadata, FileInfo


def write_ingestion_log(
    conn,
    *,
    status: str,
    stage: str,
    file_info: FileInfo | None = None,
    metadata: DocumentMetadata | None = None,
    file_checksum: str | None = None,
    document_id: Any | None = None,
    version_id: Any | None = None,
    total_chunks: int = 0,
    summary_generated: bool = False,
    error_message: str | None = None,
    job_id: str | None = None,
) -> None:
    source_system = metadata.source_system if metadata else None
    source_url = metadata.source_url if metadata else None
    storage_path = metadata.storage_path if metadata else None
    file_name = metadata.original_file_name if metadata else None
    file_type = metadata.file_type if metadata else None

    if file_info and not metadata:
        storage_path = str(file_info.file_path)
        file_name = file_info.file_name
        file_type = file_info.file_type

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO ingestion_logs (
                job_id,
                document_id,
                version_id,
                source_system,
                source_url,
                storage_path,
                file_name,
                file_type,
                file_checksum,
                status,
                stage,
                total_chunks,
                summary_generated,
                error_message,
                finished_at
            )
            VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                CURRENT_TIMESTAMP
            )
            """,
            (
                job_id,
                document_id,
                version_id,
                source_system,
                source_url,
                storage_path,
                file_name,
                file_type,
                file_checksum,
                status,
                stage,
                total_chunks,
                summary_generated,
                error_message,
            ),
        )

