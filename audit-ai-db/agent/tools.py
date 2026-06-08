from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from agent.llm_agent.decisions import (
    judge_evidence_with_llm,
    plan_search_tasks_with_llm as plan_search_tasks_with_llm_decision,
)
from agent.state import (
    AgentAnswer,
    AgentRunLog,
    EvidenceJudgment,
    EvidenceBundle,
    SearchTask,
    VerificationResult,
)
from agent.tool_registry import AgentTool, ToolRegistry
from ingestion.models import IngestionError
from rag.answer_generator import generate_answer
from rag.context_builder import RAGContext, build_rag_context
from rag.hybrid_search import hybrid_search
from rag.search_models import SearchFilters, SearchResult


QUESTION_WORDS = {
    "是否",
    "需要",
    "如何",
    "哪些",
    "什麼",
    "甚麼",
    "可以",
    "應",
    "要",
    "嗎",
}
DOMAIN_KEYWORDS = [
    "客戶資料共享",
    "資料共享",
    "集團資料共享",
    "客戶同意",
    "告知客戶",
    "事前取得",
    "拒絕",
    "停止共享",
    "共享使用",
    "客戶註記",
    "負面資訊",
    "風險類資料",
    "必要查證",
    "保密義務",
    "安全維護",
    "個資法",
    "共享政策",
    "管理辦法",
]
CITATION_RE = re.compile(r"\[(S\d+)\]")


def normalize_question(question: str) -> dict[str, Any]:
    normalized = re.sub(r"\s+", " ", question).strip()
    normalized = normalized.replace("？", "?").replace("，", ",")
    keywords = _keyword_phrases(normalized)
    return {
        "normalized_question": normalized,
        "keywords": keywords,
        "filters": {},
    }


def plan_search_tasks(
    normalized_question: str,
    *,
    keywords: list[str] | None = None,
    limit: int = 6,
    filters: dict[str, Any] | None = None,
    iteration: int = 1,
) -> list[SearchTask]:
    keywords = keywords or _keyword_phrases(normalized_question)
    filters = _clean_filters(filters or {})
    queries = [normalized_question]

    compact_query = _compact_query(normalized_question, keywords)
    if compact_query and compact_query not in queries:
        queries.append(compact_query)

    expanded_query = _expanded_query(normalized_question)
    if expanded_query and expanded_query not in queries:
        queries.append(expanded_query)

    if iteration > 1:
        retry_query = " ".join(keywords[:8]) if keywords else normalized_question
        if retry_query and retry_query not in queries:
            queries.insert(0, retry_query)

    tasks: list[SearchTask] = []
    for index, query in enumerate(queries[:3], start=1):
        tasks.append(
            SearchTask(
                task_id=f"search_{iteration}_{index}",
                query=query,
                purpose=_task_purpose(index, iteration),
                limit=limit,
                filters=filters,
            )
        )
    return tasks


def plan_search_tasks_with_llm(
    normalized_question: str,
    *,
    keywords: list[str] | None = None,
    limit: int = 6,
    filters: dict[str, Any] | None = None,
    iteration: int = 1,
    refined_query: str | None = None,
) -> dict[str, Any]:
    fallback = plan_search_tasks(
        refined_query or normalized_question,
        keywords=keywords,
        limit=limit,
        filters=filters,
        iteration=iteration,
    )
    return plan_search_tasks_with_llm_decision(
        normalized_question,
        keywords=keywords or [],
        limit=limit,
        filters=filters or {},
        iteration=iteration,
        refined_query=refined_query,
        fallback_tasks=fallback,
    )


def retrieve_evidence(
    conn,
    task: SearchTask,
    *,
    include_vector: bool,
    embedding_model: str | None,
    include_agentic: bool = False,
) -> list[SearchResult]:
    filters = SearchFilters(
        document_type=task.filters.get("document_type"),
        status=task.filters.get("status", "active"),
        source_system=task.filters.get("source_system"),
        language=task.filters.get("language"),
    )
    return hybrid_search(
        conn,
        task.query,
        limit=max(task.limit * 3, task.limit),
        filters=filters,
        include_vector=include_vector,
        include_agentic=include_agentic,
        embedding_model=embedding_model,
    )


