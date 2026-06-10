from __future__ import annotations

import unittest

from agent.state import AgentAnswer
from agent.tool_registry import AgentTool, ToolRegistry
from agent.tools import (
    check_evidence_sufficiency,
    generate_cited_answer,
    judge_evidence_checklist,
    normalize_question,
    plan_search_tasks,
    select_evidence,
    verify_citations,
)
from ingestion.models import IngestionError
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

    def test_select_evidence_surfaces_parent_and_matched_child_fields(self) -> None:
        result = _result(
            "parent-1",
            0.2,
            text="完整父層條文內容",
        )
        result.source_chunk_id = "parent-1"
        result.matched_chunk_id = "child-1"
        result.matched_chunk_text = "精準子層命中文字"
        result.matched_text_preview = "精準子層命中文字"

        bundle = select_evidence(
            "問題",
            [result],
            limit=1,
            max_context_chars=1000,
        )

        self.assertEqual(bundle.sources[0].source_chunk_id, "parent-1")
        self.assertEqual(bundle.sources[0].matched_chunk_id, "child-1")
        self.assertEqual(bundle.sources[0].matched_text_preview, "精準子層命中文字")

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

    def test_judge_evidence_checklist_uses_binary_points(self) -> None:
        bundle = select_evidence(
            "資料共享是否需要告知客戶?",
            [_result("chunk-1", 0.2)],
            limit=1,
            max_context_chars=1000,
        )

        judgments = judge_evidence_checklist("資料共享是否需要告知客戶?", bundle)

        self.assertEqual(len(judgments), 1)
        self.assertEqual(set(judgments[0].checklist.values()), {1})
        self.assertEqual(judgments[0].score, 12)
        self.assertEqual(judgments[0].classification, "strong")

    def test_health_marketing_legal_opinion_is_direct_evidence(self) -> None:
        bundle = select_evidence(
            "客戶健康資料可以用於行銷嗎?",
            [
                _result(
                    "health-marketing",
                    0.2,
                    text=(
                        "法務室意見：本公司蒐集客戶健康相關資料，欲供客戶服務、"
                        "行銷接觸及風險控管等利用時，應檢視個資法及特種個資規定，"
                        "並確認已取得當事人明確同意。"
                    ),
                )
            ],
            limit=1,
            max_context_chars=1000,
        )

        judgment = judge_evidence_checklist("客戶健康資料可以用於行銷嗎?", bundle)[0]

        self.assertEqual(judgment.checklist["direct_answer"], 1)
        self.assertEqual(judgment.classification, "strong")

    def test_generic_data_sharing_range_is_not_direct_for_health_marketing(self) -> None:
        bundle = select_evidence(
            "客戶健康資料可以用於行銷嗎?",
            [
                _result(
                    "sharing-range",
                    0.2,
                    text=(
                        "第四條 客戶資料共享範圍包括客戶基本資料、身分核驗資料、"
                        "帳戶資料、金融商品或服務之交易紀錄、負面資訊及其他依法同意共享之客戶資料。"
                    ),
                )
            ],
            limit=1,
            max_context_chars=1000,
        )

        judgment = judge_evidence_checklist("客戶健康資料可以用於行銷嗎?", bundle)[0]

        self.assertEqual(judgment.checklist["direct_answer"], 0)
        self.assertEqual(judgment.checklist["no_obvious_mismatch"], 0)

    def test_generic_ad_marketing_opinion_is_not_direct_for_health_marketing(self) -> None:
        bundle = select_evidence(
            "客戶健康資料可以用於行銷嗎?",
            [
                _result(
                    "generic-ad-marketing",
                    0.2,
                    text=(
                        "公司將客戶個資提供予數位廣告平台供行銷之用，應經客戶同意後方得為之。"
                        "個資法所稱個人資料包括病歷、醫療、基因、性生活、健康檢查等資料。"
                    ),
                )
            ],
            limit=1,
            max_context_chars=1000,
        )

        judgment = judge_evidence_checklist("客戶健康資料可以用於行銷嗎?", bundle)[0]

        self.assertEqual(judgment.checklist["direct_answer"], 0)
        self.assertEqual(judgment.checklist["no_obvious_mismatch"], 0)

    def test_transmission_rejection_is_not_direct_for_customer_refusing_sharing(self) -> None:
        bundle = select_evidence(
            "客戶拒絕資料共享時公司要怎麼處理?",
            [
                _result(
                    "reject-application",
                    0.2,
                    text=(
                        "金控資訊處負責審閱資料是否完整無虞，如有疑慮應通知相關單位"
                        "重新提供完整資訊，必要時得予以拒絕申請。"
                    ),
                )
            ],
            limit=1,
            max_context_chars=1000,
        )

        judgment = judge_evidence_checklist("客戶拒絕資料共享時公司要怎麼處理?", bundle)[0]

        self.assertEqual(judgment.checklist["direct_answer"], 0)
        self.assertEqual(judgment.checklist["no_obvious_mismatch"], 0)

    def test_generative_ai_definition_is_not_direct_for_disclosure_question(self) -> None:
        bundle = select_evidence(
            "使用生成式AI需要揭露什麼?",
            [
                _result(
                    "genai-definition",
                    0.2,
                    text=(
                        "名詞定義：生成式AI係指可以生成模擬人類智慧創造之內容的相關AI系統，"
                        "其內容形式包括文章、圖像、音訊、影片及程式碼等。"
                    ),
                )
            ],
            limit=1,
            max_context_chars=1000,
        )

        judgment = judge_evidence_checklist("使用生成式AI需要揭露什麼?", bundle)[0]

        self.assertEqual(judgment.checklist["direct_answer"], 0)
        self.assertEqual(judgment.checklist["no_obvious_mismatch"], 0)

    def test_ai_disclosure_checklist_is_direct_for_disclosure_question(self) -> None:
        bundle = select_evidence(
            "使用生成式AI需要揭露什麼?",
            [
                _result(
                    "ai-disclosure",
                    0.2,
                    text=(
                        "如本案直接提供客戶或消費者使用，請檢視是否已告知客戶或消費者其服務"
                        "或互動為AI所提供，並以淺白扼要之方式揭露予客戶或消費者知悉本案之"
                        "AI系統架構、演算法、所使用之功能及決策因素。"
                    ),
                )
            ],
            limit=1,
            max_context_chars=1000,
        )

        judgment = judge_evidence_checklist("使用生成式AI需要揭露什麼?", bundle)[0]

        self.assertEqual(judgment.checklist["direct_answer"], 1)
        self.assertEqual(judgment.classification, "strong")

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

    def test_verify_citations_uses_structured_citations(self) -> None:
        source_bundle = select_evidence(
            "問題",
            [_result("chunk-1", 0.2)],
            limit=1,
            max_context_chars=1000,
        )
        answer = AgentAnswer(
            status="answered",
            answer="應依來源辦理。",
            model="test",
            citations=["S9"],
        )
        verification = verify_citations(answer, source_bundle.sources)
        self.assertFalse(verification.valid)
        self.assertIn("unknown_citations:S9", verification.errors)

    def test_generate_cited_answer_rejects_malformed_llm_json(self) -> None:
        with unittest.mock.patch(
            "agent.tools.generate_answer",
            side_effect=IngestionError("rag_answer_generation", "bad json"),
        ):
            answer = generate_cited_answer(
                context=object(),
                dry_run=False,
            )

        self.assertEqual(answer.status, "failed_verification")


def _result(
    chunk_id: str,
    score: float,
    *,
    text: str = "資料共享依法應取得客戶同意者，應於事前告知客戶並取得其同意後始得為之。",
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
