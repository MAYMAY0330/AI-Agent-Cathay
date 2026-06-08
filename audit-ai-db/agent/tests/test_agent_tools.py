from __future__ import annotations

import unittest

from agent.state import AgentAnswer
from agent.tool_registry import AgentTool, ToolRegistry
from agent.tools import (
    check_evidence_sufficiency,
    normalize_question,
    plan_search_tasks,
    select_evidence,
    verify_citations,
)
from rag.search_models import SearchResult


class AgentToolTests(unittest.TestCase):
    def test_registry_rejects_missing_required_input(self) -> None:
        registry = ToolRegistry()
        registry.register(
            AgentTool(
                name="echo",
                description="echo",
                input_schema={
                    "type": "object",
                    "required": ["text"],
                    "properties": {"text": {"type": "string"}},
                },
                output_schema={},
                callable=lambda payload: payload,
            )
        )

        with self.assertRaises(ValueError):
            registry.call_tool("echo", {})

    def test_normalize_question_extracts_keywords(self) -> None:
        result = normalize_question("  客戶資料共享是否  需要告知客戶？ ")
        self.assertEqual(result["normalized_question"], "客戶資料共享是否 需要告知客戶?")
        self.assertIn("客戶資料共享", result["keywords"])

    def test_plan_search_tasks_returns_json_compatible_tasks(self) -> None:
        tasks = plan_search_tasks(
            "資料共享是否需要告知客戶?",
            keywords=["資料共享", "告知客戶", "客戶同意"],
            limit=6,
            filters={"document_type": "internal_rule"},
        )
        self.assertGreaterEqual(len(tasks), 1)
        self.assertLessEqual(len(tasks), 3)
        self.assertEqual(tasks[0].limit, 6)
        self.assertEqual(tasks[0].filters["document_type"], "internal_rule")
        self.assertIsInstance(tasks[0].to_dict()["query"], str)

    def test_select_evidence_deduplicates_and_labels_sources(self) -> None:
        duplicate = _result("chunk-1", 0.2)
        stronger_duplicate = _result("chunk-1", 0.4)
        other = _result("chunk-2", 0.3)
        bundle = select_evidence(
            "資料共享是否需要告知客戶?",
            [duplicate, stronger_duplicate, other],
            limit=2,
            max_context_chars=2000,
        )

        self.assertEqual(len(bundle.sources), 2)
        self.assertEqual(bundle.sources[0].label, "S1")
        self.assertEqual({source.chunk_id for source in bundle.sources}, {"chunk-1", "chunk-2"})

    def test_select_evidence_prefers_exact_domain_phrase(self) -> None:
        risk_workflow = _result(
            "risk-workflow",
            0.35,
            text="涉及風險類資料之使用時，應依其性質會簽法令遵循單位、洗錢防制單位或風險管理單位。",
        )
        negative_info = _result(
            "negative-info",
            0.2,
            text="共享之資料如屬身分核驗資料或負面資訊等，對客戶權益有較大影響性者，應審慎辦理並為相關必要措施。",
        )
        bundle = select_evidence(
            "資料共享涉及負面資訊時要注意什麼?",
            [risk_workflow, negative_info],
            limit=2,
            max_context_chars=2000,
        )

        self.assertEqual(bundle.sources[0].chunk_id, "negative-info")

    def test_check_evidence_sufficiency_rejects_empty_or_weak_sources(self) -> None:
        empty_bundle = select_evidence(
            "問題",
            [],
            limit=2,
            max_context_chars=1000,
        )
        self.assertFalse(check_evidence_sufficiency(empty_bundle).valid)

        weak_bundle = select_evidence(
            "問題",
            [_result("chunk-1", 0.01)],
            limit=2,
            max_context_chars=1000,
        )
        self.assertFalse(check_evidence_sufficiency(weak_bundle).valid)

    def test_verify_citations_catches_unknown_label(self) -> None:
        source_bundle = select_evidence(
            "問題",
            [_result("chunk-1", 0.2)],
            limit=1,
            max_context_chars=1000,
        )
        answer = AgentAnswer(
            status="answered",
            answer="應依來源辦理。[S9]",
            model="test",
        )
        verification = verify_citations(answer, source_bundle.sources)
        self.assertFalse(verification.valid)
        self.assertIn("unknown_citations:S9", verification.errors)


def _result(
    chunk_id: str,
    score: float,
    *,
    text: str = "資料共享依法應取得客戶同意者，應於事前取得其同意後始得為之。",
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
        match_sources=["keyword", "term"],
        score_details={"keyword_score": score},
    )


if __name__ == "__main__":
    unittest.main()
