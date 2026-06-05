from __future__ import annotations

import argparse
import hashlib
import sys
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


def embed_missing_chunks(
    conn,
    *,
    model: str,
    limit: int,
    dry_run: bool = False,
) -> EmbedChunksSummary:
    rows = _fetch_chunks_to_embed(conn, model=model, limit=limit)
    embedded = 0
    failed = 0

    for row in rows:
        checksum = _content_checksum(row["chunk_text"])
        if dry_run:
            print(
                "EMBED_CHUNK_DRY_RUN "
                f"chunk_id={row['chunk_id']} title={row['title']} checksum={checksum}",
                flush=True,
            )
            continue

        try:
            embedding = embed_text(
                row["chunk_text"],
                task_type="retrieval_document",
                model=model,
                dimension=DEFAULT_EMBEDDING_DIMENSION,
            )
            _upsert_embedding(
                conn,
                chunk_id=row["chunk_id"],
                model=model,
                embedding=embedding,
                content_checksum=checksum,
            )
            embedded += 1
            print(
                "EMBED_CHUNK_OK "
                f"chunk_id={row['chunk_id']} title={row['title']} dimension={len(embedding)}",
                flush=True,
            )
        except Exception as exc:
            failed += 1
            print(
                f"EMBED_CHUNK_FAILED chunk_id={row['chunk_id']} error={exc}",
                file=sys.stderr,
                flush=True,
            )

    return EmbedChunksSummary(
        scanned=len(rows),
        embedded=embedded,
        skipped=0 if dry_run else max(0, len(rows) - embedded - failed),
        failed=failed,
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
