from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from ingestion.gemini.reader import create_gemini_model, load_gemini_settings
from rag.keyword_search import search_chunks
from rag.metadata_search import search_metadata
from rag.search_models import SearchFilters, SearchResult
from rag.vector_search import search_vectors


ALLOWED_FILTERS = {"document_type", "status", "source_system", "language"}
ALLOWED_PURPOSES = {
    "synonym_expansion",
    "legal_term_expansion",
    "document_phrase_match",
    "metadata_focus",
}
AGENTIC_SEARCH_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "reason": {"type": "string"},
        "queries": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "purpose": {
                        "type": "string",
                        "enum": sorted(ALLOWED_PURPOSES),
                    },
                },
                "required": ["query", "purpose"],
            },
        },
        "filters": {
            "type": "object",
            "properties": {
                "document_type": {"type": "string"},
                "status": {"type": "string"},
                "source_system": {"type": "string"},
                "language": {"type": "string"},
            },
        },
    },
    "required": ["reason", "queries", "filters"],
}


@dataclass(frozen=True)
class AgenticSearchQuery:
    query: str
    purpose: str


@dataclass(frozen=True)
class AgenticSearchPlan:
    queries: list[AgenticSearchQuery]
    filters: SearchFilters
    reason: str
    mode: str
    raw: dict[str, Any] = field(default_factory=dict)


