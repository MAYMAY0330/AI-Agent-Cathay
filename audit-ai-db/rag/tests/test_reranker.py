from __future__ import annotations

import unittest
from unittest.mock import patch

from rag.hybrid_search import hybrid_search
from rag.reranker import rerank_results
from rag.search_models import SearchResult


class RerankerTests(unittest.TestCase):
    def test_reranker_orders_by_mocked_score(self) -> None:
        results = [_result("low", 0.9), _result("high", 0.1)]

        with patch("rag.reranker._load_flag_reranker", return_value=_FakeReranker([0.2, 0.8])):
            reranked = rerank_results("資料共享是否需要告知客戶?", results)

        self.assertEqual([result.chunk_id for result in reranked], ["high", "low"])
        self.assertEqual(reranked[0].score_details["reranker_score"], 0.8)
        self.assertEqual(reranked[0].score_details["hybrid_score_before_rerank"], 0.1)

    def test_reranker_scores_matched_child_text_when_present(self) -> None:
        result = _result(
            "parent",
            0.4,
            text="完整父層上下文",
            matched_text="精準子層命中文字",
        )
        fake = _FakeReranker([0.7])

        with patch("rag.reranker._load_flag_reranker", return_value=fake):
            rerank_results("問題", [result])

        self.assertEqual(fake.pairs, [["問題", "精準子層命中文字"]])

    def test_reranker_fail_open_preserves_hybrid_score(self) -> None:
        result = _result("chunk-1", 0.42)

        with patch("rag.reranker._load_flag_reranker", side_effect=RuntimeError("missing model")):
            reranked = rerank_results("問題", [result], fail_open=True)

        self.assertEqual(reranked[0].score, 0.42)
        self.assertIn("reranker_error", reranked[0].score_details)

    def test_hybrid_search_reranks_candidate_pool(self) -> None:
        low_hybrid = _result("low-hybrid", 0.9, score_details={"keyword_score": 0.9})
        high_rerank = _result("high-rerank", 0.1, score_details={"metadata_score": 0.1})

        with (
            patch("rag.hybrid_search.search_chunks", return_value=[low_hybrid]),
            patch("rag.hybrid_search.search_metadata", return_value=[high_rerank]),
            patch("rag.reranker._load_flag_reranker", return_value=_FakeReranker([0.1, 0.95])),
        ):
            results = hybrid_search(object(), "問題", limit=1, rerank=True, rerank_candidates=2)

        self.assertEqual(results[0].chunk_id, "high-rerank")


class _FakeReranker:
    def __init__(self, scores: list[float]) -> None:
        self.scores = scores
        self.pairs = None

    def compute_score(self, pairs, normalize: bool = True):
        self.pairs = pairs
        return self.scores


def _result(
    chunk_id: str,
    score: float,
    *,
    text: str = "資料共享依法應取得客戶同意者，應於事前告知客戶並取得其同意後始得為之。",
    matched_text: str | None = None,
    score_details: dict[str, float] | None = None,
) -> SearchResult:
    return SearchResult(
        chunk_id=chunk_id,
        document_id="doc-1",
        version_id="ver-1",
        internal_code="CODE-1",
        title="測試文件",
        document_type="internal_rule",
        source_system="test",
        section_title="測試章節",
        heading_path=None,
        clause_number="第一條",
        page_start=1,
        page_end=1,
        chunk_index=1,
        chunk_text=text,
        score=score,
        match_sources=["keyword"],
        score_details=score_details or {"keyword_score": score},
        matched_chunk_id="child-1" if matched_text else None,
        matched_chunk_text=matched_text,
    )


if __name__ == "__main__":
    unittest.main()
