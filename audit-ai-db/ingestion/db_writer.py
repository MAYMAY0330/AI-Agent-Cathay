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


def delete_document_chunks(conn, document_id: Any) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            DELETE FROM chunk_embeddings e
            USING document_chunks c
            WHERE e.chunk_id = c.id
              AND c.document_id = %s
            """,
            (document_id,),
        )
        cur.execute(
            "DELETE FROM document_chunks WHERE document_id = %s",
            (document_id,),
        )
        return cur.rowcount or 0


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
    chunk_list = list(chunks)
    if not chunk_list:
        return 0

    inserted_ids_by_index: dict[int, Any] = {}
    with conn.cursor() as cur:
        for chunk in chunk_list:
            if chunk.parent_chunk_id is not None:
                continue
            inserted_ids_by_index[chunk.chunk_index] = _insert_document_chunk(
                cur,
                document_id=document_id,
                version_id=version_id,
                chunk=chunk,
                parent_chunk_id=None,
            )

        for chunk in chunk_list:
            if chunk.parent_chunk_id is None:
                continue
            parent_chunk_id = _resolve_parent_chunk_id(
                chunk.parent_chunk_id,
                inserted_ids_by_index,
            )
            inserted_ids_by_index[chunk.chunk_index] = _insert_document_chunk(
                cur,
                document_id=document_id,
                version_id=version_id,
                chunk=chunk,
                parent_chunk_id=parent_chunk_id,
            )

    return len(chunk_list)


def _insert_document_chunk(
    cur,
    *,
    document_id: Any,
    version_id: Any,
    chunk: ChunkRecord,
    parent_chunk_id: Any | None,
) -> Any:
    cur.execute(
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
        RETURNING id
        """,
        (
            document_id,
            version_id,
            parent_chunk_id,
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
        ),
    )
    return cur.fetchone()["id"]


def _resolve_parent_chunk_id(
    parent_reference: Any,
    inserted_ids_by_index: dict[int, Any],
) -> Any:
    if isinstance(parent_reference, int):
        return inserted_ids_by_index[parent_reference]
    if isinstance(parent_reference, str) and parent_reference.isdigit():
        return inserted_ids_by_index[int(parent_reference)]
    return parent_reference


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


def expire_older_documents_in_family(
    conn,
    *,
    current_document_id: Any,
    metadata: DocumentMetadata,
) -> Any | None:
    if not metadata.document_family or not metadata.is_latest:
        return None
    if metadata.effective_date is None and metadata.effective_year is None:
        return None
    if _has_newer_document_in_family(
        conn,
        current_document_id=current_document_id,
        metadata=metadata,
    ):
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE documents
                SET status = 'expired',
                    is_latest = FALSE,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
                """,
                (current_document_id,),
            )
        return None

    previous_document_id = _find_previous_document_in_family(
        conn,
        current_document_id=current_document_id,
        metadata=metadata,
    )
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE documents
            SET status = 'expired',
                is_latest = FALSE,
                updated_at = CURRENT_TIMESTAMP
            WHERE document_family = %s
              AND id <> %s
              AND (
                  effective_date IS NULL
                  OR %s::date IS NULL
                  OR effective_date <= %s::date
              )
              AND (
                  effective_year IS NULL
                  OR %s::integer IS NULL
                  OR effective_year <= %s::integer
              )
            """,
            (
                metadata.document_family,
                current_document_id,
                metadata.effective_date,
                metadata.effective_date,
                metadata.effective_year,
                metadata.effective_year,
            ),
        )
        cur.execute(
            """
            UPDATE documents
            SET status = 'active',
                is_latest = TRUE,
                supersedes_document_id = %s,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
            """,
            (previous_document_id, current_document_id),
        )
    return previous_document_id


def _has_newer_document_in_family(
    conn,
    *,
    current_document_id: Any,
    metadata: DocumentMetadata,
) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT 1
            FROM documents
            WHERE document_family = %s
              AND id <> %s
              AND (
                  (%s::date IS NOT NULL AND effective_date > %s::date)
                  OR (
                      %s::date IS NULL
                      AND %s::integer IS NOT NULL
                      AND effective_year > %s::integer
                  )
              )
            LIMIT 1
            """,
            (
                metadata.document_family,
                current_document_id,
                metadata.effective_date,
                metadata.effective_date,
                metadata.effective_date,
                metadata.effective_year,
                metadata.effective_year,
            ),
        )
        return cur.fetchone() is not None


def _find_previous_document_in_family(
    conn,
    *,
    current_document_id: Any,
    metadata: DocumentMetadata,
) -> Any | None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id
            FROM documents
            WHERE document_family = %s
              AND id <> %s
              AND (
                  effective_date IS NULL
                  OR %s::date IS NULL
                  OR effective_date <= %s::date
              )
              AND (
                  effective_year IS NULL
                  OR %s::integer IS NULL
                  OR effective_year <= %s::integer
              )
            ORDER BY effective_date DESC NULLS LAST,
                     effective_year DESC NULLS LAST,
                     updated_at DESC
            LIMIT 1
            """,
            (
                metadata.document_family,
                current_document_id,
                metadata.effective_date,
                metadata.effective_date,
                metadata.effective_year,
                metadata.effective_year,
            ),
        )
        row = cur.fetchone()
    return row["id"] if row else None