def search_agentic(
    conn,
    query: str,
    *,
    limit: int = 10,
    filters: SearchFilters | None = None,
    include_keyword: bool = True,
    include_metadata: bool = True,
    include_vector: bool = False,
    embedding_model: str | None = None,
    max_queries: int = 3,
) -> list[SearchResult]:
    plan = plan_agentic_search(
        query,
        filters=filters,
        max_queries=max_queries,
    )
    if not plan.queries:
        return []

    candidates: list[SearchResult] = []
    per_query_limit = max(limit, 5)
    for index, planned_query in enumerate(plan.queries, start=1):
        if include_keyword:
            candidates.extend(
                _tag_agentic_results(
                    search_chunks(
                        conn,
                        planned_query.query,
                        limit=per_query_limit,
                        filters=plan.filters,
                    ),
                    planned_query,
                    index,
                    plan,
                )
            )
        if include_metadata:
            candidates.extend(
                _tag_agentic_results(
                    search_metadata(
                        conn,
                        planned_query.query,
                        limit=max(3, per_query_limit // 2),
                        filters=plan.filters,
                    ),
                    planned_query,
                    index,
                    plan,
                )
            )
        if include_vector:
            vector_kwargs = {"model": embedding_model} if embedding_model else {}
            candidates.extend(
                _tag_agentic_results(
                    search_vectors(
                        conn,
                        planned_query.query,
                        limit=per_query_limit,
                        filters=plan.filters,
                        **vector_kwargs,
                    ),
                    planned_query,
                    index,
                    plan,
                )
            )
    return candidates


def plan_agentic_search(
    query: str,
    *,
    filters: SearchFilters | None = None,
    max_queries: int = 3,
) -> AgenticSearchPlan:
    filters = filters or SearchFilters()
    try:
        prompt = build_agentic_search_prompt(
            query,
            filters=filters,
            max_queries=max_queries,
        )
        payload = _call_gemini_json(prompt, AGENTIC_SEARCH_RESPONSE_SCHEMA)
        planned_queries = _coerce_queries(
            payload.get("queries"),
            original_query=query,
            max_queries=max_queries,
        )
        planned_filters = _coerce_filters(payload.get("filters"), base_filters=filters)
        return AgenticSearchPlan(
            queries=planned_queries,
            filters=planned_filters,
            reason=str(payload.get("reason") or ""),
            mode="llm",
            raw=payload,
        )
    except Exception as exc:
        return AgenticSearchPlan(
            queries=[],
            filters=filters,
            reason=f"Agentic search planner failed; skipped agentic search. error={exc}",
            mode="fallback",
        )


def build_agentic_search_prompt(
    query: str,
    *,
    filters: SearchFilters,
    max_queries: int,
) -> str:
    return "\n".join(
        [
            "# Role",
            "You are a small search agent inside an internal audit/legal RAG system.",
            "You do not answer the user and you do not write SQL.",
            "",
            "# Situation",
            "The database stores internal document chunks from policies, legal opinions,",
            "system manuals, and audit knowledge documents. Python will run safe keyword,",
            "metadata, and vector searches after your plan is validated.",
            "",
            "# Task",
            "Rewrite the user's search need into a few high-value retrieval queries that may",
            "find evidence missed by exact keyword search.",
            "",
            "# Search Rules",
            f"- Return at most {max_queries} extra queries.",
            "- Use Traditional Chinese if the user query is Chinese.",
            "- Prefer terms likely to appear in formal internal documents.",
            "- Expand synonyms and formal legal/audit wording, but keep each query specific.",
            "- Do not produce SQL, table names, column names, or database instructions.",
            "- Do not answer the question.",
            "- Allowed filter keys: document_type, status, source_system, language.",
            "- Do not loosen filters already provided in Current Input.",
            "",
            "# Output Format",
            "Return only valid JSON. Do not include markdown, comments, or extra text.",
            "The JSON object must match this shape:",
            "{",
            '  "reason": "brief Traditional Chinese reason for the search expansion",',
            '  "queries": [',
            '    {"query": "expanded search query", "purpose": "synonym_expansion"}',
            "  ],",
            '  "filters": {"status": "active", "language": "zh-TW"}',
            "}",
            "Allowed purpose values: synonym_expansion, legal_term_expansion, document_phrase_match, metadata_focus.",
            "",
            "# Examples",
            "Example 1 input:",
            'query: "資料共享是否需要告知客戶?"',
            "Example 1 output:",
            "{",
            '  "reason": "問題聚焦資料共享的告知與同意義務，應補充正式文件常見用語。",',
            '  "queries": [',
            '    {"query": "資料共享 個資應告知事項 契據文件", "purpose": "document_phrase_match"},',
            '    {"query": "客戶資料共享 告知義務 客戶同意", "purpose": "legal_term_expansion"},',
            '    {"query": "個人資料 共享使用 當事人知悉", "purpose": "synonym_expansion"}',
            "  ],",
            '  "filters": {"status": "active", "language": "zh-TW"}',
            "}",
            "",
            "Example 2 input:",
            'query: "AI服務要揭露什麼?"',
            "Example 2 output:",
            "{",
            '  "reason": "問題聚焦 AI 服務揭露內容，應搜尋資訊揭露、使用限制與客戶告知相關詞。",',
            '  "queries": [',
            '    {"query": "AI 服務 資訊揭露 客戶告知", "purpose": "legal_term_expansion"},',
            '    {"query": "生成式 AI 使用限制 風險揭露", "purpose": "document_phrase_match"}',
            "  ],",
            '  "filters": {"status": "active", "language": "zh-TW"}',
            "}",
            "",
            "# Current Input",
            f"query: {query}",
            f"filters: {json.dumps(_filters_to_dict(filters), ensure_ascii=False)}",
        ]
    )


def _call_gemini_json(prompt: str, response_schema: dict[str, Any]) -> dict[str, Any]:
    api_key, model_name = load_gemini_settings()
    model = create_gemini_model(api_key, model_name)
    response = model.generate_content(
        prompt,
        generation_config={
            "response_mime_type": "application/json",
            "response_schema": response_schema,
        },
    )
    text = str(getattr(response, "text", "") or response).strip()
    payload = _extract_json_object(text)
    if not isinstance(payload, dict):
        raise ValueError("agentic search response JSON root must be an object")
    return payload


def _extract_json_object(text: str) -> Any:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start < 0 or end <= start:
            raise
        return json.loads(cleaned[start : end + 1])


def _coerce_queries(
    raw_queries: Any,
    *,
    original_query: str,
    max_queries: int,
) -> list[AgenticSearchQuery]:
    if not isinstance(raw_queries, list):
        return []
    original_normalized = _normalize_query(original_query)
    queries: list[AgenticSearchQuery] = []
    seen = {original_normalized}
    for raw_query in raw_queries:
        if not isinstance(raw_query, dict):
            continue
        query = _clean_query(raw_query.get("query"))
        if not query:
            continue
        normalized = _normalize_query(query)
        if normalized in seen:
            continue
        purpose = str(raw_query.get("purpose") or "synonym_expansion").strip()
        if purpose not in ALLOWED_PURPOSES:
            purpose = "synonym_expansion"
        queries.append(AgenticSearchQuery(query=query, purpose=purpose))
        seen.add(normalized)
        if len(queries) >= max(0, max_queries):
            break
    return queries


def _coerce_filters(raw_filters: Any, *, base_filters: SearchFilters) -> SearchFilters:
    candidate = raw_filters if isinstance(raw_filters, dict) else {}
    clean = {
        key: _clean_filter_value(candidate.get(key))
        for key in ALLOWED_FILTERS
    }
    return SearchFilters(
        document_type=base_filters.document_type or clean.get("document_type"),
        status=base_filters.status or clean.get("status"),
        source_system=base_filters.source_system or clean.get("source_system"),
        language=base_filters.language or clean.get("language"),
        is_latest=base_filters.is_latest,
    )


def _tag_agentic_results(
    results: list[SearchResult],
    planned_query: AgenticSearchQuery,
    index: int,
    plan: AgenticSearchPlan,
) -> list[SearchResult]:
    for result in results:
        if "agentic" not in result.match_sources:
            result.match_sources.append("agentic")
        purpose_source = f"agentic_{planned_query.purpose}"
        if purpose_source not in result.match_sources:
            result.match_sources.append(purpose_source)
        result.score_details["agentic_score"] = max(
            result.score_details.get("agentic_score", 0.0),
            result.score,
        )
        result.score_details["agentic_query_index"] = float(index)
        result.score_details["agentic_mode_llm"] = 1.0 if plan.mode == "llm" else 0.0
    return results


def _clean_query(value: Any) -> str:
    query = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(query) > 160:
        query = query[:160].strip()
    if not query or _looks_like_sql(query):
        return ""
    return query


def _looks_like_sql(value: str) -> bool:
    lowered = value.lower()
    return bool(
        re.search(
            r"\b(select|insert|update|delete|drop|alter|truncate|from|where|join)\b",
            lowered,
        )
    )


def _clean_filter_value(value: Any) -> str | None:
    if value is None:
        return None
    text = re.sub(r"\s+", " ", str(value)).strip()
    if not text or len(text) > 80 or _looks_like_sql(text):
        return None
    return text


def _normalize_query(query: str) -> str:
    return re.sub(r"\s+", " ", query).strip().lower()


def _filters_to_dict(filters: SearchFilters) -> dict[str, str]:
    return {
        key: value
        for key, value in {
            "document_type": filters.document_type,
            "status": filters.status,
            "source_system": filters.source_system,
            "language": filters.language,
        }.items()
        if value
    }
