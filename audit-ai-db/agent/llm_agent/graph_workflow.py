from __future__ import annotations

from datetime import datetime
from typing import Literal, TypedDict

from langgraph.graph import END, START, StateGraph

from agent.state import AgentAnswer, AgentState, EvidenceJudgment, VerificationResult
from agent.tool_registry import ToolRegistry


class GraphState(TypedDict):
    agent_state: AgentState


def run_agent_graph(
    state: AgentState,
    *,
    registry: ToolRegistry,
    fixed_filters: dict[str, str],
    limit: int,
    max_iterations: int,
    max_context_chars: int,
    dry_run: bool,
    llm_decisions: bool,
) -> AgentState:
    graph = build_agent_graph(
        registry=registry,
        fixed_filters=fixed_filters,
        limit=limit,
        max_iterations=max_iterations,
        max_context_chars=max_context_chars,
        dry_run=dry_run,
        llm_decisions=llm_decisions,
    )
    result = graph.invoke({"agent_state": state})
    return result["agent_state"]


def build_agent_graph(
    *,
    registry: ToolRegistry,
    fixed_filters: dict[str, str],
    limit: int,
    max_iterations: int,
    max_context_chars: int,
    dry_run: bool,
    llm_decisions: bool,
):
    builder = StateGraph(GraphState)

    builder.add_node("normalize", _make_normalize_node(registry))
    builder.add_node(
        "plan",
        _make_plan_node(
            registry,
            fixed_filters=fixed_filters,
            limit=limit,
            dry_run=dry_run,
            llm_decisions=llm_decisions,
        ),
    )
    builder.add_node("retrieve", _make_retrieve_node(registry))
    builder.add_node(
        "select_evidence",
        _make_select_evidence_node(
            registry,
            limit=limit,
            max_context_chars=max_context_chars,
        ),
    )
    builder.add_node(
        "judge_evidence",
        _make_judge_evidence_node(
            registry,
            dry_run=dry_run,
            llm_decisions=llm_decisions,
        ),
    )
    builder.add_node(
        "answer",
        _make_answer_node(
            registry,
            dry_run=dry_run,
            max_context_chars=max_context_chars,
        ),
    )
    builder.add_node("verify", _make_verify_node(registry))

    builder.add_edge(START, "normalize")
    builder.add_edge("normalize", "plan")
    builder.add_edge("plan", "retrieve")
    builder.add_edge("retrieve", "select_evidence")
    builder.add_edge("select_evidence", "judge_evidence")
    builder.add_conditional_edges(
        "judge_evidence",
        _make_route_after_judge(max_iterations=max(1, max_iterations)),
        {
            "retry": "plan",
            "answer": "answer",
        },
    )
    builder.add_edge("answer", "verify")
    builder.add_edge("verify", END)
    return builder.compile()


def _make_normalize_node(registry: ToolRegistry):
    def node(graph_state: GraphState) -> GraphState:
        state = graph_state["agent_state"]
        result = registry.call_tool("normalize_question", {"question": state.question})
        state.normalized_question = result["normalized_question"]
        state.keywords = result["keywords"]
        state.inferred_filters = result["filters"]
        return {"agent_state": state}

    return node


def _make_plan_node(
    registry: ToolRegistry,
    *,
    fixed_filters: dict[str, str],
    limit: int,
    dry_run: bool,
    llm_decisions: bool,
):
    def node(graph_state: GraphState) -> GraphState:
        state = graph_state["agent_state"]
        iteration = state.iterations + 1
        filters = _base_filters(state, fixed_filters)
        refined_query = state.refined_queries[-1] if state.refined_queries else ""
        payload = {
            "normalized_question": state.normalized_question,
            "keywords": state.keywords,
            "filters": filters,
            "limit": limit,
            "iteration": iteration,
            "refined_query": refined_query,
        }
        if llm_decisions:
            result = registry.call_tool("plan_search_tasks_llm", payload)
            tasks = result["tasks"]
            state.llm_decisions.append(result["decision"])
        else:
            tasks = registry.call_tool("plan_search_tasks", payload)
            state.llm_decisions.append(
                {
                    "kind": "planner",
                    "mode": "deterministic",
                    "iteration": iteration,
                    "reasoning": "LangGraph used deterministic planner.",
                }
            )
        state.iterations = iteration
        state.search_tasks.extend(tasks)
        return {"agent_state": state}

    return node


