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
from rag.embedding_client import DEFAULT_EMBEDDING_MODEL
from rag.hybrid_search import hybrid_search
from rag.search_models import SearchFilters, SearchResult


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Search imported audit knowledge-base chunks."
    )
    parser.add_argument("query", help="Question or search text")
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--document-type")
    parser.add_argument("--source-system")
    parser.add_argument("--language")
    parser.add_argument("--status", default="active")
    parser.add_argument(
        "--all-statuses",
        action="store_true",
        help="Search documents regardless of status.",
    )
    parser.add_argument(
        "--keyword-only",
        action="store_true",
        help="Use chunk keyword/full-text search only.",
    )
    parser.add_argument(
        "--metadata-only",
        action="store_true",
        help="Use document metadata search only.",
    )
    parser.add_argument(
        "--vector",
        action="store_true",
        help="Include vector similarity search in the hybrid result set.",
    )
    parser.add_argument(
        "--agentic",
        action="store_true",
        help="Ask the small search agent to add validated expansion queries.",
    )
    parser.add_argument(
        "--max-agentic-queries",
        type=int,
        default=3,
        help="Maximum extra queries from the small search agent. Default: 3",
    )
    parser.add_argument(
        "--vector-only",
        action="store_true",
        help="Use vector similarity search only.",
    )
    parser.add_argument("--embedding-model", default=DEFAULT_EMBEDDING_MODEL)
    parser.add_argument("--json", action="store_true", help="Print JSON output.")
    parser.add_argument("--preview-chars", type=int, default=360)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    exclusive_modes = [args.keyword_only, args.metadata_only, args.vector_only]
    if sum(bool(mode) for mode in exclusive_modes) > 1:
        print(
            "FAILED: choose only one of --keyword-only, --metadata-only, or --vector-only",
            file=sys.stderr,
        )
        return 2

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
            args.query,
            limit=args.limit,
            filters=filters,
            include_keyword=not args.metadata_only and not args.vector_only,
            include_metadata=not args.keyword_only and not args.vector_only,
            include_vector=args.vector or args.vector_only,
            include_agentic=args.agentic,
            embedding_model=args.embedding_model,
            max_agentic_queries=args.max_agentic_queries,
        )
    except IngestionError as exc:
        print(f"FAILED stage={exc.stage} error={exc.message}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"FAILED stage=rag_search error={exc}", file=sys.stderr)
        return 1
    finally:
        if conn is not None:
            conn.close()

    if args.json:
        print(json.dumps([asdict(result) for result in results], ensure_ascii=False, indent=2))
        return 0

    print_results(results, preview_chars=args.preview_chars)
    return 0


def print_results(results: list[SearchResult], *, preview_chars: int) -> None:
    print(f"SEARCH_RESULTS total={len(results)}")
    for index, result in enumerate(results, start=1):
        page_range = _format_page_range(result.page_start, result.page_end)
        preview = _preview(result.chunk_text, preview_chars)
        print("")
        print(
            f"[{index}] score={result.score:.4f} "
            f"sources={','.join(result.match_sources)}"
        )
        print(f"title={result.title}")
        print(
            f"document_type={result.document_type} "
            f"internal_code={result.internal_code or '-'}"
        )
        print(
            f"section={result.section_title or result.heading_path or '-'} "
            f"clause={result.clause_number or '-'} page={page_range}"
        )
        print(f"chunk_id={result.chunk_id}")
        print(f"preview={preview}")


def _format_page_range(page_start: int | None, page_end: int | None) -> str:
    if page_start is None and page_end is None:
        return "-"
    if page_start == page_end or page_end is None:
        return str(page_start)
    if page_start is None:
        return str(page_end)
    return f"{page_start}-{page_end}"


def _preview(text: str, limit: int) -> str:
    clean = " ".join(text.split())
    if len(clean) <= limit:
        return clean
    return clean[: max(0, limit - 3)] + "..."


if __name__ == "__main__":
    raise SystemExit(main())