def select_evidence(
    question: str,
    results: list[SearchResult],
    *,
    limit: int,
    max_context_chars: int,
) -> EvidenceBundle:
    deduped = _dedupe_results(results)
    question_keywords = _keyword_phrases(question)
    ordered = sorted(
        deduped,
        key=lambda result: (
            1 if _has_chunk_evidence(result) else 0,
            _agent_relevance_score(question, question_keywords, result),
            result.score,
            -result.chunk_index,
        ),
        reverse=True,
    )
    selected = ordered[:limit]
    context = build_rag_context(
        question,
        selected,
        max_sources=limit,
        max_context_chars=max_context_chars,
        preserve_order=True,
    )
    return EvidenceBundle(
        sources=context.sources,
        selected_results=selected,
        all_results_count=len(results),
    )


def check_evidence_sufficiency(
    bundle: EvidenceBundle,
    *,
    min_score: float = 0.08,
) -> VerificationResult:
    if not bundle.sources:
        return VerificationResult(
            valid=False,
            errors=["no_sources"],
            reason="No retrieved source chunks were selected.",
        )

    strongest = max((source.score for source in bundle.sources), default=0.0)
    if strongest < min_score:
        return VerificationResult(
            valid=False,
            errors=["weak_scores"],
            reason=f"Strongest selected source score {strongest:.4f} is below {min_score:.4f}.",
        )

    if not any(_source_has_direct_evidence(source.match_sources) for source in bundle.sources):
        return VerificationResult(
            valid=False,
            errors=["no_direct_chunk_evidence"],
            reason="Selected sources do not include keyword or vector chunk evidence.",
        )

    if not any(len(source.text.strip()) >= 30 for source in bundle.sources):
        return VerificationResult(
            valid=False,
            errors=["short_sources"],
            reason="Selected source text is too short to support an answer.",
        )

    return VerificationResult(valid=True, reason="Evidence is sufficient for answer generation.")


def judge_evidence_checklist(
    question: str,
    bundle: EvidenceBundle,
) -> list[EvidenceJudgment]:
    judgments: list[EvidenceJudgment] = []
    question_keywords = _keyword_phrases(question)
    for source in bundle.sources:
        checklist = _score_source_checklist(question, question_keywords, source)
        score = sum(checklist.values())
        judgments.append(
            EvidenceJudgment(
                label=source.label,
                chunk_id=source.chunk_id,
                checklist=checklist,
                score=score,
                max_score=len(checklist),
                classification=_classify_checklist_score(score, checklist),
                reason=_checklist_reason(checklist, source),
                supporting_quote=_supporting_quote(question_keywords, source.text),
                mode="deterministic",
            )
        )
    return judgments


def apply_evidence_judgments(
    bundle: EvidenceBundle,
    judgments: list[EvidenceJudgment],
) -> EvidenceBundle:
    if not judgments:
        return bundle

    judgment_by_chunk = {judgment.chunk_id: judgment for judgment in judgments}

    def sort_key(result: SearchResult) -> tuple[int, int, float, int]:
        judgment = judgment_by_chunk.get(result.chunk_id)
        direct = judgment.checklist.get("direct_answer", 0) if judgment else 0
        checklist_score = judgment.score if judgment else 0
        return (direct, checklist_score, result.score, -result.chunk_index)

    selected_results = sorted(bundle.selected_results, key=sort_key, reverse=True)
    rebuilt_context = build_rag_context(
        "",
        selected_results,
        max_sources=len(bundle.sources),
        max_context_chars=sum(len(source.text) for source in bundle.sources) or 1,
        preserve_order=True,
    )
    return EvidenceBundle(
        sources=rebuilt_context.sources,
        selected_results=selected_results,
        all_results_count=bundle.all_results_count,
    )


def build_answer_context(
    question: str,
    bundle: EvidenceBundle,
    *,
    max_context_chars: int,
) -> RAGContext:
    return build_rag_context(
        question,
        bundle.selected_results,
        max_sources=len(bundle.sources),
        max_context_chars=max_context_chars,
        preserve_order=True,
    )


