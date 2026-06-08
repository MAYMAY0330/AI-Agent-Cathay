from __future__ import annotations

import argparse
import csv
import hashlib
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.append(str(Path(__file__).resolve().parents[1]))

from ingestion.models import IngestionError
from ingestion.hybrid.pipeline import run_hybrid_ingestion


SUPPORTED_EXTENSIONS = {".docx", ".pdf"}
UNSUPPORTED_EXTENSIONS = {".xlsx", ".xls", ".csv", ".pptx", ".txt", ".html"}


@dataclass(frozen=True)
class BatchResult:
    file_path: Path
    status: str
    stage: str | None = None
    document_type: str | None = None
    internal_code: str | None = None
    selected_strategy: str | None = None
    total_chunks: int = 0
    error_message: str | None = None


def infer_document_type(file_path: Path) -> str:
    name = file_path.stem

    legal_keywords = [
        "適法性",
        "個資法",
        "法務",
        "疑義",
        "法之虞",
        "意見",
    ]
    manual_keywords = [
        "使用說明",
        "操作",
        "平台",
        "系統",
        "工具",
        "申請",
        "Hadoop",
        "R語言",
    ]

    if any(keyword in name for keyword in legal_keywords):
        return "legal_opinion"
    if any(keyword in name for keyword in manual_keywords):
        return "system_manual"
    return "internal_rule"


def build_internal_code(file_path: Path, prefix: str) -> str:
    digest = hashlib.sha1(file_path.stem.encode("utf-8")).hexdigest()[:12].upper()
    return f"{prefix}-{digest}"


def discover_files(folder: Path) -> list[Path]:
    return sorted(
        path for path in folder.iterdir() if path.is_file() and not path.name.startswith(".")
    )


def build_metadata(
    file_path: Path,
    *,
    source_system: str,
    language: str,
    internal_code_prefix: str,
) -> dict[str, Any]:
    document_type = infer_document_type(file_path)
    return {
        "file_path": str(file_path),
        "internal_code": build_internal_code(file_path, internal_code_prefix),
        "document_type": document_type,
        "title": file_path.stem,
        "source_system": source_system,
        "language": language,
        "source_record_id": file_path.stem,
    }


def run_folder_ingestion(
    folder_path: str,
    *,
    source_system: str,
    language: str,
    internal_code_prefix: str,
    strategy: str = "auto",
    output_dir: str = "data/processed/hybrid_pipeline",
    vision_mode: str = "minimal",
    max_vision_pages: int | None = None,
    no_db: bool = False,
    dry_run: bool = False,
) -> list[BatchResult]:
    folder = Path(folder_path).expanduser().resolve()
    if not folder.exists():
        raise IngestionError("folder_loading", f"folder does not exist: {folder}")
    if not folder.is_dir():
        raise IngestionError("folder_loading", f"path is not a folder: {folder}")

    results: list[BatchResult] = []
    for file_path in discover_files(folder):
        extension = file_path.suffix.lower()
        if extension not in SUPPORTED_EXTENSIONS:
            status = "skipped_unsupported"
            message = (
                f"unsupported file extension: {extension}"
                if extension in UNSUPPORTED_EXTENSIONS or extension
                else "file has no extension"
            )
            results.append(
                BatchResult(
                    file_path=file_path,
                    status=status,
                    stage="file_discovery",
                    error_message=message,
                )
            )
            continue

        metadata = build_metadata(
            file_path,
            source_system=source_system,
            language=language,
            internal_code_prefix=internal_code_prefix,
        )

        if dry_run:
            results.append(
                BatchResult(
                    file_path=file_path,
                    status="dry_run",
                    stage="file_discovery",
                    document_type=metadata["document_type"],
                    internal_code=metadata["internal_code"],
                )
            )
            continue

        try:
            result = run_hybrid_ingestion(
                metadata,
                strategy=strategy,
                output_dir=output_dir,
                vision_mode=vision_mode,
                max_vision_pages=max_vision_pages,
                no_db=no_db,
            )
            results.append(
                BatchResult(
                    file_path=file_path,
                    status=str(result.get("status")),
                    stage=str(result.get("stage")),
                    document_type=metadata["document_type"],
                    internal_code=metadata["internal_code"],
                    selected_strategy=str(result.get("selected_strategy") or ""),
                    total_chunks=int(result.get("total_chunks") or 0),
                )
            )
        except IngestionError as exc:
            results.append(
                BatchResult(
                    file_path=file_path,
                    status=exc.status,
                    stage=exc.stage,
                    document_type=metadata["document_type"],
                    internal_code=metadata["internal_code"],
                    error_message=exc.message,
                )
            )

    return results


def print_results(results: list[BatchResult]) -> None:
    counts: dict[str, int] = {}
    for result in results:
        counts[result.status] = counts.get(result.status, 0) + 1
        detail = [
            f"status={result.status}",
            f"stage={result.stage}",
            f"type={result.document_type or '-'}",
            f"strategy={result.selected_strategy or '-'}",
            f"chunks={result.total_chunks}",
            f"file={result.file_path.name}",
        ]
        if result.error_message:
            detail.append(f"error={result.error_message}")
        print("FILE_RESULT " + " ".join(detail))

    print("")
    print("BATCH_SUMMARY")
    print(f"total_files={len(results)}")
    for status in sorted(counts):
        print(f"{status}={counts[status]}")


def write_report(results: list[BatchResult], report_path: str) -> Path:
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
                "total_chunks",
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
                    "selected_strategy": result.selected_strategy or "",
                    "total_chunks": result.total_chunks,
                    "error_message": result.error_message or "",
                }
            )

    return path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Ingest every supported PDF/DOCX file in a folder."
    )
    parser.add_argument(
        "folder",
        nargs="?",
        default="data/raw",
        help="Folder containing local .pdf and .docx files. Default: data/raw",
    )
    parser.add_argument("--source-system", default="folder_test")
    parser.add_argument("--language", default="zh-TW")
    parser.add_argument("--internal-code-prefix", default="BATCH")
    parser.add_argument(
        "--strategy",
        choices=["auto", "local", "gemini"],
        default="auto",
        help="Hybrid strategy for supported files. Default: auto",
    )
    parser.add_argument(
        "--output-dir",
        default="data/processed/hybrid_pipeline",
        help="Where hybrid/Gemini artifacts are written.",
    )
    parser.add_argument(
        "--vision-mode",
        choices=["minimal", "full", "off"],
        default="minimal",
        help="Gemini PDF Vision routing when hybrid selects Gemini.",
    )
    parser.add_argument(
        "--max-vision-pages-per-file",
        type=int,
        help="Skip a PDF if more than this many pages would need Gemini Vision.",
    )
    parser.add_argument(
        "--no-db",
        action="store_true",
        help="Parse/chunk supported files without writing PostgreSQL.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List files and inferred metadata without writing to the database.",
    )
    parser.add_argument(
        "--report-path",
        default="data/processed/ingestion_report.csv",
        help="CSV report output path. Default: data/processed/ingestion_report.csv",
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
        results = run_folder_ingestion(
            args.folder,
            source_system=args.source_system,
            language=args.language,
            internal_code_prefix=args.internal_code_prefix,
            strategy=args.strategy,
            output_dir=args.output_dir,
            vision_mode=args.vision_mode,
            max_vision_pages=args.max_vision_pages_per_file,
            no_db=args.no_db,
            dry_run=args.dry_run,
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


if __name__ == "__main__":
    raise SystemExit(main())
