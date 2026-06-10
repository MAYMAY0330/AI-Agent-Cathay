from __future__ import annotations

from rag.query_terms import build_query_terms
from rag.search_models import SearchFilters, SearchResult


def search_chunks(
    conn,
    query: str,
    *,
    limit: int = 10,
    filters: SearchFilters | None = None,
) -> list[SearchResult]:
    filters = filters or SearchFilters()
    terms = build_query_terms(query)
    if not terms:
        return []

    with conn.cursor() as cur:
        cur.execute(
            """
            WITH q AS (
                SELECT
                    websearch_to_tsquery('simple', %(query)s) AS ts_query,
                    %(terms)s::text[] AS terms
            ),
            scored AS (
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
                    ts_rank_cd(c.search_vector, q.ts_query) AS full_text_score,
                    GREATEST(
                        similarity(c.chunk_text, %(query)s),
                        similarity(coalesce(c.heading_path, ''), %(query)s),
                        similarity(coalesce(c.section_title, ''), %(query)s),
                        similarity(coalesce(d.title, ''), %(query)s)
                    ) AS trigram_score,
                    COALESCE(
                        (
                            SELECT COUNT(*)::float / GREATEST(cardinality(q.terms), 1)
                            FROM unnest(q.terms) AS term
                            WHERE c.chunk_text ILIKE '%%' || term || '%%'
                               OR coalesce(c.heading_path, '') ILIKE '%%' || term || '%%'
                               OR coalesce(c.section_title, '') ILIKE '%%' || term || '%%'
                               OR coalesce(c.clause_number, '') ILIKE '%%' || term || '%%'
                               OR d.title ILIKE '%%' || term || '%%'
                        ),
                        0.0
                    ) AS term_match_score
                FROM document_chunks c
                LEFT JOIN document_chunks p ON p.id = c.parent_chunk_id
                JOIN documents d ON d.id = c.document_id
                JOIN document_versions v ON v.id = c.version_id
                CROSS JOIN q
                WHERE v.is_current = TRUE
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
            )
            SELECT *,
                (
                    full_text_score * 0.55
                    + trigram_score * 0.30
                    + term_match_score * 0.15
                ) AS score
            FROM scored
            WHERE full_text_score > 0
               OR trigram_score >= %(trigram_threshold)s
               OR term_match_score > 0
            ORDER BY score DESC, chunk_index ASC
            LIMIT %(limit)s
            """,
            {
                "query": query,
                "terms": terms,
                "limit": limit,
                "trigram_threshold": 0.05,
                "document_type": filters.document_type,
                "status": filters.status,
                "source_system": filters.source_system,
                "language": filters.language,
                "is_latest": filters.is_latest,
            },
        )
        rows = cur.fetchall()

    results: list[SearchResult] = []
    for row in rows:
        sources = _match_sources(row)
        results.append(
            SearchResult.from_row(
                row,
                match_sources=sources,
                score_details={
                    "keyword_score": float(row.get("score") or 0),
                    "keyword_full_text": float(row.get("full_text_score") or 0),
                    "keyword_trigram": float(row.get("trigram_score") or 0),
                    "keyword_term": float(row.get("term_match_score") or 0),
                },
            )
        )
    return results


def _match_sources(row: dict) -> list[str]:
    sources = ["keyword"]
    if float(row.get("full_text_score") or 0) > 0:
        sources.append("full_text")
    if float(row.get("trigram_score") or 0) > 0:
        sources.append("trigram")
    if float(row.get("term_match_score") or 0) > 0:
        sources.append("term")
    return sources
