from __future__ import annotations

import argparse
import hashlib
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.append(str(Path(__file__).resolve().parents[1]))

from ingestion.config import DBConfig
from ingestion.db_writer import connect
from ingestion.models import IngestionError
from rag.embedding_client import (
    DEFAULT_EMBEDDING_DIMENSION,
    DEFAULT_EMBEDDING_MODEL,
    embed_text,
    embedding_to_pgvector,
)


@dataclass(frozen=True)
class EmbedChunksSummary:
    scanned: int
    embedded: int
    skipped: int
    failed: int


@dataclass(frozen=True)
class EmbedChunkResult:
    chunk_id: Any
    title: str
    checksum: str
    embedding: list[float]


def embed_missing_chunks(
    conn,
    *,
    model: str,
    limit: int,
    dry_run: bool = False,
    workers: int = 1,
) -> EmbedChunksSummary:
    rows = _fetch_chunks_to_embed(conn, model=model, limit=limit)
    embedded = 0
    failed = 0
    workers = max(1, workers)

    if dry_run:
        for row in rows:
            checksum = _content_checksum(row["chunk_text"])
            print(
                "EMBED_CHUNK_DRY_RUN "
                f"chunk_id={row['chunk_id']} title={row['title']} checksum={checksum}",
                flush=True,
            )
        return EmbedChunksSummary(
            scanned=len(rows),
            embedded=0,
            skipped=0,
            failed=0,
        )

    if not rows:
        return EmbedChunksSummary(scanned=0, embedded=0, skipped=0, failed=0)

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(_embed_chunk_row, row, model) for row in rows]
        for future in as_completed(futures):
            try:
                result = future.result()
                _upsert_embedding(
                    conn,
                    chunk_id=result.chunk_id,
                    model=model,
                    embedding=result.embedding,
                    content_checksum=result.checksum,
                )
                embedded += 1
                print(
                    "EMBED_CHUNK_OK "
                    f"chunk_id={result.chunk_id} title={result.title} "
                    f"dimension={len(result.embedding)}",
                    flush=True,
                )
            except Exception as exc:
                failed += 1
                print(
                    f"EMBED_CHUNK_FAILED error={exc}",
                    file=sys.stderr,
                    flush=True,
                )

    return EmbedChunksSummary(
        scanned=len(rows),
        embedded=embedded,
        skipped=max(0, len(rows) - embedded - failed),
        failed=failed,
    )


def _embed_chunk_row(row: dict[str, Any], model: str) -> EmbedChunkResult:
    checksum = _content_checksum(row["chunk_text"])
    embedding = embed_text(
        row["chunk_text"],
        task_type="retrieval_document",
        model=model,
        dimension=DEFAULT_EMBEDDING_DIMENSION,
    )
    return EmbedChunkResult(
        chunk_id=row["chunk_id"],
        title=row["title"],
        checksum=checksum,
        embedding=embedding,
    )


def _fetch_chunks_to_embed(conn, *, model: str, limit: int) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                c.id AS chunk_id,
                d.title,
                c.chunk_text
            FROM document_chunks c
            JOIN document_versions v ON v.id = c.version_id AND v.is_current = TRUE
            JOIN documents d ON d.id = c.document_id
            LEFT JOIN chunk_embeddings e
                ON e.chunk_id = c.id
               AND e.embedding_model = %(model)s
               AND e.content_checksum = encode(sha256(convert_to(c.chunk_text, 'UTF8')), 'hex')
            WHERE e.id IS NULL
              AND (
                  c.parent_chunk_id IS NOT NULL
                  OR NOT EXISTS (
                      SELECT 1
                      FROM document_chunks child
                      WHERE child.parent_chunk_id = c.id
                  )
              )
            ORDER BY d.updated_at DESC, c.created_at ASC, c.chunk_index ASC
            LIMIT %(limit)s
            """,
            {"model": model, "limit": limit},
        )
        return list(cur.fetchall())


def _upsert_embedding(
    conn,
    *,
    chunk_id: Any,
    model: str,
    embedding: list[float],
    content_checksum: str,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO chunk_embeddings (
                chunk_id,
                embedding_model,
                embedding_dimension,
                embedding,
                content_checksum
            )
            VALUES (%s, %s, %s, %s::vector, %s)
            ON CONFLICT (chunk_id, embedding_model)
            DO UPDATE SET
                embedding_dimension = EXCLUDED.embedding_dimension,
                embedding = EXCLUDED.embedding,
                content_checksum = EXCLUDED.content_checksum,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                chunk_id,
                model,
                DEFAULT_EMBEDDING_DIMENSION,
                embedding_to_pgvector(embedding),
                content_checksum,
            ),
        )


def _content_checksum(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate Gemini embeddings for document_chunks and store them in chunk_embeddings."
    )
    parser.add_argument("--limit", type=int, default=25)
    parser.add_argument("--model", default=DEFAULT_EMBEDDING_MODEL)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help="Number of concurrent embedding API calls. Keep modest to avoid rate limits.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    conn = None
    try:
        conn = connect(DBConfig.from_env())
        summary = embed_missing_chunks(
            conn,
            model=args.model,
            limit=args.limit,
            dry_run=args.dry_run,
            workers=args.workers,
        )
    except IngestionError as exc:
        print(f"FAILED stage={exc.stage} error={exc.message}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"FAILED stage=embed_chunks error={exc}", file=sys.stderr)
        return 1
    finally:
        if conn is not None:
            conn.close()

    print(
        "EMBED_CHUNKS_SUMMARY "
        f"scanned={summary.scanned} embedded={summary.embedded} "
        f"skipped={summary.skipped} failed={summary.failed}"
    )
    return 1 if summary.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