def generate_cited_answer(
    context: RAGContext | None,
    *,
    dry_run: bool,
    insufficient_reason: str | None = None,
) -> AgentAnswer:
    if insufficient_reason:
        return AgentAnswer(
            status="insufficient_evidence",
            answer="目前無法由已檢索到的內部文件判定此問題。請補充更明確的問題或匯入相關文件。",
            model="none",
        )
    if dry_run:
        return AgentAnswer(
            status="dry_run",
            answer="DRY RUN: 已完成檢索、證據選擇與提示組裝；未呼叫 LLM 產生正式答覆。",
            model="dry-run",
        )
    if context is None:
        return AgentAnswer(
            status="insufficient_evidence",
            answer="目前沒有足夠的資料來源，無法根據已匯入文件回答此問題。",
            model="none",
        )

    rag_answer = generate_answer(context)
    return AgentAnswer(status="answered", answer=rag_answer.answer, model=rag_answer.model)


def verify_citations(
    answer: AgentAnswer,
    sources: list[Any],
) -> VerificationResult:
    if not answer.answer.strip():
        return VerificationResult(valid=False, errors=["empty_answer"])

    if answer.status in {"insufficient_evidence", "dry_run"}:
        return VerificationResult(valid=True, reason=f"Verification skipped for {answer.status}.")

    source_labels = {_source_label(source) for source in sources}
    cited_labels = _dedupe_labels(CITATION_RE.findall(answer.answer))
    errors: list[str] = []
    if not cited_labels:
        errors.append("missing_citations")

    unknown_labels = [label for label in cited_labels if label not in source_labels]
    if unknown_labels:
        errors.append("unknown_citations:" + ",".join(unknown_labels))

    return VerificationResult(
        valid=not errors,
        cited_labels=cited_labels,
        errors=errors,
        reason="Citation labels verified." if not errors else "Citation verification failed.",
    )


def log_agent_run(log: AgentRunLog, *, log_dir: Path) -> Path:
    log_dir.mkdir(parents=True, exist_ok=True)
    date_part = datetime.now().strftime("%Y-%m-%d")
    path = log_dir / f"{date_part}.jsonl"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(log.to_dict(), ensure_ascii=False) + "\n")
    return path


