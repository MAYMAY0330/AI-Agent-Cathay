from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from agent.state import AgentAnswer, AgentRunLog, AgentState, VerificationResult
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
    embedding_model: str | None = DEFAULT_EMBEDDING_MODEL,
    dry_run: bool = False,
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
            embedding_model=embedding_model,
            dry_run=dry_run,
            log_dir=log_dir,
        )

        normalized = registry.call_tool("normalize_question", {"question": question})
        state.normalized_question = normalized["normalized_question"]
        state.keywords = normalized["keywords"]
        state.inferred_filters = normalized["filters"]

        base_filters = {
            **state.inferred_filters,
            "document_type": document_type,
            "source_system": source_system,
            "language": language,
            "status": status,
        }
        base_filters = {key: value for key, value in base_filters.items() if value}

        sufficiency = VerificationResult(valid=False, reason="No search attempted.")
        for iteration in range(1, max(1, max_iterations) + 1):
            state.iterations = iteration
            tasks = registry.call_tool(
                "plan_search_tasks",
                {
                    "normalized_question": state.normalized_question,
                    "keywords": state.keywords,
                    "filters": base_filters,
                    "limit": limit,
                    "iteration": iteration,
                },
            )
            state.search_tasks.extend(tasks)

            for task in tasks:
                results = registry.call_tool("retrieve_evidence", {"task": task})
                state.retrieved_results.extend(results)

            bundle = registry.call_tool(
                "select_evidence",
                {
                    "question": state.normalized_question,
                    "results": state.retrieved_results,
                    "limit": limit,
                    "max_context_chars": max_context_chars,
                },
            )
            state.evidence_bundle = bundle

            sufficiency = registry.call_tool(
                "check_evidence_sufficiency",
                {"bundle": bundle},
            )
            if sufficiency.valid:
                break

        state.verification = sufficiency
        if state.evidence_bundle is not None and sufficiency.valid:
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
            state.answer = registry.call_tool(
                "generate_cited_answer",
                {
                    "dry_run": dry_run,
                    "insufficient_reason": sufficiency.reason or "Insufficient evidence.",
                },
            )

        sources = state.evidence_bundle.sources if state.evidence_bundle else []
        state.verification = registry.call_tool(
            "verify_citations",
            {
                "answer": state.answer,
                "sources": sources,
            },
        )
        state.status = _final_status(state.answer, state.verification)
        state.finished_at = _now_iso()

        log = _build_run_log(state, dry_run=dry_run)
        log_path = registry.call_tool("log_agent_run", {"log": log})
        state.log_path = str(log_path)
        return state
    finally:
        conn.close()


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
        iterations=state.iterations,
        dry_run=dry_run,
        model=state.answer.model if state.answer else None,
    )


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")
