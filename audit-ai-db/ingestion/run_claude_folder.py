from __future__ import annotations

import argparse
import csv
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.append(str(Path(__file__).resolve().parents[1]))

from ingestion.models import IngestionError
from ingestion.run_claude_ingestion import run_claude_ingestion
from ingestion.run_folder import (
    SUPPORTED_EXTENSIONS,
    UNSUPPORTED_EXTENSIONS,
    build_metadata,
    discover_files,
)


@dataclass(frozen=True)
class ClaudeBatchResult:
    file_path: Path
    status: str
    stage: str | None = None
    document_type: str | None = None
    internal_code: str | None = None
    total_chunks: int = 0
    claude_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    markdown_path: str | None = None
    chunks_path: str | None = None
    usage_path: str | None = None
    error_message: str | None = None


def run_claude_folder_ingestion(
    folder_path: str,
    *,
    source_system: str,
    language: str,
    internal_code_prefix: str,
    output_dir: str,
    no_db: bool,
    max_pages: int | None,
    vision_mode: str,
    max_vision_pages: int | None,
    limit: int | None,
    dry_run: bool,
    prefer_docx: bool,
) -> list[ClaudeBatchResult]:
    if max_pages is not None and not no_db:
        raise IngestionError(
            "claude_configuration",
            "--max-pages can only be used with --no-db to avoid partial database ingestion",
        )

    folder = Path(folder_path).expanduser().resolve()
    if not folder.exists():
        raise IngestionError("folder_loading", f"folder does not exist: {folder}")
    if not folder.is_dir():
        raise IngestionError("folder_loading", f"path is not a folder: {folder}")

    all_files = discover_files(folder)
    docx_stems = {path.stem for path in all_files if path.suffix.lower() == ".docx"}

    results: list[ClaudeBatchResult] = []
    supported_seen = 0
    for file_path in all_files:
        extension = file_path.suffix.lower()
        if extension not in SUPPORTED_EXTENSIONS:
            message = (
                f"unsupported file extension: {extension}"
                if extension in UNSUPPORTED_EXTENSIONS or extension
                else "file has no extension"
            )
            batch_result = ClaudeBatchResult(
                file_path=file_path,
                status="skipped_unsupported",
                stage="file_discovery",
                error_message=message,
            )
            results.append(batch_result)
            print_single_result(batch_result)
            continue

        if prefer_docx and extension == ".pdf" and file_path.stem in docx_stems:
            batch_result = ClaudeBatchResult(
                file_path=file_path,
                status="skipped_duplicate_source",
                stage="file_discovery",
                error_message="matching DOCX exists; skipped PDF duplicate source",
            )
            results.append(batch_result)
            print_single_result(batch_result)
            continue

        supported_seen += 1
        if limit is not None and supported_seen > limit:
            break

        metadata = build_metadata(
            file_path,
            source_system=source_system,
            language=language,
            internal_code_prefix=internal_code_prefix,
        )

        if dry_run:
            batch_result = ClaudeBatchResult(
                file_path=file_path,
                status="dry_run",
                stage="file_discovery",
                document_type=metadata["document_type"],
                internal_code=metadata["internal_code"],
            )
            results.append(batch_result)
            print_single_result(batch_result)
            continue

        try:
            print(
                "CLAUDE_FILE_START "
                f"file={file_path.name} type={metadata['document_type']} "
                f"internal_code={metadata['internal_code']}",
                flush=True,
            )
            result = run_claude_ingestion(
                metadata,
                output_dir=output_dir,
                max_pages=max_pages,
                vision_mode=vision_mode,
                max_vision_pages=max_vision_pages,
                no_db=no_db,
            )
            batch_result = _result_from_run(file_path, metadata, result)
            results.append(batch_result)
            print_single_result(batch_result)
        except IngestionError as exc:
            batch_result = ClaudeBatchResult(
                file_path=file_path,
                status=exc.status,
                stage=exc.stage,
                document_type=metadata["document_type"],
                internal_code=metadata["internal_code"],
                error_message=exc.message,
            )
            results.append(batch_result)
            print_single_result(batch_result)

    return results


def _result_from_run(
    file_path: Path,
    metadata: dict[str, Any],
    result: dict[str, Any],
) -> ClaudeBatchResult:
    return ClaudeBatchResult(
        file_path=file_path,
        status=str(result.get("status")),
        stage=str(result.get("stage")),
        document_type=metadata["document_type"],
        internal_code=metadata["internal_code"],
        total_chunks=int(result.get("total_chunks") or 0),
        claude_calls=int(result.get("claude_calls") or 0),
        input_tokens=int(result.get("input_tokens") or 0),
        output_tokens=int(result.get("output_tokens") or 0),
        total_tokens=int(result.get("total_tokens") or 0),
        markdown_path=_optional_string(result.get("markdown_path")),
        chunks_path=_optional_string(result.get("chunks_path")),
        usage_path=_optional_string(result.get("usage_path")),
    )


