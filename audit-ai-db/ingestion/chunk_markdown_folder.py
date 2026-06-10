from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.append(str(Path(__file__).resolve().parents[1]))

from ingestion import chunker, db_writer, logger, structure_detector
from ingestion.checksum import generate_file_checksum
from ingestion.config import DBConfig
from ingestion.file_loader import load_file
from ingestion.gemini.chunker import chunk_markdown_with_gemini
from ingestion.hybrid.chunkers import output_name_for_metadata, write_token_usage
from ingestion.markdown_blocks import markdown_to_blocks
from ingestion.metadata_extractor import enrich_metadata_from_markdown, prepare_metadata
from ingestion.models import IngestionError, SummaryResult
from ingestion.summary_generator import generate_summary
from ingestion.version_checker import check_version


@dataclass(frozen=True)
class ChunkCacheResult:
    manifest_path: Path
    status: str
    stage: str
    internal_code: str | None = None
    title: str | None = None
    parent_chunker: str | None = None
    total_chunks: int = 0
    deleted_chunks: int = 0
    chunk_ms: int = 0
    error_message: str | None = None


def run_chunk_markdown_folder(
    cache_dir: str,
    *,
    parent_chunker: str,
    clean_existing: bool,
    skip_duplicates: bool,
    limit: int | None,
    workers: int = 1,
) -> list[ChunkCacheResult]:
    cache_root = Path(cache_dir).expanduser().resolve()
    manifest_dir = cache_root / "manifest"
    if not manifest_dir.exists():
        raise IngestionError("markdown_cache", f"manifest folder does not exist: {manifest_dir}")

    parent_chunker = parent_chunker.strip().lower()
    if parent_chunker not in {"rules", "gemini"}:
        raise IngestionError("markdown_cache", "parent_chunker must be one of: rules, gemini")

    manifests = sorted(manifest_dir.glob("*.json"))
    if limit is not None:
        manifests = manifests[:limit]

    workers = max(1, workers)
    if workers > 1:
        return _run_chunk_markdown_folder_parallel(
            manifests,
            parent_chunker=parent_chunker,
            clean_existing=clean_existing,
            skip_duplicates=skip_duplicates,
            workers=workers,
        )

    results: list[ChunkCacheResult] = []
    conn = db_writer.connect(DBConfig.from_env())
    try:
        for manifest_path in manifests:
            started = time.perf_counter()
            try:
                result = _chunk_one_manifest(
                    conn,
                    manifest_path,
                    parent_chunker=parent_chunker,
                    clean_existing=clean_existing,
                    skip_duplicates=skip_duplicates,
                    started=started,
                )
                results.append(result)
            except IngestionError as exc:
                results.append(
                    ChunkCacheResult(
                        manifest_path=manifest_path,
                        status=exc.status,
                        stage=exc.stage,
                        chunk_ms=int((time.perf_counter() - started) * 1000),
                        error_message=exc.message,
                    )
                )
            except Exception as exc:
                results.append(
                    ChunkCacheResult(
                        manifest_path=manifest_path,
                        status="failed",
                        stage="chunking",
                        chunk_ms=int((time.perf_counter() - started) * 1000),
                        error_message=str(exc),
                    )
                )
    finally:
        conn.close()
    return results


def _run_chunk_markdown_folder_parallel(
    manifests: list[Path],
    *,
    parent_chunker: str,
    clean_existing: bool,
    skip_duplicates: bool,
    workers: int,
) -> list[ChunkCacheResult]:
    results: list[ChunkCacheResult] = []

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(
                _chunk_one_manifest_with_connection,
                manifest_path,
                parent_chunker=parent_chunker,
                clean_existing=clean_existing,
                skip_duplicates=skip_duplicates,
            ): manifest_path
            for manifest_path in manifests
        }
        for future in as_completed(futures):
            results.append(future.result())

    return sorted(results, key=lambda result: result.manifest_path.name)


