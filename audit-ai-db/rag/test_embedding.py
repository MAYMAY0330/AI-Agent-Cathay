from __future__ import annotations

import sys

from ingestion.models import IngestionError
from rag.embedding_client import embed_text


def main() -> int:
    try:
        embedding = embed_text("RAG 是什麼？", task_type="retrieval_query")
    except IngestionError as exc:
        print(f"FAILED stage={exc.stage} error={exc.message}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"FAILED stage=embedding_smoke_test error={exc}", file=sys.stderr)
        return 1

    print(f"EMBEDDING_SMOKE_TEST_OK dimension={len(embedding)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

