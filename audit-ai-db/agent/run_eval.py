from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.append(str(Path(__file__).resolve().parents[1]))

from agent.state import AgentState
from agent.workflow import run_agent
from ingestion.models import IngestionError
from rag.embedding_client import DEFAULT_EMBEDDING_MODEL
from rag.reranker import DEFAULT_RERANKER_MODEL


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Batch-evaluate the modular RAG agent against local question cases."
    )
    parser.add_argument("eval_path", type=Path)
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
    parser.add_argument("--rerank", action="store_true")
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
        cases = _load_cases(args.eval_path)
    except ValueError as exc:
        print(f"FAILED stage=agent_eval_config error={exc}", file=sys.stderr)
        return 2

    results: list[dict[str, Any]] = []
    for index, case in enumerate(cases, start=1):
        try:
            state = run_agent(
                case["question"],
                limit=int(case.get("limit") or args.limit),
                max_iterations=args.max_iterations,
                document_type=case.get("document_type") or args.document_type,
                source_system=case.get("source_system") or args.source_system,
                language=case.get("language") or args.language,
                status=case.get("status") or args.status,
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
            result = _evaluate_case(index, case, state)
        except IngestionError as exc:
            result = _failed_case(index, case, f"{exc.stage}: {exc.message}")
        except Exception as exc:
            result = _failed_case(index, case, f"agent_eval: {exc}")
        results.append(result)

    summary = _summary(results)
    payload = {"summary": summary, "results": results}
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        _print_human(payload)
    return 0 if summary["failed"] == 0 else 1


def _load_cases(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise ValueError(f"eval file does not exist: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("eval file root must be a JSON array")

    cases: list[dict[str, Any]] = []
    for index, item in enumerate(data, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"case {index} must be an object")
        question = item.get("question")
        if not isinstance(question, str) or not question.strip():
            raise ValueError(f"case {index} missing non-empty question")
        cases.append(item)
    return cases


def _evaluate_case(index: int, case: dict[str, Any], state: AgentState) -> dict[str, Any]:
    sources = state.evidence_bundle.sources if state.evidence_bundle else []
    source_text = "\n".join(source.text for source in sources)
    source_sections = [
        source.section_title or source.heading_path or ""
        for source in sources
    ]
    source_titles = [source.title for source in sources]
    source_chunk_ids = [source.chunk_id for source in sources]

    checks: list[dict[str, Any]] = []
    checks.append(_check("has_sources", bool(sources), f"{len(sources)} source(s)"))
    checks.append(_check("agent_status", state.status in {"dry_run", "answered"}, state.status))

    checks.extend(
        _contains_checks("expected_phrases", case, source_text)
    )
    checks.extend(
        _contains_any_checks("expected_sections", case, source_sections)
    )
    checks.extend(
        _contains_any_checks("expected_titles", case, source_titles)
    )
    checks.extend(
        _contains_any_checks("expected_chunk_ids", case, source_chunk_ids)
    )

    passed = all(check["passed"] for check in checks)
    return {
        "index": case.get("index", index),
        "question": case["question"],
        "passed": passed,
        "status": state.status,
        "checks": checks,
        "sources": [
            {
                "label": source.label,
                "title": source.title,
                "section": source.section_title or source.heading_path or "-",
                "clause": source.clause_number or "-",
                "chunk_id": source.chunk_id,
                "score": source.score,
            }
            for source in sources
        ],
        "log_path": state.log_path,
        "answer": asdict(state.answer) if state.answer else None,
    }


def _failed_case(index: int, case: dict[str, Any], error: str) -> dict[str, Any]:
    return {
        "index": case.get("index", index),
        "question": case.get("question", ""),
        "passed": False,
        "status": "error",
        "checks": [_check("agent_error", False, error)],
        "sources": [],
        "log_path": None,
        "answer": None,
    }


def _contains_checks(
    key: str,
    case: dict[str, Any],
    haystack: str,
) -> list[dict[str, Any]]:
    expected = _string_list(case.get(key))
    return [
        _check(key, value in haystack, value)
        for value in expected
    ]


def _contains_any_checks(
    key: str,
    case: dict[str, Any],
    values: list[str],
) -> list[dict[str, Any]]:
    expected = _string_list(case.get(key))
    return [
        _check(
            key,
            any(expected_value in value for value in values),
            expected_value,
        )
        for expected_value in expected
    ]


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    return []


def _check(name: str, passed: bool, detail: str) -> dict[str, Any]:
    return {"name": name, "passed": passed, "detail": detail}


def _summary(results: list[dict[str, Any]]) -> dict[str, int]:
    passed = sum(1 for result in results if result["passed"])
    total = len(results)
    return {
        "total": total,
        "passed": passed,
        "failed": total - passed,
    }


def _print_human(payload: dict[str, Any]) -> None:
    summary = payload["summary"]
    print(
        "AGENT_EVAL "
        f"total={summary['total']} passed={summary['passed']} failed={summary['failed']}"
    )
    for result in payload["results"]:
        mark = "PASS" if result["passed"] else "FAIL"
        print("")
        print(f"[{mark}] case={result['index']} status={result['status']}")
        print(f"question={result['question']}")
        failed_checks = [check for check in result["checks"] if not check["passed"]]
        if failed_checks:
            print("failed_checks=" + "; ".join(
                f"{check['name']}:{check['detail']}" for check in failed_checks
            ))
        print("sources=")
        for source in result["sources"][:6]:
            print(
                f"  [{source['label']}] {source['title']} / {source['section']} / "
                f"{source['clause']} / chunk_id={source['chunk_id']}"
            )
        if result.get("log_path"):
            print(f"log_path={result['log_path']}")


if __name__ == "__main__":
    raise SystemExit(main())
