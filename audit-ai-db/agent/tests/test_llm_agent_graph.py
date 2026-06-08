from __future__ import annotations

import unittest

from agent.llm_agent.graph_workflow import run_agent_graph
from agent.state import AgentAnswer, AgentState, SearchTask
from agent.tool_registry import AgentTool, ToolRegistry
from agent.tools import (
    build_answer_context,
    check_evidence_sufficiency,
    normalize_question,
    select_evidence,
    verify_citations,
)
from rag.search_models import SearchResult


class LlmAgentGraphTests(unittest.TestCase):
    def test_graph_runs_llm_decision_path_with_fake_tools(self) -> None:
        registry = _fake_registry()
        state = AgentState(
            run_id="run-1",
            question="資料共享是否需要告知客戶？",
            started_at="2026-06-07T00:00:00",
            status="running",
        )

        result = run_agent_graph(
            state,
            registry=registry,
            fixed_filters={"status": "active"},
            limit=2,
            max_iterations=2,
            max_context_chars=2000,
            dry_run=False,
            llm_decisions=True,
        )

        self.assertEqual(result.status, "answered")
        self.assertEqual(result.answer.status if result.answer else None, "answered")
        self.assertEqual(result.verification.valid if result.verification else None, True)
        self.assertEqual(result.iterations, 1)
        self.assertEqual(result.search_tasks[0].task_id, "llm_search_1_1")
        self.assertEqual([decision["kind"] for decision in result.llm_decisions], ["planner", "evidence_judge"])


def _fake_registry() -> ToolRegistry:
    registry = ToolRegistry()
    _register(registry, "normalize_question", lambda payload: normalize_question(payload["question"]))
    _register(
        registry,
        "plan_search_tasks",
        lambda payload: [
            SearchTask(
                task_id="search_1_1",
                query=payload["normalized_question"],
                purpose="direct_question",
                limit=payload["limit"],
                filters=payload.get("filters") or {},
            )
        ],
    )
    _register(
        registry,
        "plan_search_tasks_llm",
        lambda payload: {
            "tasks": [
                SearchTask(
                    task_id="llm_search_1_1",
                    query="資料共享 告知",
                    purpose="direct_question",
                    limit=payload["limit"],
                    filters=payload.get("filters") or {},
                )
            ],
            "decision": {
                "kind": "planner",
                "mode": "llm",
                "iteration": payload.get("iteration", 1),
                "reasoning": "test planner",
            },
        },
    )
    _register(registry, "retrieve_evidence", lambda payload: [_result()])
    _register(
        registry,
        "select_evidence",
        lambda payload: select_evidence(
            payload["question"],
            payload["results"],
            limit=payload["limit"],
            max_context_chars=payload["max_context_chars"],
        ),
    )
    _register(
        registry,
        "check_evidence_sufficiency",
        lambda payload: check_evidence_sufficiency(payload["bundle"]),
    )
    _register(
        registry,
        "judge_evidence_llm",
        lambda payload: {
            "is_sufficient": True,
            "reason": "test judge",
            "supporting_labels": ["S1"],
            "refined_query": "",
            "mode": "llm",
        },
    )
    _register(
        registry,
        "build_answer_context",
        lambda payload: build_answer_context(
            payload["question"],
            payload["bundle"],
            max_context_chars=payload["max_context_chars"],
        ),
    )
    _register(
        registry,
        "generate_cited_answer",
        lambda payload: AgentAnswer(
            status="answered",
            answer="應依來源辦理。[S1]",
            model="test",
        ),
    )
    _register(
        registry,
        "verify_citations",
        lambda payload: verify_citations(payload["answer"], payload["sources"]),
    )
    return registry


def _register(registry: ToolRegistry, name: str, callable) -> None:
    registry.register(
        AgentTool(
            name=name,
            description=name,
            input_schema={},
            output_schema={},
            callable=callable,
        )
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
        chunk_text="資料共享依法應取得客戶同意者，應於事前取得其同意後始得為之。",
        score=0.2,
        match_sources=["keyword"],
        score_details={"keyword_score": 0.2},
    )


if __name__ == "__main__":
    unittest.main()