def build_tool_registry(
    conn,
    *,
    include_vector: bool,
    embedding_model: str | None,
    dry_run: bool,
    log_dir: Path,
    include_agentic: bool = False,
) -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(
        AgentTool(
            name="normalize_question",
            description="Normalize the raw user question and extract search keywords.",
            input_schema=_object_schema(["question"], {"question": {"type": "string"}}),
            output_schema=_object_schema(
                ["normalized_question", "keywords", "filters"],
                {
                    "normalized_question": {"type": "string"},
                    "keywords": {"type": "array"},
                    "filters": {"type": "object"},
                },
            ),
            callable=lambda payload: normalize_question(payload["question"]),
        )
    )
    registry.register(
        AgentTool(
            name="plan_search_tasks",
            description="Create guarded retrieval tasks from a normalized question.",
            input_schema=_object_schema(
                ["normalized_question", "limit"],
                {
                    "normalized_question": {"type": "string"},
                    "keywords": {"type": "array"},
                    "filters": {"type": "object"},
                    "limit": {"type": "integer"},
                    "iteration": {"type": "integer"},
                },
            ),
            output_schema={},
            callable=lambda payload: plan_search_tasks(
                payload["normalized_question"],
                keywords=payload.get("keywords"),
                limit=payload["limit"],
                filters=payload.get("filters"),
                iteration=payload.get("iteration", 1),
            ),
        )
    )
    registry.register(
        AgentTool(
            name="plan_search_tasks_llm",
            description="Ask the LLM to plan retrieval tasks, with deterministic fallback.",
            input_schema=_object_schema(
                ["normalized_question", "limit"],
                {
                    "normalized_question": {"type": "string"},
                    "keywords": {"type": "array"},
                    "filters": {"type": "object"},
                    "limit": {"type": "integer"},
                    "iteration": {"type": "integer"},
                    "refined_query": {"type": "string"},
                },
            ),
            output_schema={},
            callable=lambda payload: plan_search_tasks_with_llm(
                payload["normalized_question"],
                keywords=payload.get("keywords"),
                limit=payload["limit"],
                filters=payload.get("filters"),
                iteration=payload.get("iteration", 1),
                refined_query=payload.get("refined_query"),
            ),
        )
    )
    registry.register(
        AgentTool(
            name="retrieve_evidence",
            description="Run hybrid retrieval against the PostgreSQL knowledge base.",
            input_schema=_object_schema(["task"], {"task": {"type": "object"}}),
            output_schema={},
            callable=lambda payload: retrieve_evidence(
                conn,
                _coerce_search_task(payload["task"]),
                include_vector=include_vector,
                include_agentic=include_agentic,
                embedding_model=embedding_model,
            ),
        )
    )
    registry.register(
        AgentTool(
            name="select_evidence",
            description="Deduplicate and label the strongest retrieved evidence.",
            input_schema=_object_schema(
                ["question", "results", "limit", "max_context_chars"],
                {
                    "question": {"type": "string"},
                    "results": {"type": "array"},
                    "limit": {"type": "integer"},
                    "max_context_chars": {"type": "integer"},
                },
            ),
            output_schema={},
            callable=lambda payload: select_evidence(
                payload["question"],
                payload["results"],
                limit=payload["limit"],
                max_context_chars=payload["max_context_chars"],
            ),
        )
    )
    registry.register(
        AgentTool(
            name="check_evidence_sufficiency",
            description="Decide whether selected evidence is enough to answer.",
            input_schema=_object_schema(["bundle"], {"bundle": {"type": "object"}}),
            output_schema={},
            callable=lambda payload: check_evidence_sufficiency(payload["bundle"]),
        )
    )
    registry.register(
        AgentTool(
            name="judge_evidence_checklist",
            description="Score selected evidence with an auditable binary checklist.",
            input_schema=_object_schema(
                ["question", "bundle"],
                {"question": {"type": "string"}, "bundle": {"type": "object"}},
            ),
            output_schema={},
            callable=lambda payload: judge_evidence_checklist(
                payload["question"],
                payload["bundle"],
            ),
        )
    )
    registry.register(
        AgentTool(
            name="apply_evidence_judgments",
            description="Rerank selected evidence by checklist judgments.",
            input_schema=_object_schema(
                ["bundle", "judgments"],
                {"bundle": {"type": "object"}, "judgments": {"type": "array"}},
            ),
            output_schema={},
            callable=lambda payload: apply_evidence_judgments(
                payload["bundle"],
                payload["judgments"],
            ),
        )
    )
    registry.register(
        AgentTool(
            name="judge_evidence_llm",
            description="Ask the LLM whether selected evidence answers the question.",
            input_schema=_object_schema(
                ["question", "bundle", "deterministic"],
                {
                    "question": {"type": "string"},
                    "bundle": {"type": "object"},
                    "deterministic": {"type": "object"},
                },
            ),
            output_schema={},
            callable=lambda payload: judge_evidence_with_llm(
                payload["question"],
                payload["bundle"],
                deterministic=payload["deterministic"],
            ),
        )
    )
    registry.register(
        AgentTool(
            name="build_answer_context",
            description="Build the final answer prompt/context from selected evidence.",
            input_schema=_object_schema(
                ["question", "bundle", "max_context_chars"],
                {
                    "question": {"type": "string"},
                    "bundle": {"type": "object"},
                    "max_context_chars": {"type": "integer"},
                },
            ),
            output_schema={},
            callable=lambda payload: build_answer_context(
                payload["question"],
                payload["bundle"],
                max_context_chars=payload["max_context_chars"],
            ),
        )
    )
    registry.register(
        AgentTool(
            name="generate_cited_answer",
            description="Generate a cited Traditional Chinese answer or dry-run preview.",
            input_schema=_object_schema(
                ["dry_run"],
                {
                    "context": {"type": "object"},
                    "dry_run": {"type": "boolean"},
                    "insufficient_reason": {"type": "string"},
                },
            ),
            output_schema={},
            callable=lambda payload: generate_cited_answer(
                payload.get("context"),
                dry_run=payload.get("dry_run", dry_run),
                insufficient_reason=payload.get("insufficient_reason"),
            ),
        )
    )
    registry.register(
        AgentTool(
            name="verify_citations",
            description="Validate cited source labels in the generated answer.",
            input_schema=_object_schema(
                ["answer", "sources"],
                {"answer": {"type": "object"}, "sources": {"type": "array"}},
            ),
            output_schema={},
            callable=lambda payload: verify_citations(payload["answer"], payload["sources"]),
        )
    )
    registry.register(
        AgentTool(
            name="log_agent_run",
            description="Append an auditable agent run record to JSONL.",
            input_schema=_object_schema(["log"], {"log": {"type": "object"}}),
            output_schema={},
            callable=lambda payload: log_agent_run(payload["log"], log_dir=log_dir),
        )
    )
    return registry