def _make_retrieve_node(registry: ToolRegistry):
    def node(graph_state: GraphState) -> GraphState:
        state = graph_state["agent_state"]
        completed_task_ids = {
            result.score_details.get("agent_task_id")
            for result in state.retrieved_results
        }
        for task in state.search_tasks:
            if task.task_id in completed_task_ids:
                continue
            results = registry.call_tool("retrieve_evidence", {"task": task})
            for result in results:
                result.score_details["agent_task_id"] = task.task_id
            state.retrieved_results.extend(results)
        return {"agent_state": state}

    return node


def _make_select_evidence_node(
    registry: ToolRegistry,
    *,
    limit: int,
    max_context_chars: int,
):
    def node(graph_state: GraphState) -> GraphState:
        state = graph_state["agent_state"]
        state.evidence_bundle = registry.call_tool(
            "select_evidence",
            {
                "question": state.normalized_question,
                "results": state.retrieved_results,
                "limit": limit,
                "max_context_chars": max_context_chars,
            },
        )
        return {"agent_state": state}

    return node


def _make_judge_evidence_node(
    registry: ToolRegistry,
    *,
    dry_run: bool,
    llm_decisions: bool,
):
    def node(graph_state: GraphState) -> GraphState:
        state = graph_state["agent_state"]
        deterministic = registry.call_tool(
            "check_evidence_sufficiency",
            {"bundle": state.evidence_bundle},
        )
        state.verification = deterministic
        checklist_judgments = []
        if state.evidence_bundle is not None:
            checklist_judgments = registry.call_tool(
                "judge_evidence_checklist",
                {
                    "question": state.normalized_question,
                    "bundle": state.evidence_bundle,
                },
            )
        if llm_decisions and state.evidence_bundle is not None:
            judgment = registry.call_tool(
                "judge_evidence_llm",
                {
                    "question": state.normalized_question,
                    "bundle": state.evidence_bundle,
                    "deterministic": deterministic,
                },
            )
            decision = {
                "kind": "evidence_judge",
                "iteration": state.iterations,
                **judgment,
            }
            state.llm_decisions.append(decision)
            if judgment.get("judgments"):
                checklist_judgments = list(judgment["judgments"])
            refined_query = str(judgment.get("refined_query") or "").strip()
            if refined_query and not judgment.get("is_sufficient"):
                state.refined_queries.append(refined_query)
        else:
            state.llm_decisions.append(
                {
                    "kind": "evidence_judge",
                    "mode": "deterministic",
                    "iteration": state.iterations,
                    "reasoning": "LangGraph used deterministic checklist evidence judge.",
                }
            )

        if state.evidence_bundle is not None and checklist_judgments:
            state.evidence_bundle = registry.call_tool(
                "apply_evidence_judgments",
                {
                    "bundle": state.evidence_bundle,
                    "judgments": checklist_judgments,
                },
            )
            state.evidence_judgments = _relabel_judgments(
                checklist_judgments,
                state.evidence_bundle,
            )
            checklist_verification = _verify_checklist_judgments(state.evidence_judgments)
            if deterministic.valid and checklist_verification.valid:
                state.verification = checklist_verification
            else:
                state.verification = checklist_verification if not checklist_verification.valid else deterministic
        return {"agent_state": state}

    return node


def _make_route_after_judge(*, max_iterations: int):
    def route(graph_state: GraphState) -> Literal["retry", "answer"]:
        state = graph_state["agent_state"]
        if state.verification is not None and state.verification.valid:
            return "answer"
        if state.iterations < max_iterations:
            return "retry"
        return "answer"

    return route


