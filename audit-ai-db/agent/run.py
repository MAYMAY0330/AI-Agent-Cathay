from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.append(str(Path(__file__).resolve().parents[1]))

from agent.state import AgentState
from agent.workflow import run_agent
from ingestion.models import IngestionError
from rag.embedding_client import DEFAULT_EMBEDDING_MODEL
from rag.reranker import DEFAULT_RERANKER_MODEL


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the modular evidence-based audit RAG agent."
    )
    parser.add_argument("question")
    parser.add_argument("--limit", type=int, default=6)
    parser.add_argument("--max-iterations", type=int, default=2)
    parser.add_argument("--document-type")
    parser.add_argument("--source-system")
    parser.add_argument("--language")
    parser.add_argument("--status", default="active")
    parser.add_argument("--vector", action="store_true")
    parser.add_argument(
        "--agentic-search",
        action="store_true",
        help="Enable the small RAG search agent for extra validated search queries.",
    )
    parser.add_argument("--embedding-model", default=DEFAULT_EMBEDDING_MODEL)
    parser.add_argument(
        "--rerank",
        action="store_true",
        help="Rerank the hybrid candidate pool with a local BGE reranker.",
    )
    parser.add_argument("--reranker-model", default=DEFAULT_RERANKER_MODEL)
    parser.add_argument("--rerank-candidates", type=int, default=30)
    parser.add_argument("--max-context-chars", type=int, default=12000)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--no-llm-decisions",
        action="store_true",
        help="Disable Gemini planner/evidence judge and use deterministic decisions.",
    )
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--log-dir",
        type=Path,
        default=Path("data/processed/agent_runs"),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        state = run_agent(
            args.question,
            limit=args.limit,
            max_iterations=args.max_iterations,
            document_type=args.document_type,
            source_system=args.source_system,
            language=args.language,
            status=args.status,
            include_vector=args.vector,
            include_agentic_search=args.agentic_search,
            embedding_model=args.embedding_model,
            dry_run=args.dry_run,
            llm_decisions=not args.no_llm_decisions,
            log_dir=args.log_dir,
            max_context_chars=args.max_context_chars,
            rerank=args.rerank,
            reranker_model=args.reranker_model,
            rerank_candidates=args.rerank_candidates,
        )
    except IngestionError as exc:
        print(f"FAILED stage={exc.stage} error={exc.message}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"FAILED stage=agent_run error={exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(_json_payload(state, include_prompt=args.dry_run), ensure_ascii=False, indent=2))
        return 0

    _print_human_output(state, include_prompt=args.dry_run)
    return 0


def _json_payload(state: AgentState, *, include_prompt: bool) -> dict:
    payload = state.to_dict(include_prompt=include_prompt)
    payload["answer_detail"] = payload.pop("answer", None)
    payload["answer"] = state.answer.answer if state.answer else ""
    payload["citations"] = state.answer.citations if state.answer else []
    if state.evidence_bundle:
        payload["sources"] = [asdict(source) for source in state.evidence_bundle.sources]
    return payload


def _print_human_output(state: AgentState, *, include_prompt: bool) -> None:
    if state.status == "dry_run":
        print("AGENT_DRY_RUN")
    else:
        print("AGENT_RESULT")
    print(f"status={state.status}")
    print(f"run_id={state.run_id}")
    if state.log_path:
        print(f"log_path={state.log_path}")
    print("")

    print("答覆：")
    print(state.answer.answer if state.answer else "")
    print("")

    print("檢索任務：")
    for task in state.search_tasks:
        print(f"- {task.task_id}: {task.query} ({task.purpose})")
    print("")

    print("支持來源：")
    sources = state.evidence_bundle.sources if state.evidence_bundle else []
    if not sources:
        print("-")
    for source in sources:
        print(
            f"[{source.label}] {source.title} / "
            f"{source.section_title or source.heading_path or '-'} / "
            f"{source.clause_number or '-'} / "
            f"page={_format_page_range(source.page_start, source.page_end)} / "
            f"chunk_id={source.chunk_id}"
        )

    if state.evidence_judgments:
        print("")
        print("證據評分：")
        for judgment in state.evidence_judgments:
            checklist = ", ".join(
                f"{key}={value}" for key, value in judgment.checklist.items()
            )
            print(
                f"[{judgment.label}] {judgment.score}/{judgment.max_score} "
                f"{judgment.classification} mode={judgment.mode}"
            )
            print(f"  checklist: {checklist}")
            if judgment.supporting_quote:
                print(f"  quote: {judgment.supporting_quote}")
            print(f"  reason: {judgment.reason}")

    if state.verification:
        print("")
        print("驗證：")
        print(f"valid={state.verification.valid}")
        if state.verification.cited_labels:
            print(f"cited_labels={','.join(state.verification.cited_labels)}")
        if state.verification.errors:
            print(f"errors={','.join(state.verification.errors)}")
        if state.verification.reason:
            print(f"reason={state.verification.reason}")

    if include_prompt and state.rag_context is not None:
        print("")
        print("RAG_CONTEXT_PREVIEW")
        print(state.rag_context.prompt)


def _format_page_range(page_start: int | None, page_end: int | None) -> str:
    if page_start is None and page_end is None:
        return "-"
    if page_start == page_end or page_end is None:
        return str(page_start)
    if page_start is None:
        return str(page_end)
    return f"{page_start}-{page_end}"


if __name__ == "__main__":
    raise SystemExit(main())