def _keyword_phrases(question: str) -> list[str]:
    keywords: list[str] = []
    for keyword in DOMAIN_KEYWORDS:
        if keyword in question:
            keywords.append(keyword)
    for term in re.findall(r"[A-Za-z0-9_@.-]+", question):
        if len(term) >= 2:
            keywords.append(term)
    for cjk_text in re.findall(r"[\u4e00-\u9fff]+", question):
        compact = cjk_text
        for word in QUESTION_WORDS:
            compact = compact.replace(word, "")
        if 2 <= len(compact) <= 12:
            keywords.append(compact)
    return _dedupe_labels(keywords)[:12]


def _compact_query(question: str, keywords: list[str]) -> str:
    useful = [term for term in keywords if term not in QUESTION_WORDS and len(term) >= 2]
    if len(useful) >= 3:
        return " ".join(useful[:8])
    compact = question
    for word in QUESTION_WORDS:
        compact = compact.replace(word, "")
    compact = re.sub(r"[?？,，。；;:：]", " ", compact)
    return re.sub(r"\s+", " ", compact).strip()


def _expanded_query(question: str) -> str | None:
    expansions: list[str] = []
    if "告知" in question or "同意" in question:
        expansions.append("資料共享 事前取得客戶同意 個資告知")
    if "拒絕" in question or "停止" in question:
        expansions.append("拒絕集團資料共享 停止共享使用 客戶註記")
    if "負面" in question or "風險" in question:
        expansions.append("資料共享 負面資訊 風險類資料 必要查證")
    if "保密" in question or "洩漏" in question:
        expansions.append("資料共享 保密義務 安全維護措施")
    return " ".join(expansions) if expansions else None


def _task_purpose(index: int, iteration: int) -> str:
    if index == 1:
        return "direct_question" if iteration == 1 else "retry_keyword_focus"
    if index == 2:
        return "keyword_compaction"
    return "domain_expansion"


def _clean_filters(filters: dict[str, Any]) -> dict[str, Any]:
    allowed = {"document_type", "status", "source_system", "language"}
    return {key: value for key, value in filters.items() if key in allowed and value}


def _coerce_search_task(value: Any) -> SearchTask:
    if isinstance(value, SearchTask):
        return value
    if isinstance(value, dict):
        return SearchTask(
            task_id=str(value["task_id"]),
            query=str(value["query"]),
            purpose=str(value["purpose"]),
            limit=int(value["limit"]),
            filters=dict(value.get("filters") or {}),
        )
    raise IngestionError("agent_tool_call", "retrieve_evidence task must be SearchTask or dict")


def _dedupe_results(results: list[SearchResult]) -> list[SearchResult]:
    by_chunk: dict[str, SearchResult] = {}
    for result in results:
        existing = by_chunk.get(result.chunk_id)
        if existing is None:
            by_chunk[result.chunk_id] = result
            continue
        existing.merge(result)
    return list(by_chunk.values())


def _agent_relevance_score(
    question: str,
    question_keywords: list[str],
    result: SearchResult,
) -> float:
    haystack = " ".join(
        value
        for value in (
            result.title,
            result.section_title or "",
            result.heading_path or "",
            result.clause_number or "",
            result.chunk_text,
        )
        if value
    )
    score = 0.0
    for keyword in question_keywords:
        if not keyword:
            continue
        if keyword in result.chunk_text:
            score += 3.0
        elif keyword in haystack:
            score += 1.5

    exact_phrases = [
        keyword
        for keyword in DOMAIN_KEYWORDS
        if keyword in question and keyword not in {"資料共享", "管理辦法", "共享政策"}
    ]
    for phrase in exact_phrases:
        if phrase in result.chunk_text:
            score += 5.0
        elif phrase in haystack:
            score += 2.0
    return score


def _has_chunk_evidence(result: SearchResult) -> bool:
    return _source_has_direct_evidence(result.match_sources)


