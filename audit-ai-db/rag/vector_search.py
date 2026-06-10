from __future__ import annotations

from rag.embedding_client import DEFAULT_EMBEDDING_MODEL, embed_text, embedding_to_pgvector
from rag.search_models import SearchFilters, SearchResult


def search_vectors(
    conn,
    query: str,
    *,
    limit: int = 10,
    filters: SearchFilters | None = None,
    model: str = DEFAULT_EMBEDDING_MODEL,
) -> list[SearchResult]:
    filters = filters or SearchFilters()
    query_embedding = embed_text(query, task_type="retrieval_query", model=model)
    query_vector = embedding_to_pgvector(query_embedding)

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                COALESCE(p.id, c.id) AS chunk_id,
                p.id AS parent_chunk_id,
                c.id AS matched_chunk_id,
                c.document_id,
                c.version_id,
                d.internal_code,
                d.title,
                d.document_type,
                d.source_system,
                COALESCE(p.section_title, c.section_title) AS section_title,
                COALESCE(p.heading_path, c.heading_path) AS heading_path,
                COALESCE(p.clause_number, c.clause_number) AS clause_number,
                COALESCE(p.page_start, c.page_start) AS page_start,
                COALESCE(p.page_end, c.page_end) AS page_end,
                COALESCE(p.chunk_index, c.chunk_index) AS chunk_index,
                COALESCE(p.chunk_text, c.chunk_text) AS chunk_text,
                c.chunk_text AS matched_chunk_text,
                e.embedding <=> %(query_vector)s::vector AS cosine_distance,
                1 - (e.embedding <=> %(query_vector)s::vector) AS score
            FROM chunk_embeddings e
            JOIN document_chunks c ON c.id = e.chunk_id
            LEFT JOIN document_chunks p ON p.id = c.parent_chunk_id
            JOIN documents d ON d.id = c.document_id
            JOIN document_versions v ON v.id = c.version_id
            WHERE e.embedding_model = %(model)s
              AND v.is_current = TRUE
              AND (
                  c.parent_chunk_id IS NOT NULL
                  OR NOT EXISTS (
                      SELECT 1
                      FROM document_chunks child
                      WHERE child.parent_chunk_id = c.id
                  )
              )
              AND (%(document_type)s::text IS NULL OR d.document_type = %(document_type)s::text)
              AND (%(status)s::text IS NULL OR d.status = %(status)s::text)
              AND (%(source_system)s::text IS NULL OR d.source_system = %(source_system)s::text)
              AND (%(language)s::text IS NULL OR d.language = %(language)s::text)
              AND (%(is_latest)s::boolean IS NULL OR d.is_latest = %(is_latest)s::boolean)
            ORDER BY e.embedding <=> %(query_vector)s::vector
            LIMIT %(limit)s
            """,
            {
                "query_vector": query_vector,
                "model": model,
                "limit": limit,
                "document_type": filters.document_type,
                "status": filters.status,
                "source_system": filters.source_system,
                "language": filters.language,
                "is_latest": filters.is_latest,
            },
        )
        rows = cur.fetchall()

    return [
        SearchResult.from_row(
            row,
            match_sources=["vector"],
            score_details={
                "vector_score": float(row.get("score") or 0),
                "vector_cosine_similarity": float(row.get("score") or 0),
                "vector_cosine_distance": float(row.get("cosine_distance") or 0),
            },
        )
        for row in rows
    ]