def _make_answer_node(
    registry: ToolRegistry,
    *,
    dry_run: bool,
    max_context_chars: int,
):
    def node(graph_state: GraphState) -> GraphState:
        state = graph_state["agent_state"]
        if state.evidence_bundle is not None and state.verification is not None and state.verification.valid:
            state.rag_context = registry.call_tool(
                "build_answer_context",
                {
                    "question": state.normalized_question,
                    "bundle": state.evidence_bundle,
                    "max_context_chars": max_context_chars,
                },
            )
            state.answer = registry.call_tool(
                "generate_cited_answer",
                {
                    "context": state.rag_context,
                    "dry_run": dry_run,
                },
            )
        else:
            reason = state.verification.reason if state.verification else "Insufficient evidence."
            state.answer = registry.call_tool(
                "generate_cited_answer",
                {
                    "dry_run": dry_run,
                    "insufficient_reason": reason,
                },
            )
        return {"agent_state": state}

    return node


def _make_verify_node(registry: ToolRegistry):
    def node(graph_state: GraphState) -> GraphState:
        state = graph_state["agent_state"]
        sources = state.evidence_bundle.sources if state.evidence_bundle else []
        state.verification = registry.call_tool(
            "verify_citations",
            {
                "answer": state.answer,
                "sources": sources,
            },
        )
        state.status = _final_status(state.answer, state.verification)
        state.finished_at = datetime.now().isoformat(timespec="seconds")
        return {"agent_state": state}

    return node


def _base_filters(state: AgentState, fixed_filters: dict[str, str]) -> dict[str, str]:
    filters = {**state.inferred_filters, **fixed_filters}
    return {key: value for key, value in filters.items() if value}


def _final_status(answer: AgentAnswer | None, verification: VerificationResult | None) -> str:
    if answer is None:
        return "failed_verification"
    if answer.status == "dry_run":
        return "dry_run"
    if answer.status == "insufficient_evidence":
        return "insufficient_evidence"
    if verification is not None and not verification.valid:
        return "failed_verification"
    return "answered"


def _relabel_judgments(
    judgments: list[EvidenceJudgment],
    bundle,
) -> list[EvidenceJudgment]:
    label_by_chunk = {source.chunk_id: source.label for source in bundle.sources}
    relabeled: list[EvidenceJudgment] = []
    for judgment in judgments:
        label = label_by_chunk.get(judgment.chunk_id, judgment.label)
        relabeled.append(
            EvidenceJudgment(
                label=label,
                chunk_id=judgment.chunk_id,
                checklist=judgment.checklist,
                score=judgment.score,
                max_score=judgment.max_score,
                classification=judgment.classification,
                reason=judgment.reason,
                supporting_quote=judgment.supporting_quote,
                mode=judgment.mode,
            )
        )
    relabeled.sort(key=lambda judgment: _label_number(judgment.label))
    return relabeled


def _verify_checklist_judgments(judgments: list[EvidenceJudgment]) -> VerificationResult:
    strong_labels = [
        judgment.label
        for judgment in judgments
        if judgment.classification == "strong"
        and judgment.checklist.get("direct_answer") == 1
    ]
    if strong_labels:
        return VerificationResult(
            valid=True,
            cited_labels=strong_labels,
            reason=f"Checklist evidence judge found strong support: {','.join(strong_labels)}.",
        )
    if not judgments:
        return VerificationResult(
            valid=False,
            errors=["no_evidence_judgments"],
            reason="No evidence checklist judgments were available.",
        )
    best = max(judgments, key=lambda judgment: judgment.score)
    return VerificationResult(
        valid=False,
        errors=["no_strong_evidence"],
        reason=f"No source passed as strong direct evidence. Best={best.label} score={best.score}/{best.max_score}.",
    )


def _label_number(label: str) -> int:
    try:
        return int(label.removeprefix("S"))
    except ValueError:
        return 10_000
