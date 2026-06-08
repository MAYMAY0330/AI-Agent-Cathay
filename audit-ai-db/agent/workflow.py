from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from agent.llm_agent.graph_workflow import run_agent_graph
from agent.state import AgentRunLog, AgentState
from agent.tools import build_tool_registry
from ingestion.config import DBConfig
from ingestion.db_writer import connect
from rag.embedding_client import DEFAULT_EMBEDDING_MODEL


def run_agent(
    question: str,
    *,
    limit: int = 6,
    max_iterations: int = 2,
    document_type: str | None = None,
    source_system: str | None = None,
    language: str | None = None,
    status: str | None = "active",
    include_vector: bool = False,
    include_agentic_search: bool = False,
    embedding_model: str | None = DEFAULT_EMBEDDING_MODEL,
    dry_run: bool = False,
    llm_decisions: bool = True,
    log_dir: Path = Path("data/processed/agent_runs"),
    max_context_chars: int = 12000,
) -> AgentState:
    started_at = _now_iso()
    state = AgentState(
        run_id=str(uuid4()),
        question=question,
        started_at=started_at,
        status="running",
    )

    conn = connect(DBConfig.from_env())
    try:
        registry = build_tool_registry(
            conn,
            include_vector=include_vector,
            include_agentic=include_agentic_search and not dry_run,
            embedding_model=embedding_model,
            dry_run=dry_run,
            log_dir=log_dir,
        )

        fixed_filters = {
            "document_type": document_type,
            "source_system": source_system,
            "language": language,
            "status": status,
        }
        fixed_filters = {key: value for key, value in fixed_filters.items() if value}

        state = run_agent_graph(
            state,
            registry=registry,
            fixed_filters=fixed_filters,
            limit=limit,
            max_iterations=max_iterations,
            max_context_chars=max_context_chars,
            dry_run=dry_run,
            llm_decisions=llm_decisions,
        )

        log = _build_run_log(state, dry_run=dry_run)
        log_path = registry.call_tool("log_agent_run", {"log": log})
        state.log_path = str(log_path)
        return state
    finally:
        conn.close()


def _build_run_log(state: AgentState, *, dry_run: bool) -> AgentRunLog:
    sources = (
        [asdict(source) for source in state.evidence_bundle.sources]
        if state.evidence_bundle
        else []
    )
    return AgentRunLog(
        run_id=state.run_id,
        started_at=state.started_at,
        finished_at=state.finished_at,
        question=state.question,
        normalized_question=state.normalized_question,
        status=state.status,
        search_tasks=[task.to_dict() for task in state.search_tasks],
        sources=sources,
        answer=state.answer.to_dict() if state.answer else None,
        verification=state.verification.to_dict() if state.verification else None,
        llm_decisions=state.llm_decisions,
        refined_queries=state.refined_queries,
        iterations=state.iterations,
        dry_run=dry_run,
        model=state.answer.model if state.answer else None,
    )


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")