def _source_has_direct_evidence(match_sources: list[str]) -> bool:
    return any(source in match_sources for source in ("keyword", "vector", "metadata_chunk"))


def _score_source_checklist(
    question: str,
    question_keywords: list[str],
    source: Any,
) -> dict[str, int]:
    text = str(source.text or "")
    metadata = " ".join(
        str(value)
        for value in (
            source.title,
            source.document_type,
            source.section_title or "",
            source.heading_path or "",
            source.clause_number or "",
        )
        if value
    )
    haystack = f"{metadata} {text}"
    key_concepts = _matched_keyword_count(question_keywords, haystack)
    direct_markers = ("應", "須", "需要", "不得", "得", "同意", "告知", "始得", "應於事前")
    concrete_markers = (
        "條",
        "辦法",
        "規定",
        "應",
        "不得",
        "始得",
        "同意",
        "告知",
        "例外",
        "程序",
        "法務室意見",
    )
    mismatch = _has_obvious_mismatch(question, text)
    return {
        "direct_answer": 1 if key_concepts >= 1 and _has_direct_answer_marker(question, text, direct_markers) and not mismatch else 0,
        "key_concepts": 1 if key_concepts > 0 else 0,
        "concrete_rule": 1 if any(marker in haystack for marker in concrete_markers) else 0,
        "citation_metadata": 1 if bool(source.title and (source.section_title or source.heading_path or source.clause_number or source.page_start)) else 0,
        "authoritative_source": 1 if source.document_type in {"legal_opinion", "internal_rule", "policy_guideline"} else 0,
        "current_source": 1,
        "no_obvious_mismatch": 0 if mismatch else 1,
    }


def _matched_keyword_count(question_keywords: list[str], haystack: str) -> int:
    return sum(1 for keyword in question_keywords if keyword and keyword in haystack)


def _has_obvious_mismatch(question: str, text: str) -> bool:
    mismatch_pairs = [
        ("資料共享", "AI"),
        ("告知", "申訴"),
        ("同意", "申訴"),
        ("上線", "資料共享"),
    ]
    for question_marker, text_marker in mismatch_pairs:
        if question_marker in question and text_marker in text and question_marker not in text:
            return True
    return False


def _has_direct_answer_marker(
    question: str,
    text: str,
    direct_markers: tuple[str, ...],
) -> bool:
    if "客戶" in question and "告知" in question and not any(
        term in text
        for term in (
            "告知客戶",
            "客戶同意",
            "取得客戶同意",
            "徵得其同意",
            "當事人同意",
            "應告知事項",
            "契據",
        )
    ):
        return False
    if "告知" in question and not any(term in text for term in ("告知", "同意", "應告知事項", "契據")):
        return False
    if "同意" in question and "同意" not in text:
        return False
    if "拒絕" in question and not any(term in text for term in ("拒絕", "停止", "註記")):
        return False
    if "風險" in question and "風險" not in text:
        return False
    return any(marker in text for marker in direct_markers)


def _classify_checklist_score(score: int, checklist: dict[str, int]) -> str:
    if score >= 6 and checklist.get("direct_answer") == 1:
        return "strong"
    if score >= 4:
        return "supporting"
    if score >= 2:
        return "background"
    return "irrelevant"


def _checklist_reason(checklist: dict[str, int], source: Any) -> str:
    passed = [key for key, value in checklist.items() if value == 1]
    failed = [key for key, value in checklist.items() if value == 0]
    return (
        f"passed={','.join(passed) or '-'}; "
        f"failed={','.join(failed) or '-'}; "
        f"source={source.title}"
    )


def _supporting_quote(question_keywords: list[str], text: str, *, max_chars: int = 180) -> str:
    clean = " ".join(text.split())
    if not clean:
        return ""
    for keyword in question_keywords:
        index = clean.find(keyword)
        if index >= 0:
            start = max(0, index - 40)
            return clean[start : start + max_chars]
    return clean[:max_chars]


def _source_label(source: Any) -> str:
    if isinstance(source, dict):
        return str(source.get("label"))
    return str(source.label)


def _dedupe_labels(labels: list[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for label in labels:
        if label in seen:
            continue
        seen.add(label)
        unique.append(label)
    return unique


def _object_schema(required: list[str], properties: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "object",
        "required": required,
        "properties": properties,
    }
