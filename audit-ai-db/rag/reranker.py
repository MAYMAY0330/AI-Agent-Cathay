from __future__ import annotations

from functools import lru_cache
from typing import Any

from rag.search_models import SearchResult


DEFAULT_RERANKER_MODEL = "BAAI/bge-reranker-v2-m3"
RERANKER_SCORE_KEY = "reranker_score"


def rerank_results(
    query: str,
    results: list[SearchResult],
    *,
    model: str = DEFAULT_RERANKER_MODEL,
    fail_open: bool = True,
) -> list[SearchResult]:
    if not results:
        return []

    try:
        reranker = _load_flag_reranker(model)
        pairs = [[query, _rerank_text(result)] for result in results]
        raw_scores = reranker.compute_score(pairs, normalize=True)
        scores = _coerce_scores(raw_scores, expected_count=len(results))
    except Exception as exc:
        if not fail_open:
            raise
        for result in results:
            result.score_details["reranker_error"] = str(exc)
        return results

    for result, score in zip(results, scores):
        result.score_details.setdefault("hybrid_score_before_rerank", result.score)
        result.score_details[RERANKER_SCORE_KEY] = score
        result.score = score

    return sorted(
        results,
        key=lambda result: (
            result.score_details.get(RERANKER_SCORE_KEY, -1.0),
            result.score_details.get("hybrid_score_before_rerank", result.score),
        ),
        reverse=True,
    )


def _rerank_text(result: SearchResult) -> str:
    return result.matched_chunk_text or result.chunk_text


@lru_cache(maxsize=4)
def _load_flag_reranker(model: str) -> Any:
    try:
        from FlagEmbedding import FlagReranker
    except ImportError as exc:
        raise RuntimeError(
            "FlagEmbedding is required for --rerank. Install dependencies with: pip install -r requirements.txt"
        ) from exc
    return FlagReranker(model, use_fp16=False)


def _coerce_scores(raw_scores: Any, *, expected_count: int) -> list[float]:
    if expected_count == 1 and isinstance(raw_scores, (int, float)):
        return [float(raw_scores)]
    if not isinstance(raw_scores, list):
        try:
            raw_scores = list(raw_scores)
        except TypeError as exc:
            raise ValueError("Reranker returned a non-iterable score payload") from exc
    if len(raw_scores) != expected_count:
        raise ValueError(
            f"Reranker returned {len(raw_scores)} scores for {expected_count} results"
        )
    return [float(score) for score in raw_scores]
