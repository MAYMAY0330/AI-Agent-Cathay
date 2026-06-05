from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.append(str(Path(__file__).resolve().parents[1]))

from ingestion.config import DBConfig
from ingestion.db_writer import connect
from ingestion.models import IngestionError
from rag.answer_generator import generate_answer
from rag.context_builder import build_rag_context
from rag.embedding_client import DEFAULT_EMBEDDING_MODEL
from rag.hybrid_search import hybrid_search
from rag.search_models import SearchFilters


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run retrieval-augmented answering over imported audit knowledge chunks."
    )
    parser.add_argument("question")
    parser.add_argument("--limit", type=int, default=6)
    parser.add_argument("--document-type")
    parser.add_argument("--source-system")
    parser.add_argument("--language")
    parser.add_argument("--status", default="active")
    parser.add_argument("--all-statuses", action="store_true")
    parser.add_argument(
        "--vector",
        action="store_true",
        help="Include vector similarity search. Requires query embeddings to work.",
    )
    parser.add_argument("--embedding-model", default=DEFAULT_EMBEDDING_MODEL)
    parser.add_argument("--max-context-chars", type=int, default=12000)
    parser.add_argument(
        "--no-llm",
        action="store_true",
        help="Print retrieved context and sources without calling Gemini.",
    )
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    filters = SearchFilters(
        document_type=args.document_type,
        status=None if args.all_statuses else args.status,
        source_system=args.source_system,
        language=args.language,
    )

    conn = None
    try:
        conn = connect(DBConfig.from_env())
        results = hybrid_search(
            conn,
            args.question,
            limit=max(args.limit * 3, args.limit),
            filters=filters,
            include_vector=args.vector,
            embedding_model=args.embedding_model,
        )
        context = build_rag_context(
            args.question,
            results,
            max_sources=args.limit,
            max_context_chars=args.max_context_chars,
        )
        answer = None if args.no_llm else generate_answer(context)
    except IngestionError as exc:
        print(f"FAILED stage={exc.stage} error={exc.message}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"FAILED stage=rag_answer error={exc}", file=sys.stderr)
        return 1
    finally:
        if conn is not None:
            conn.close()

    if args.json:
        payload = {
            "question": args.question,
            "answer": asdict(answer) if answer else None,
            "sources": [asdict(source) for source in context.sources],
            "prompt": context.prompt if args.no_llm else None,
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    if args.no_llm:
        print("RAG_CONTEXT_PREVIEW")
        print(context.prompt)
        return 0

    print("RAG_ANSWER")
    print(answer.answer if answer else "")
    print("")
    print("SOURCES")
    for source in context.sources:
        print(
            f"[{source.label}] score={source.score:.4f} "
            f"title={source.title} section={source.section_title or source.heading_path or '-'} "
            f"chunk_id={source.chunk_id}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