def _chunk_one_manifest_with_connection(
    manifest_path: Path,
    *,
    parent_chunker: str,
    clean_existing: bool,
    skip_duplicates: bool,
) -> ChunkCacheResult:
    started = time.perf_counter()
    conn = db_writer.connect(DBConfig.from_env())
    try:
        return _chunk_one_manifest(
            conn,
            manifest_path,
            parent_chunker=parent_chunker,
            clean_existing=clean_existing,
            skip_duplicates=skip_duplicates,
            started=started,
        )
    except IngestionError as exc:
        return ChunkCacheResult(
            manifest_path=manifest_path,
            status=exc.status,
            stage=exc.stage,
            chunk_ms=int((time.perf_counter() - started) * 1000),
            error_message=exc.message,
        )
    except Exception as exc:
        return ChunkCacheResult(
            manifest_path=manifest_path,
            status="failed",
            stage="chunking",
            chunk_ms=int((time.perf_counter() - started) * 1000),
            error_message=str(exc),
        )
    finally:
        conn.close()


def _chunk_one_manifest(
    conn,
    manifest_path: Path,
    *,
    parent_chunker: str,
    clean_existing: bool,
    skip_duplicates: bool,
    started: float,
) -> ChunkCacheResult:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    file_path = Path(str(manifest["file_path"]))
    markdown_path = Path(str(manifest["markdown_path"]))
    if not file_path.exists():
        raise IngestionError("file_loading", f"source file missing: {file_path}")
    if not markdown_path.exists():
        raise IngestionError("markdown_cache", f"Markdown file missing: {markdown_path}")

    file_info = load_file(file_path)
    raw_metadata = dict(manifest.get("metadata") or {})
    raw_metadata["file_path"] = str(file_path)
    metadata = prepare_metadata(file_info, raw_metadata)
    markdown = markdown_path.read_text(encoding="utf-8")
    metadata = enrich_metadata_from_markdown(metadata, markdown)
    file_checksum = generate_file_checksum(file_info.file_path)

    blocks = markdown_to_blocks(markdown)
    output_root = manifest_path.parents[1]
    output_name = output_name_for_metadata(metadata)
    if parent_chunker == "gemini":
        parent_chunks, summary, _chunks_path, chunk_usage = chunk_markdown_with_gemini(
            markdown,
            metadata,
            output_root,
            output_name=output_name,
        )
        chunks = chunker.add_child_chunks(parent_chunks)
        write_token_usage(output_root, output_name, [chunk_usage])
    else:
        structure = structure_detector.detect_structure(blocks, metadata.document_type)
        chunks = chunker.create_chunks(structure.sections)
        try:
            summary = generate_summary(blocks, metadata)
        except Exception:
            summary = SummaryResult(
                short_summary=None,
                keywords=metadata.keywords,
                main_topics=metadata.main_topics,
                summary_generated=False,
            )

    with conn.transaction():
        version_decision = check_version(
            conn,
            metadata.internal_code,
            file_checksum,
            force_reprocess=not skip_duplicates,
        )
        if version_decision.is_duplicate:
            logger.write_ingestion_log(
                conn,
                status="skipped_duplicate",
                stage="version_check",
                file_info=file_info,
                metadata=metadata,
                file_checksum=file_checksum,
                document_id=version_decision.document_id,
                version_id=version_decision.current_version_id,
            )
            return ChunkCacheResult(
                manifest_path=manifest_path,
                status="skipped_duplicate",
                stage="version_check",
                internal_code=metadata.internal_code,
                title=metadata.title,
                parent_chunker=parent_chunker,
                chunk_ms=int((time.perf_counter() - started) * 1000),
            )

        if version_decision.action == "new_document":
            document_id = db_writer.insert_document(conn, metadata)
        else:
            document_id = version_decision.document_id
            db_writer.update_document_metadata(conn, document_id, metadata)
            db_writer.mark_versions_not_current(conn, document_id)

        deleted_chunks = db_writer.delete_document_chunks(conn, document_id) if clean_existing else 0
        version_id = db_writer.insert_document_version(
            conn,
            document_id,
            metadata,
            file_checksum,
            version_decision.next_version_label,
        )
        total_chunks = db_writer.insert_document_chunks(conn, document_id, version_id, chunks)
        db_writer.update_document_summary(conn, document_id, summary)
        db_writer.expire_older_documents_in_family(
            conn,
            current_document_id=document_id,
            metadata=metadata,
        )
        logger.write_ingestion_log(
            conn,
            status="success",
            stage="markdown_cache_chunked",
            file_info=file_info,
            metadata=metadata,
            file_checksum=file_checksum,
            document_id=document_id,
            version_id=version_id,
            total_chunks=total_chunks,
            summary_generated=summary.summary_generated,
        )

    return ChunkCacheResult(
        manifest_path=manifest_path,
        status="success",
        stage="markdown_cache_chunked",
        internal_code=metadata.internal_code,
        title=metadata.title,
        parent_chunker=parent_chunker,
        total_chunks=total_chunks,
        deleted_chunks=deleted_chunks,
        chunk_ms=int((time.perf_counter() - started) * 1000),
    )


