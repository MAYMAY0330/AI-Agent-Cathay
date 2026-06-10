from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.append(str(Path(__file__).resolve().parents[2]))

from ingestion.hybrid.pipeline import run_hybrid_ingestion
from ingestion.models import IngestionError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Ingest one local PDF/DOCX through the hybrid local/Gemini pipeline."
        )
    )
    parser.add_argument("file_path", help="Local .pdf or .docx file path")
    parser.add_argument(
        "--strategy",
        choices=["auto", "local", "gemini"],
        default="auto",
        help="Parsing strategy. auto chooses local for text-rich files and Gemini for image-heavy PDFs.",
    )
    parser.add_argument(
        "--parent-chunker",
        choices=["rules", "gemini"],
        default="rules",
        help=(
            "Parent chunk boundary method after Markdown parsing. "
            "rules is deterministic; gemini asks Gemini to choose semantic parent sections."
        ),
    )
    parser.add_argument("--internal-code")
    parser.add_argument("--document-type", default="other")
    parser.add_argument("--language", default="zh-TW")
    parser.add_argument("--data-type")
    parser.add_argument("--title")
    parser.add_argument("--source-url")
    parser.add_argument("--source-system", default="hybrid_ingestion")
    parser.add_argument("--source-record-id")
    parser.add_argument("--responsible-unit")
    parser.add_argument("--issuing-unit")
    parser.add_argument("--effective-date")
    parser.add_argument("--effective-year", type=int)
    parser.add_argument("--revision-date")
    parser.add_argument("--document-family")
    parser.add_argument("--normalized-version-label")
    parser.add_argument("--system-category")
    parser.add_argument("--status", default="active")
    parser.add_argument("--short-summary")
    parser.add_argument(
        "--keywords",
        help="Comma-separated keywords. If omitted, the selected path will infer keywords.",
    )
    parser.add_argument(
        "--main-topics",
        help="Comma-separated topic tags. If omitted, document metadata is used.",
    )
    parser.add_argument(
        "--output-dir",
        default="data/processed/hybrid_pipeline",
        help="Where Gemini Markdown, page analysis, chunks JSON, and token usage files are written.",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        help="Only parse first N PDF pages. Requires --no-db and the Gemini path.",
    )
    parser.add_argument(
        "--vision-mode",
        choices=["minimal", "full", "off"],
        default="minimal",
        help=(
            "PDF Vision routing for Gemini. minimal sends only image-only pages; "
            "full also sends mixed text+image pages; off never sends PDF pages to Gemini."
        ),
    )
    parser.add_argument(
        "--max-vision-pages-per-file",
        type=int,
        help="Skip a PDF if more than this many pages would need Gemini Vision.",
    )
    parser.add_argument(
        "--no-db",
        action="store_true",
        help="Parse/chunk only; do not write PostgreSQL.",
    )
    parser.add_argument(
        "--force-reprocess",
        action="store_true",
        help="Reprocess even when the current stored version has the same file checksum.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the result as JSON.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    raw_metadata = vars(args)
    strategy = raw_metadata.pop("strategy")
    parent_chunker = raw_metadata.pop("parent_chunker")
    output_dir = raw_metadata.pop("output_dir")
    max_pages = raw_metadata.pop("max_pages")
    vision_mode = raw_metadata.pop("vision_mode")
    max_vision_pages = raw_metadata.pop("max_vision_pages_per_file")
    no_db = raw_metadata.pop("no_db")
    force_reprocess = raw_metadata.pop("force_reprocess")
    json_output = raw_metadata.pop("json")

    try:
        result = run_hybrid_ingestion(
            raw_metadata,
            strategy=strategy,
            parent_chunker=parent_chunker,
            output_dir=output_dir,
            max_pages=max_pages,
            vision_mode=vision_mode,
            max_vision_pages=max_vision_pages,
            no_db=no_db,
            force_reprocess=force_reprocess,
        )
    except IngestionError as exc:
        print(f"FAILED stage={exc.stage} error={exc.message}", file=sys.stderr)
        return 1

    if json_output:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(
            "HYBRID_INGESTION_RESULT "
            + " ".join(f"{key}={_format_value(value)}" for key, value in result.items())
        )
    return 0


def _format_value(value: Any) -> str:
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    text = str(value)
    if any(char.isspace() for char in text):
        return json.dumps(text, ensure_ascii=False)
    return text


if __name__ == "__main__":
    raise SystemExit(main())