def print_results(results: list[ClaudeBatchResult]) -> None:
    counts: dict[str, int] = {}
    total_input_tokens = 0
    total_output_tokens = 0
    total_tokens = 0

    for result in results:
        counts[result.status] = counts.get(result.status, 0) + 1
        total_input_tokens += result.input_tokens
        total_output_tokens += result.output_tokens
        total_tokens += result.total_tokens

    print("")
    print("CLAUDE_BATCH_SUMMARY")
    print(f"total_files={len(results)}")
    for status in sorted(counts):
        print(f"{status}={counts[status]}")
    print(f"input_tokens={total_input_tokens}")
    print(f"output_tokens={total_output_tokens}")
    print(f"total_tokens={total_tokens}")


def print_single_result(result: ClaudeBatchResult) -> None:
    detail = [
        f"status={result.status}",
        f"stage={result.stage}",
        f"type={result.document_type or '-'}",
        f"chunks={result.total_chunks}",
        f"calls={result.claude_calls}",
        f"input_tokens={result.input_tokens}",
        f"output_tokens={result.output_tokens}",
        f"total_tokens={result.total_tokens}",
        f"file={result.file_path.name}",
    ]
    if result.error_message:
        detail.append(f"error={result.error_message}")
    print("CLAUDE_FILE_RESULT " + " ".join(detail), flush=True)


def write_report(results: list[ClaudeBatchResult], report_path: str) -> Path:
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
                "total_chunks",
                "claude_calls",
                "input_tokens",
                "output_tokens",
                "total_tokens",
                "markdown_path",
                "chunks_path",
                "usage_path",
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
                    "stage": result.stage or "",
                    "document_type": result.document_type or "",
                    "internal_code": result.internal_code or "",
                    "total_chunks": result.total_chunks,
                    "claude_calls": result.claude_calls,
                    "input_tokens": result.input_tokens,
                    "output_tokens": result.output_tokens,
                    "total_tokens": result.total_tokens,
                    "markdown_path": result.markdown_path or "",
                    "chunks_path": result.chunks_path or "",
                    "usage_path": result.usage_path or "",
                    "error_message": result.error_message or "",
                }
            )

    return path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run Claude parsing/chunking for every supported PDF/DOCX file in a folder."
    )
    parser.add_argument(
        "folder",
        nargs="?",
        default="data/raw",
        help="Folder containing local .pdf and .docx files. Default: data/raw",
    )
    parser.add_argument("--source-system", default="claude_folder_test")
    parser.add_argument("--language", default="zh-TW")
    parser.add_argument("--internal-code-prefix", default="CLAUDE-BATCH")
    parser.add_argument(
        "--output-dir",
        default="data/processed/claude_pipeline",
        help="Where Markdown, chunk JSON, page analysis, and token usage files are written.",
    )
    parser.add_argument(
        "--no-db",
        action="store_true",
        help="Parse with Claude and write Markdown/JSON only; do not write PostgreSQL.",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        help="Only parse first N PDF pages. Requires --no-db.",
    )
    parser.add_argument(
        "--vision-mode",
        choices=["minimal", "full", "off"],
        default="minimal",
        help=(
            "PDF Vision routing. minimal sends only image-only pages to Claude; "
            "full also sends mixed text+image pages; off never sends PDF pages to Claude."
        ),
    )
    parser.add_argument(
        "--max-vision-pages-per-file",
        type=int,
        default=10,
        help=(
            "Skip a PDF if more than this many pages would need Claude Vision. "
            "Default: 10 for cost-safe folder tests."
        ),
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Only process the first N supported files.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List files and inferred metadata without calling Claude or writing the database.",
    )
    parser.add_argument(
        "--include-pdf-duplicates",
        action="store_true",
        help="Also process PDFs when a DOCX with the same file stem exists.",
    )
    parser.add_argument(
        "--report-path",
        default="data/processed/claude_ingestion_report.csv",
        help="CSV report output path. Default: data/processed/claude_ingestion_report.csv",
    )
    parser.add_argument(
        "--no-report",
        action="store_true",
        help="Do not write a CSV report.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        results = run_claude_folder_ingestion(
            args.folder,
            source_system=args.source_system,
            language=args.language,
            internal_code_prefix=args.internal_code_prefix,
            output_dir=args.output_dir,
            no_db=args.no_db,
            max_pages=args.max_pages,
            vision_mode=args.vision_mode,
            max_vision_pages=args.max_vision_pages_per_file,
            limit=args.limit,
            dry_run=args.dry_run,
            prefer_docx=not args.include_pdf_duplicates,
        )
    except IngestionError as exc:
        print(f"FAILED stage={exc.stage} error={exc.message}", file=sys.stderr)
        return 1

    print_results(results)
    if not args.no_report:
        report_path = write_report(results, args.report_path)
        print(f"report_path={report_path}")

    failed_count = sum(1 for result in results if result.status == "failed")
    return 1 if failed_count else 0


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


if __name__ == "__main__":
    raise SystemExit(main())