def print_results(results: list[ChunkCacheResult]) -> None:
    counts: dict[str, int] = {}
    for result in results:
        counts[result.status] = counts.get(result.status, 0) + 1
        detail = [
            f"status={result.status}",
            f"stage={result.stage}",
            f"chunker={result.parent_chunker or '-'}",
            f"chunks={result.total_chunks}",
            f"deleted={result.deleted_chunks}",
            f"ms={result.chunk_ms}",
            f"manifest={result.manifest_path.name}",
        ]
        if result.error_message:
            detail.append(f"error={result.error_message}")
        print("CHUNK_CACHE_RESULT " + " ".join(detail))
    print("")
    print("CHUNK_CACHE_SUMMARY")
    print(f"total_manifests={len(results)}")
    for status in sorted(counts):
        print(f"{status}={counts[status]}")


def write_report(results: list[ChunkCacheResult], report_path: str) -> Path:
    path = Path(report_path).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=[
                "manifest",
                "status",
                "stage",
                "internal_code",
                "title",
                "parent_chunker",
                "total_chunks",
                "deleted_chunks",
                "chunk_ms",
                "error_message",
            ],
        )
        writer.writeheader()
        for result in results:
            writer.writerow(
                {
                    "manifest": str(result.manifest_path),
                    "status": result.status,
                    "stage": result.stage,
                    "internal_code": result.internal_code or "",
                    "title": result.title or "",
                    "parent_chunker": result.parent_chunker or "",
                    "total_chunks": result.total_chunks,
                    "deleted_chunks": result.deleted_chunks,
                    "chunk_ms": result.chunk_ms,
                    "error_message": result.error_message or "",
                }
            )
    return path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Chunk a Markdown cache folder and write parent/child chunks to PostgreSQL."
    )
    parser.add_argument("cache_dir", help="Folder produced by ingestion.parse_folder")
    parser.add_argument("--parent-chunker", choices=["rules", "gemini"], default="rules")
    parser.add_argument(
        "--keep-existing",
        action="store_true",
        help="Do not delete existing chunks for each document before inserting new chunks.",
    )
    parser.add_argument(
        "--skip-duplicates",
        action="store_true",
        help="Skip files whose current version checksum already matches the source file.",
    )
    parser.add_argument("--limit", type=int)
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help="Number of manifests to chunk in parallel. Use cautiously with Gemini rate limits.",
    )
    parser.add_argument(
        "--report-path",
        default="data/processed/chunk_markdown_report.csv",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        results = run_chunk_markdown_folder(
            args.cache_dir,
            parent_chunker=args.parent_chunker,
            clean_existing=not args.keep_existing,
            skip_duplicates=args.skip_duplicates,
            limit=args.limit,
            workers=args.workers,
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
