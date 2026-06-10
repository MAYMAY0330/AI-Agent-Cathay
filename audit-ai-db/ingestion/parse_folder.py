from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.append(str(Path(__file__).resolve().parents[1]))

from ingestion.file_loader import load_file
from ingestion.hybrid.chunkers import output_name_for_metadata
from ingestion.hybrid.readers import read_gemini_document, read_local_document
from ingestion.hybrid.strategies import choose_ingestion_strategy
from ingestion.metadata_extractor import enrich_metadata_from_markdown, prepare_metadata
from ingestion.models import IngestionError
from ingestion.run_folder import (
    SUPPORTED_EXTENSIONS,
    build_metadata,
    discover_files,
)


@dataclass(frozen=True)
class ParseResult:
    file_path: Path
    status: str
    stage: str
    internal_code: str | None = None
    document_type: str | None = None
    selected_strategy: str | None = None
    markdown_path: str | None = None
    manifest_path: str | None = None
    markdown_chars: int = 0
    parse_ms: int = 0
    error_message: str | None = None


def run_parse_folder(
    folder_path: str,
    *,
    source_system: str,
    language: str,
    internal_code_prefix: str,
    strategy: str,
    output_dir: str,
    vision_mode: str,
    max_vision_pages: int | None,
    only_missing: bool,
) -> list[ParseResult]:
    folder = Path(folder_path).expanduser().resolve()
    if not folder.exists():
        raise IngestionError("folder_loading", f"folder does not exist: {folder}")
    if not folder.is_dir():
        raise IngestionError("folder_loading", f"path is not a folder: {folder}")

    output_root = Path(output_dir).expanduser().resolve()
    manifest_dir = output_root / "manifest"
    manifest_dir.mkdir(parents=True, exist_ok=True)

    results: list[ParseResult] = []
    for file_path in discover_files(folder):
        started = time.perf_counter()
        extension = file_path.suffix.lower()
        if extension not in SUPPORTED_EXTENSIONS:
            results.append(
                ParseResult(
                    file_path=file_path,
                    status="skipped_unsupported",
                    stage="file_discovery",
                    error_message=f"unsupported file extension: {extension or '(none)'}",
                )
            )
            continue
        if extension == ".pdf" and file_path.with_suffix(".docx").exists():
            results.append(
                ParseResult(
                    file_path=file_path,
                    status="skipped_duplicate_source",
                    stage="file_discovery",
                    error_message="same-title DOCX exists; using DOCX Markdown for this document",
                )
            )
            continue

        raw_metadata = build_metadata(
            file_path,
            source_system=source_system,
            language=language,
            internal_code_prefix=internal_code_prefix,
        )
        file_info = load_file(file_path)
        metadata = prepare_metadata(file_info, raw_metadata)
        output_name = output_name_for_metadata(metadata)
        manifest_path = manifest_dir / f"{output_name}.json"

        if only_missing and manifest_path.exists():
            cached = json.loads(manifest_path.read_text(encoding="utf-8"))
            results.append(
                ParseResult(
                    file_path=file_path,
                    status="skipped_cached",
                    stage="cache_check",
                    internal_code=metadata.internal_code,
                    document_type=metadata.document_type,
                    selected_strategy=cached.get("selected_strategy"),
                    markdown_path=cached.get("markdown_path"),
                    manifest_path=str(manifest_path),
                    markdown_chars=int(cached.get("markdown_chars") or 0),
                    parse_ms=0,
                )
            )
            continue

        try:
            decision = choose_ingestion_strategy(file_info, strategy)
            if decision.selected_strategy == "gemini":
                read_result = read_gemini_document(
                    file_info,
                    output_root,
                    max_pages=None,
                    vision_mode=vision_mode,
                    max_vision_pages=max_vision_pages,
                    output_name=output_name,
                )
                markdown = read_result.markdown
                parse_engine = "gemini"
                table_repair_status = "not_applicable"
                page_analysis = [
                    {
                        "page": page.page,
                        "text_chars": page.text_chars,
                        "image_count": page.image_count,
                        "route": page.route,
                        "text_preview": page.text_preview,
                    }
                    for page in read_result.page_analysis
                ]
            else:
                read_result = read_local_document(
                    file_info,
                    metadata,
                    output_root,
                    output_name=output_name,
                )
                markdown = read_result.markdown
                parse_engine = read_result.parse_engine
                table_repair_status = read_result.table_repair_status
                page_analysis = decision.analysis

            enriched = enrich_metadata_from_markdown(metadata, markdown)
            payload: dict[str, Any] = {
                "file_path": str(file_path),
                "markdown_path": str(read_result.output_markdown_path),
                "internal_code": enriched.internal_code,
                "title": enriched.title,
                "document_type": enriched.document_type,
                "source_system": enriched.source_system,
                "source_record_id": enriched.source_record_id,
                "language": enriched.language,
                "selected_strategy": decision.selected_strategy,
                "strategy_reason": decision.reason,
                "parse_engine": parse_engine,
                "table_repair_status": table_repair_status,
                "markdown_chars": len(markdown),
                "page_analysis": page_analysis,
                "metadata": enriched.document_values(),
            }
            manifest_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2, default=str),
                encoding="utf-8",
            )
            results.append(
                ParseResult(
                    file_path=file_path,
                    status="success",
                    stage="markdown_cached",
                    internal_code=enriched.internal_code,
                    document_type=enriched.document_type,
                    selected_strategy=decision.selected_strategy,
                    markdown_path=str(read_result.output_markdown_path),
                    manifest_path=str(manifest_path),
                    markdown_chars=len(markdown),
                    parse_ms=int((time.perf_counter() - started) * 1000),
                )
            )
        except IngestionError as exc:
            results.append(
                ParseResult(
                    file_path=file_path,
                    status=exc.status,
                    stage=exc.stage,
                    internal_code=metadata.internal_code,
                    document_type=metadata.document_type,
                    parse_ms=int((time.perf_counter() - started) * 1000),
                    error_message=exc.message,
                )
            )
        except Exception as exc:
            results.append(
                ParseResult(
                    file_path=file_path,
                    status="failed",
                    stage="parsing",
                    internal_code=metadata.internal_code,
                    document_type=metadata.document_type,
                    parse_ms=int((time.perf_counter() - started) * 1000),
                    error_message=str(exc),
                )
            )
    return results


