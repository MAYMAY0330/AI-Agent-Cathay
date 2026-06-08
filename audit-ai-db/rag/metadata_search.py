from __future__ import annotations

from rag.query_terms import build_query_terms
from rag.search_models import SearchFilters, SearchResult


def search_metadata(
    conn,
    query: str,
    *,
    limit: int = 10,
    chunks_per_document: int = 2,
    filters: SearchFilters | None = None,
) -> list[SearchResult]:
    filters = filters or SearchFilters()
    terms = build_query_terms(query)
    if not terms:
        return []

    doc_limit = max(1, limit)
    row_limit = max(1, limit * chunks_per_document)

    with conn.cursor() as cur:
        cur.execute(
            """
            WITH q AS (
                SELECT %(terms)s::text[] AS terms
            ),
            matched_documents AS (
                SELECT
                    d.*,
                    GREATEST(
                        similarity(d.title, %(query)s),
                        similarity(coalesce(d.short_summary, ''), %(query)s),
                        similarity(coalesce(d.responsible_unit, ''), %(query)s),
                        similarity(coalesce(d.system_category, ''), %(query)s),
                        similarity(array_to_string(coalesce(d.keywords, ARRAY[]::text[]), ' '), %(query)s),
                        similarity(array_to_string(coalesce(d.main_topics, ARRAY[]::text[]), ' '), %(query)s)
                    ) AS metadata_trigram_score,
                    COALESCE(
                        (
                            SELECT COUNT(*)::float / GREATEST(cardinality(q.terms), 1)
                            FROM unnest(q.terms) AS term
                            WHERE d.title ILIKE '%%' || term || '%%'
                               OR coalesce(d.short_summary, '') ILIKE '%%' || term || '%%'
                               OR coalesce(d.document_type, '') ILIKE '%%' || term || '%%'
                               OR coalesce(d.internal_code, '') ILIKE '%%' || term || '%%'
                               OR coalesce(d.source_system, '') ILIKE '%%' || term || '%%'
                               OR coalesce(d.responsible_unit, '') ILIKE '%%' || term || '%%'
                               OR coalesce(d.system_category, '') ILIKE '%%' || term || '%%'
                               OR array_to_string(coalesce(d.keywords, ARRAY[]::text[]), ' ') ILIKE '%%' || term || '%%'
                               OR array_to_string(coalesce(d.main_topics, ARRAY[]::text[]), ' ') ILIKE '%%' || term || '%%'
                        ),
                        0.0
                    ) AS metadata_term_score
                FROM documents d
                CROSS JOIN q
                WHERE (%(document_type)s::text IS NULL OR d.document_type = %(document_type)s::text)
                  AND (%(status)s::text IS NULL OR d.status = %(status)s::text)
                  AND (%(source_system)s::text IS NULL OR d.source_system = %(source_system)s::text)
                  AND (%(language)s::text IS NULL OR d.language = %(language)s::text)
            ),
            ranked_documents AS (
                SELECT *,
                    (
                        metadata_trigram_score * 0.60
                        + metadata_term_score * 0.40
                    ) AS metadata_score
                FROM matched_documents
                WHERE metadata_trigram_score >= %(trigram_threshold)s
                   OR metadata_term_score > 0
                ORDER BY metadata_score DESC, updated_at DESC
                LIMIT %(doc_limit)s
            ),
            chunk_candidates AS (
                SELECT
                    c.id AS chunk_id,
                    c.document_id,
                    c.version_id,
                    c.chunk_level,
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
                    d.metadata_score,
                    d.metadata_trigram_score,
                    d.metadata_term_score,
                    GREATEST(
                        similarity(c.chunk_text, %(query)s),
                        similarity(coalesce(c.heading_path, ''), %(query)s),
                        similarity(coalesce(c.section_title, ''), %(query)s),
                        similarity(coalesce(c.clause_number, ''), %(query)s)
                    ) AS chunk_trigram_score,
                    COALESCE(
                        (
                            SELECT COUNT(*)::float / GREATEST(cardinality(q.terms), 1)
                            FROM unnest(q.terms) AS term
                            WHERE c.chunk_text ILIKE '%%' || term || '%%'
                               OR coalesce(c.heading_path, '') ILIKE '%%' || term || '%%'
                               OR coalesce(c.section_title, '') ILIKE '%%' || term || '%%'
                               OR coalesce(c.clause_number, '') ILIKE '%%' || term || '%%'
                        ),
                        0.0
                    ) AS chunk_term_score
                FROM ranked_documents d
                JOIN document_versions v ON v.document_id = d.id AND v.is_current = TRUE
                JOIN document_chunks c ON c.version_id = v.id
                CROSS JOIN q
            ),
            ranked_chunks AS (
                SELECT
                    *,
                    (
                        chunk_trigram_score * 0.45
                        + chunk_term_score * 0.55
                    ) AS chunk_relevance_score,
                    row_number() OVER (
                        PARTITION BY document_id
                        ORDER BY
                            CASE
                                WHEN chunk_trigram_score >= %(trigram_threshold)s
                                  OR chunk_term_score > 0
                                THEN 0
                                WHEN chunk_level = 'header' THEN 1
                                ELSE 2
                            END,
                            (
                                chunk_trigram_score * 0.45
                                + chunk_term_score * 0.55
                            ) DESC,
                            chunk_index ASC
                    ) AS chunk_rank
                FROM chunk_candidates
            )
            SELECT *,
                (
                    metadata_score * 0.65
                    + chunk_relevance_score * 0.35
                ) AS score
            FROM ranked_chunks
            WHERE chunk_rank <= %(chunks_per_document)s
              AND chunk_relevance_score >= %(min_chunk_relevance)s
            ORDER BY score DESC, chunk_index ASC
            LIMIT %(row_limit)s
            """,
            {
                "query": query,
                "terms": terms,
                "doc_limit": doc_limit,
                "chunks_per_document": chunks_per_document,
                "row_limit": row_limit,
                "trigram_threshold": 0.05,
                "min_chunk_relevance": 0.08,
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
            match_sources=_match_sources(row),
            score_details={
                "metadata_score": float(row.get("score") or 0),
                "metadata_document_score": float(row.get("metadata_score") or 0),
                "metadata_trigram": float(row.get("metadata_trigram_score") or 0),
                "metadata_term": float(row.get("metadata_term_score") or 0),
                "metadata_chunk_relevance": float(row.get("chunk_relevance_score") or 0),
                "metadata_chunk_trigram": float(row.get("chunk_trigram_score") or 0),
                "metadata_chunk_term": float(row.get("chunk_term_score") or 0),
            },
        )
        for row in rows
    ]


def _match_sources(row: dict) -> list[str]:
    sources = ["metadata"]
    if float(row.get("metadata_trigram_score") or 0) > 0:
        sources.append("metadata_trigram")
    if float(row.get("metadata_term_score") or 0) > 0:
        sources.append("metadata_term")
    if float(row.get("chunk_relevance_score") or 0) > 0:
        sources.append("metadata_chunk")
    if float(row.get("chunk_trigram_score") or 0) > 0:
        sources.append("metadata_chunk_trigram")
    if float(row.get("chunk_term_score") or 0) > 0:
        sources.append("metadata_chunk_term")
    return sources
