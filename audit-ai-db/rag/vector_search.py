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
                c.id AS chunk_id,
                c.document_id,
                c.version_id,
                d.internal_code,
                d.title,
                d.document_type,
                d.source_system,
                c.section_title,
                c.heading_path,
                c.clause_number,
                c.page_start,
                c.page_end,
                c.chunk_index,
                c.chunk_text,
                e.embedding <=> %(query_vector)s::vector AS cosine_distance,
                1 - (e.embedding <=> %(query_vector)s::vector) AS score
            FROM chunk_embeddings e
            JOIN document_chunks c ON c.id = e.chunk_id
            JOIN documents d ON d.id = c.document_id
            JOIN document_versions v ON v.id = c.version_id
            WHERE e.embedding_model = %(model)s
              AND v.is_current = TRUE
              AND (%(document_type)s::text IS NULL OR d.document_type = %(document_type)s::text)
              AND (%(status)s::text IS NULL OR d.status = %(status)s::text)
              AND (%(source_system)s::text IS NULL OR d.source_system = %(source_system)s::text)
              AND (%(language)s::text IS NULL OR d.language = %(language)s::text)
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