def print_results(results: list[ParseResult]) -> None:
    counts: dict[str, int] = {}
    for result in results:
        counts[result.status] = counts.get(result.status, 0) + 1
        detail = [
            f"status={result.status}",
            f"stage={result.stage}",
            f"type={result.document_type or '-'}",
            f"strategy={result.selected_strategy or '-'}",
            f"chars={result.markdown_chars}",
            f"ms={result.parse_ms}",
            f"file={result.file_path.name}",
        ]
        if result.error_message:
            detail.append(f"error={result.error_message}")
        print("PARSE_RESULT " + " ".join(detail))
    print("")
    print("PARSE_SUMMARY")
    print(f"total_files={len(results)}")
    for status in sorted(counts):
        print(f"{status}={counts[status]}")


def write_report(results: list[ParseResult], report_path: str) -> Path:
    path = Path(report_path).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=[
                "file_name",
                "file_path",
                "status",
                "stage",
                "document_type",
                "internal_code",
                "selected_strategy",
                "markdown_chars",
                "parse_ms",
                "markdown_path",
                "manifest_path",
                "error_message",
            ],
        )
        writer.writeheader()
        for result in results:
            writer.writerow(
                {
                    "file_name": result.file_path.name,
                    "file_path": str(result.file_path),
                    "status": result.status,
                    "stage": result.stage,
                    "document_type": result.document_type or "",
                    "internal_code": result.internal_code or "",
                    "selected_strategy": result.selected_strategy or "",
                    "markdown_chars": result.markdown_chars,
                    "parse_ms": result.parse_ms,
                    "markdown_path": result.markdown_path or "",
                    "manifest_path": result.manifest_path or "",
                    "error_message": result.error_message or "",
                }
            )
    return path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Parse a document folder into a resumable Markdown cache without DB writes."
    )
    parser.add_argument("folder", help="Folder containing local .pdf and .docx files")
    parser.add_argument("--source-system", default="folder_test")
    parser.add_argument("--language", default="zh-TW")
    parser.add_argument("--internal-code-prefix", default="BATCH")
    parser.add_argument("--strategy", choices=["auto", "local", "gemini"], default="auto")
    parser.add_argument("--output-dir", default="data/processed/markdown_cache")
    parser.add_argument("--vision-mode", choices=["minimal", "full", "off"], default="minimal")
    parser.add_argument("--max-vision-pages-per-file", type=int)
    parser.add_argument(
        "--only-missing",
        action="store_true",
        help="Skip files that already have a manifest in the Markdown cache.",
    )
    parser.add_argument(
        "--report-path",
        default="data/processed/parse_report.csv",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        results = run_parse_folder(
            args.folder,
            source_system=args.source_system,
            language=args.language,
            internal_code_prefix=args.internal_code_prefix,
            strategy=args.strategy,
            output_dir=args.output_dir,
            vision_mode=args.vision_mode,
            max_vision_pages=args.max_vision_pages_per_file,
            only_missing=args.only_missing,
        )
    except IngestionError as exc:
        print(f"FAILED stage={exc.stage} error={exc.message}", file=sys.stderr)
        return 1
    print_results(results)
    report_path = write_report(results, args.report_path)
    print(f"report_path={report_path}")
    return 1 if any(result.status == "failed" for result in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
