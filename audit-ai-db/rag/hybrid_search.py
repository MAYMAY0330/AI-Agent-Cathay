from __future__ import annotations

from rag.agentic_search import search_agentic
from rag.keyword_search import search_chunks
from rag.metadata_search import search_metadata
from rag.search_models import SearchFilters, SearchResult
from rag.vector_search import search_vectors


def hybrid_search(
    conn,
    query: str,
    *,
    limit: int = 10,
    filters: SearchFilters | None = None,
    include_keyword: bool = True,
    include_metadata: bool = True,
    include_vector: bool = False,
    include_agentic: bool = False,
    embedding_model: str | None = None,
    max_agentic_queries: int = 3,
) -> list[SearchResult]:
    filters = filters or SearchFilters()
    candidates: list[SearchResult] = []

    if include_keyword:
        candidates.extend(
            search_chunks(
                conn,
                query,
                limit=max(limit * 3, limit),
                filters=filters,
            )
        )
    if include_metadata:
        candidates.extend(
            search_metadata(
                conn,
                query,
                limit=max(limit, 5),
                filters=filters,
            )
        )
    if include_vector:
        vector_kwargs = {"model": embedding_model} if embedding_model else {}
        candidates.extend(
            search_vectors(
                conn,
                query,
                limit=max(limit * 3, limit),
                filters=filters,
                **vector_kwargs,
            )
        )
    if include_agentic:
        candidates.extend(
            search_agentic(
                conn,
                query,
                limit=max(limit * 2, limit),
                filters=filters,
                include_keyword=include_keyword,
                include_metadata=include_metadata,
                include_vector=include_vector,
                embedding_model=embedding_model,
                max_queries=max_agentic_queries,
            )
        )

    merged = _merge_results(candidates)
    _recompute_hybrid_scores(merged)
    merged.sort(key=lambda result: result.score, reverse=True)
    return merged[:limit]


def _merge_results(results: list[SearchResult]) -> list[SearchResult]:
    by_chunk: dict[str, SearchResult] = {}
    for result in results:
        existing = by_chunk.get(result.chunk_id)
        if existing is None:
            by_chunk[result.chunk_id] = result
            continue
        existing.merge(result)
    return list(by_chunk.values())


def _recompute_hybrid_scores(results: list[SearchResult]) -> None:
    weights = {
        "vector_score": 0.50,
        "keyword_score": 0.35,
        "metadata_score": 0.10,
        "agentic_score": 0.15,
    }
    for result in results:
        weighted_total = 0.0
        used_weight = 0.0
        for score_name, weight in weights.items():
            source_score = result.score_details.get(score_name)
            if source_score is None:
                continue
            weighted_total += source_score * weight
            used_weight += weight

        if used_weight:
            result.score = weighted_total / used_weight

        overlap_count = sum(
            1
            for source in ("keyword", "metadata", "vector", "agentic")
            if source in result.match_sources
        )
        if overlap_count >= 2:
            boost = 0.10 * (overlap_count - 1)
            result.score += boost
            result.score_details["hybrid_overlap_boost"] = boost
