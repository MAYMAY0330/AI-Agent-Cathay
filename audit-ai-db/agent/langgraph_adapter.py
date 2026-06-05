from __future__ import annotations

from agent.state import AgentState
from agent.tool_registry import ToolRegistry


def make_normalize_node(registry: ToolRegistry):
    def node(state: AgentState) -> AgentState:
        result = registry.call_tool("normalize_question", {"question": state.question})
        state.normalized_question = result["normalized_question"]
        state.keywords = result["keywords"]
        state.inferred_filters = result["filters"]
        return state

    return node


def make_plan_node(registry: ToolRegistry, *, limit: int):
    def node(state: AgentState) -> AgentState:
        tasks = registry.call_tool(
            "plan_search_tasks",
            {
                "normalized_question": state.normalized_question,
                "keywords": state.keywords,
                "filters": state.inferred_filters,
                "limit": limit,
                "iteration": state.iterations + 1,
            },
        )
        state.iterations += 1
        state.search_tasks.extend(tasks)
        return state

    return node


def make_retrieve_node(registry: ToolRegistry):
    def node(state: AgentState) -> AgentState:
        for task in state.search_tasks:
            if any(result.score_details.get("agent_task_id") == task.task_id for result in state.retrieved_results):
                continue
            results = registry.call_tool("retrieve_evidence", {"task": task})
            for result in results:
                result.score_details["agent_task_id"] = task.task_id
            state.retrieved_results.extend(results)
        return state

    return node


def make_select_evidence_node(
    registry: ToolRegistry,
    *,
    limit: int,
    max_context_chars: int,
):
    def node(state: AgentState) -> AgentState:
        state.evidence_bundle = registry.call_tool(
            "select_evidence",
            {
                "question": state.normalized_question,
                "results": state.retrieved_results,
                "limit": limit,
                "max_context_chars": max_context_chars,
            },
        )
        return state

    return node


def make_sufficiency_node(registry: ToolRegistry):
    def node(state: AgentState) -> AgentState:
        state.verification = registry.call_tool(
            "check_evidence_sufficiency",
            {"bundle": state.evidence_bundle},
        )
        return state

    return node
