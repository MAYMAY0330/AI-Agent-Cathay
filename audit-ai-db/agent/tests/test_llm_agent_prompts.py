from __future__ import annotations

import unittest

from agent.llm_agent.decisions import (
    EVIDENCE_JUDGE_RESPONSE_SCHEMA,
    PLANNER_RESPONSE_SCHEMA,
    extract_json_object,
)
from agent.llm_agent.prompts import build_evidence_judge_prompt, build_planner_prompt
from agent.tools import select_evidence
from rag.search_models import SearchResult


class LlmAgentPromptTests(unittest.TestCase):
    def test_planner_prompt_has_required_sections_and_example(self) -> None:
        prompt = build_planner_prompt(
            "資料共享是否需要告知客戶?",
            keywords=["資料共享", "告知客戶"],
            filters={"status": "active"},
            limit=3,
            iteration=1,
            refined_query=None,
        )

        for heading in ("# Role", "# Situation", "# Task", "# Output Format", "# Examples"):
            self.assertIn(heading, prompt)
        self.assertIn("Return only valid JSON", prompt)
        self.assertIn("資料共享 個資告知事項 客戶同意", prompt)

    def test_evidence_judge_prompt_has_required_sections_and_sources(self) -> None:
        bundle = select_evidence(
            "資料共享是否需要告知客戶?",
            [_result()],
            limit=1,
            max_context_chars=1000,
        )
        prompt = build_evidence_judge_prompt("資料共享是否需要告知客戶?", bundle)

        for heading in ("# Role", "# Situation", "# Task", "# Judgment Rules", "# Output Format", "# Examples"):
            self.assertIn(heading, prompt)
        self.assertIn("<source label=\"S1\">", prompt)
        self.assertIn("Do not mark evidence sufficient just because sources are topically related.", prompt)

    def test_extract_json_object_handles_markdown_fence_and_surrounding_text(self) -> None:
        payload = extract_json_object('```json\n{"ok": true}\n```')
        self.assertEqual(payload, {"ok": True})

        payload = extract_json_object('Here is JSON: {"ok": false, "reason": "test"} done.')
        self.assertEqual(payload, {"ok": False, "reason": "test"})

    def test_gemini_decision_schemas_match_expected_contracts(self) -> None:
        self.assertEqual(
            PLANNER_RESPONSE_SCHEMA["required"],
            ["reasoning", "search_tasks"],
        )
        planner_task = PLANNER_RESPONSE_SCHEMA["properties"]["search_tasks"]["items"]
        self.assertEqual(planner_task["required"], ["query", "purpose"])

        self.assertEqual(
            EVIDENCE_JUDGE_RESPONSE_SCHEMA["required"],
            ["is_sufficient", "reason", "supporting_labels", "refined_query"],
        )


def _result() -> SearchResult:
    return SearchResult(
        chunk_id="chunk-1",
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
        chunk_text="資料共享運用範圍應載明於客戶已簽署之契據文件及官網個資應告知事項。",
        score=0.2,
        match_sources=["keyword"],
        score_details={"keyword_score": 0.2},
    )


if __name__ == "__main__":
    unittest.main()
