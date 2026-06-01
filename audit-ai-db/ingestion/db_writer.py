from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from ingestion.config import DBConfig
from ingestion.models import ChunkRecord, DocumentMetadata, IngestionError, SummaryResult


def connect(config: DBConfig):
    try:
        import psycopg
        from psycopg.rows import dict_row
    except ImportError as exc:
        raise IngestionError(
            "database_connection",
            "psycopg is required. Install dependencies with: pip install -r requirements.txt",
        ) from exc

    return psycopg.connect(
        host=config.host,
        port=config.port,
        dbname=config.dbname,
        user=config.user,
        password=config.password,
        row_factory=dict_row,
        autocommit=True,
    )


def fetch_document_by_internal_code(conn, internal_code: str) -> dict[str, Any] | None:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT * FROM documents WHERE internal_code = %s",
            (internal_code,),
        )
        return cur.fetchone()


def fetch_current_version(conn, document_id: Any) -> dict[str, Any] | None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT *
            FROM document_versions
            WHERE document_id = %s AND is_current = TRUE
            ORDER BY imported_at DESC
            LIMIT 1
            """,
            (document_id,),
        )
        return cur.fetchone()


def count_document_versions(conn, document_id: Any) -> int:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) AS version_count FROM document_versions WHERE document_id = %s",
            (document_id,),
        )
        row = cur.fetchone()
        return int(row["version_count"])


def insert_document(conn, metadata: DocumentMetadata) -> Any:
    values = metadata.document_values()
    columns = list(values.keys())
    placeholders = ", ".join(["%s"] * len(columns))

    with conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO documents ({", ".join(columns)})
            VALUES ({placeholders})
            RETURNING id
            """,
            tuple(values[column] for column in columns),
        )
        return cur.fetchone()["id"]


def update_document_metadata(conn, document_id: Any, metadata: DocumentMetadata) -> None:
    values = metadata.document_values()
    values.pop("internal_code", None)
    values.pop("short_summary", None)
    values.pop("keywords", None)
    values.pop("main_topics", None)

    assignments = ", ".join(f"{column} = %s" for column in values)
    params = [values[column] for column in values]
    params.append(document_id)

    with conn.cursor() as cur:
        cur.execute(
            f"""
            UPDATE documents
            SET {assignments}, updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
            """,
            tuple(params),
        )


def mark_versions_not_current(conn, document_id: Any) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE document_versions SET is_current = FALSE WHERE document_id = %s",
            (document_id,),
        )


def insert_document_version(
    conn,
    document_id: Any,
    metadata: DocumentMetadata,
    file_checksum: str,
    version_label: str,
) -> Any:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO document_versions (
                document_id,
                version_label,
                file_name,
                file_type,
                file_checksum,
                source_url,
                storage_path,
                is_current
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, TRUE)
            RETURNING id
            """,
            (
                document_id,
                version_label,
                metadata.original_file_name,
                metadata.file_type,
                file_checksum,
                metadata.source_url,
                metadata.storage_path,
            ),
        )
        return cur.fetchone()["id"]


def insert_document_chunks(
    conn,
    document_id: Any,
    version_id: Any,
    chunks: Iterable[ChunkRecord],
) -> int:
    rows = [
        (
            document_id,
            version_id,
            chunk.parent_chunk_id,
            chunk.chunk_index,
            chunk.chunk_level,
            chunk.source_structure_type,
            chunk.heading_path,
            chunk.section_title,
            chunk.clause_number,
            chunk.page_start,
            chunk.page_end,
            chunk.chunk_text,
            chunk.token_count,
            chunk.char_count,
        )
        for chunk in chunks
    ]
    if not rows:
        return 0

    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO document_chunks (
                document_id,
                version_id,
                parent_chunk_id,
                chunk_index,
                chunk_level,
                source_structure_type,
                heading_path,
                section_title,
                clause_number,
                page_start,
                page_end,
                chunk_text,
                token_count,
                char_count
            )
            VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
            """,
            rows,
        )
    return len(rows)


def update_document_summary(
    conn,
    document_id: Any,
    summary: SummaryResult,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE documents
            SET short_summary = %s,
                keywords = %s,
                main_topics = %s,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
            """,
            (
                summary.short_summary,
                summary.keywords or None,
                summary.main_topics or None,
                document_id,
            ),
        )
