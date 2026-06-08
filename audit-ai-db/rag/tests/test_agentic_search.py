from __future__ import annotations

import unittest
from unittest.mock import patch

from rag.agentic_search import (
    AGENTIC_SEARCH_RESPONSE_SCHEMA,
    build_agentic_search_prompt,
    plan_agentic_search,
)
from rag.hybrid_search import hybrid_search
from rag.search_models import SearchFilters, SearchResult


class AgenticSearchTests(unittest.TestCase):
    def test_agentic_prompt_has_strict_sections_and_examples(self) -> None:
        prompt = build_agentic_search_prompt(
            "資料共享是否需要告知客戶?",
            filters=SearchFilters(status="active", language="zh-TW"),
            max_queries=3,
        )

        for heading in (
            "# Role",
            "# Situation",
            "# Task",
            "# Search Rules",
            "# Output Format",
            "# Examples",
            "# Current Input",
        ):
            self.assertIn(heading, prompt)
        self.assertIn("You do not answer the user and you do not write SQL.", prompt)
        self.assertIn("資料共享 個資應告知事項 契據文件", prompt)

    def test_agentic_schema_requires_queries_filters_and_reason(self) -> None:
        self.assertEqual(
            AGENTIC_SEARCH_RESPONSE_SCHEMA["required"],
            ["reason", "queries", "filters"],
        )
        query_item = AGENTIC_SEARCH_RESPONSE_SCHEMA["properties"]["queries"]["items"]
        self.assertEqual(query_item["required"], ["query", "purpose"])

    def test_plan_agentic_search_validates_queries_and_filters(self) -> None:
        payload = {
            "reason": "測試搜尋擴展",
            "queries": [
                {"query": "資料共享 個資應告知事項", "purpose": "document_phrase_match"},
                {"query": "SELECT * FROM documents", "purpose": "metadata_focus"},
                {"query": "資料共享 個資應告知事項", "purpose": "synonym_expansion"},
            ],
            "filters": {
                "status": "inactive",
                "language": "zh-TW",
            },
        }

        with patch("rag.agentic_search._call_gemini_json", return_value=payload):
            plan = plan_agentic_search(
                "資料共享是否需要告知客戶?",
                filters=SearchFilters(status="active"),
                max_queries=3,
            )

        self.assertEqual(plan.mode, "llm")
        self.assertEqual(len(plan.queries), 1)
        self.assertEqual(plan.queries[0].purpose, "document_phrase_match")
        self.assertEqual(plan.filters.status, "active")
        self.assertEqual(plan.filters.language, "zh-TW")

    def test_hybrid_search_can_include_agentic_results(self) -> None:
        agentic_result = _result(
            chunk_id="chunk-agentic",
            score=0.7,
            match_sources=["agentic"],
            score_details={"agentic_score": 0.7},
        )

        with (
            patch("rag.hybrid_search.search_chunks", return_value=[]),
            patch("rag.hybrid_search.search_metadata", return_value=[]),
            patch("rag.hybrid_search.search_agentic", return_value=[agentic_result]) as agentic,
        ):
            results = hybrid_search(
                object(),
                "資料共享是否需要告知客戶?",
                include_agentic=True,
            )

        self.assertEqual(len(results), 1)
        self.assertIn("agentic", results[0].match_sources)
        agentic.assert_called_once()


def _result(
    *,
    chunk_id: str,
    score: float,
    match_sources: list[str],
    score_details: dict[str, float],
) -> SearchResult:
    return SearchResult(
        chunk_id=chunk_id,
        document_id="doc-1",
        version_id="ver-1",
        internal_code="TEST-1",
        title="測試文件",
        document_type="internal_rule",
        source_system="test",
        section_title="測試章節",
        heading_path=None,
        clause_number="第一條",
        page_start=1,
        page_end=1,
        chunk_index=1,
        chunk_text="資料共享運用範圍應載明於客戶已簽署之契據文件及官網個資應告知事項。",
        score=score,
        match_sources=match_sources,
        score_details=score_details,
    )


if __name__ == "__main__":
    unittest.main()

