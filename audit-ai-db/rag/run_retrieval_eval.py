from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.append(str(Path(__file__).resolve().parents[1]))

from ingestion.config import DBConfig
from ingestion.db_writer import connect
from ingestion.models import IngestionError
from rag.embedding_client import DEFAULT_EMBEDDING_MODEL
from rag.hybrid_search import hybrid_search
from rag.reranker import DEFAULT_RERANKER_MODEL
from rag.search_models import SearchFilters


@dataclass(frozen=True)
class EvalQuestion:
    question: str
    expected_title_terms: list[str]
    expected_text_terms: list[str]


DEFAULT_QUESTIONS = [
    EvalQuestion(
        question="客戶資料共享是否需要告知客戶?",
        expected_title_terms=["客戶資料共享", "資料共享"],
        expected_text_terms=["告知", "同意", "契據"],
    ),
    EvalQuestion(
        question="客戶拒絕資料共享時公司要怎麼處理?",
        expected_title_terms=["客戶資料共享", "資料共享"],
        expected_text_terms=["拒絕", "停止", "註記"],
    ),
    EvalQuestion(
        question="客戶健康資料可以用於行銷嗎?",
        expected_title_terms=["健康", "行銷"],
        expected_text_terms=["健康", "行銷", "同意"],
    ),
    EvalQuestion(
        question="使用生成式AI需要揭露什麼?",
        expected_title_terms=["人工智慧", "AI"],
        expected_text_terms=["生成式AI", "揭露", "告知"],
    ),
    EvalQuestion(
        question="資料共享涉及負面資訊時要注意什麼?",
        expected_title_terms=["客戶資料共享", "資料共享"],
        expected_text_terms=["負面資訊", "風險", "查證"],
    ),
    EvalQuestion(
        question="AI服務應用上線前需要做哪些檢核?",
        expected_title_terms=["AI", "人工智慧", "上線檢核"],
        expected_text_terms=["上線", "檢核", "風險評估"],
    ),
    EvalQuestion(
        question="資料共享資料外洩時有哪些保密或安全維護要求?",
        expected_title_terms=["資料共享", "客戶資料共享"],
        expected_text_terms=["保密", "安全維護"],
    ),
    EvalQuestion(
        question="公司員工餐廳菜單如何訂價?",
        expected_title_terms=[],
        expected_text_terms=[],
    ),
]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a small retrieval quality regression set.")
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--top-k", type=int, default=3)
    parser.add_argument("--vector", action="store_true")
    parser.add_argument("--agentic", action="store_true")
    parser.add_argument("--embedding-model", default=DEFAULT_EMBEDDING_MODEL)
    parser.add_argument("--rerank", action="store_true")
    parser.add_argument("--reranker-model", default=DEFAULT_RERANKER_MODEL)
    parser.add_argument("--rerank-candidates", type=int, default=30)
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    conn = None
    try:
        conn = connect(DBConfig.from_env())
        rows = []
        for item in DEFAULT_QUESTIONS:
            results = hybrid_search(
                conn,
                item.question,
                limit=args.limit,
                filters=SearchFilters(),
                include_vector=args.vector,
                include_agentic=args.agentic,
                embedding_model=args.embedding_model,
                rerank=args.rerank,
                reranker_model=args.reranker_model,
                rerank_candidates=args.rerank_candidates,
            )
            top_results = results[: args.top_k]
            rows.append(
                {
                    "question": item.question,
                    "expected_title_terms": item.expected_title_terms,
                    "expected_text_terms": item.expected_text_terms,
                    "top_k_hit": _has_expected_hit(item, top_results),
                    "top_results": [asdict(result) for result in top_results],
                }
            )
    except IngestionError as exc:
        print(f"FAILED stage={exc.stage} error={exc.message}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"FAILED stage=retrieval_eval error={exc}", file=sys.stderr)
        return 1
    finally:
        if conn is not None:
            conn.close()

    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
    else:
        hits = sum(1 for row in rows if row["top_k_hit"])
        print(f"RETRIEVAL_EVAL hit_rate={hits}/{len(rows)} rerank={args.rerank}")
        for row in rows:
            print(f"- hit={row['top_k_hit']} question={row['question']}")
    return 0


def _has_expected_hit(item: EvalQuestion, results) -> bool:
    if not item.expected_title_terms and not item.expected_text_terms:
        return not results
    for result in results:
        title_ok = (
            not item.expected_title_terms
            or any(term in result.title for term in item.expected_title_terms)
        )
        text = f"{result.chunk_text} {result.matched_chunk_text or ''}"
        text_ok = (
            not item.expected_text_terms
            or any(term in text for term in item.expected_text_terms)
        )
        if title_ok and text_ok:
            return True
    return False


if __name__ == "__main__":
    raise SystemExit(main())
