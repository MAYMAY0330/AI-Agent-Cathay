from __future__ import annotations

import json
import re
from typing import Any

from agent.llm_agent.prompts import build_evidence_judge_prompt, build_planner_prompt
from agent.state import EvidenceBundle, SearchTask, VerificationResult
from ingestion.gemini.reader import create_gemini_model, load_gemini_settings


PLANNER_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "reasoning": {"type": "string"},
        "search_tasks": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "purpose": {
                        "type": "string",
                        "enum": [
                            "direct_question",
                            "keyword_compaction",
                            "domain_expansion",
                            "retry_refinement",
                        ],
                    },
                },
                "required": ["query", "purpose"],
            },
        },
    },
    "required": ["reasoning", "search_tasks"],
}

EVIDENCE_JUDGE_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "is_sufficient": {"type": "boolean"},
        "reason": {"type": "string"},
        "supporting_labels": {
            "type": "array",
            "items": {"type": "string"},
        },
        "refined_query": {"type": "string"},
    },
    "required": ["is_sufficient", "reason", "supporting_labels", "refined_query"],
}


def plan_search_tasks_with_llm(
    normalized_question: str,
    *,
    keywords: list[str],
    limit: int,
    filters: dict[str, Any],
    iteration: int,
    refined_query: str | None,
    fallback_tasks: list[SearchTask],
) -> dict[str, Any]:
    try:
        payload = _call_gemini_json(
            build_planner_prompt(
                normalized_question,
                keywords=keywords,
                filters=filters,
                limit=limit,
                iteration=iteration,
                refined_query=refined_query,
            ),
            PLANNER_RESPONSE_SCHEMA,
        )
        raw_tasks = payload.get("search_tasks")
        if not isinstance(raw_tasks, list):
            raise ValueError("search_tasks must be a list")
        tasks = _coerce_llm_search_tasks(
            raw_tasks,
            fallback=fallback_tasks,
            filters=_clean_filters(filters),
            limit=limit,
            iteration=iteration,
        )
        return {
            "tasks": tasks,
            "decision": {
                "kind": "planner",
                "mode": "llm",
                "iteration": iteration,
                "reasoning": str(payload.get("reasoning") or ""),
                "raw": payload,
            },
        }
    except Exception as exc:
        return {
            "tasks": fallback_tasks,
            "decision": {
                "kind": "planner",
                "mode": "fallback",
                "iteration": iteration,
                "reasoning": f"LLM planner failed; used deterministic planner. error={exc}",
            },
        }


def judge_evidence_with_llm(
    question: str,
    bundle: EvidenceBundle,
    *,
    deterministic: VerificationResult,
) -> dict[str, Any]:
    if not bundle.sources:
        return {
            "is_sufficient": False,
            "reason": deterministic.reason or "No selected sources.",
            "supporting_labels": [],
            "refined_query": "",
            "mode": "deterministic_guard",
        }

    try:
        payload = _call_gemini_json(
            build_evidence_judge_prompt(question, bundle),
            EVIDENCE_JUDGE_RESPONSE_SCHEMA,
        )
        is_sufficient = bool(payload.get("is_sufficient"))
        supporting_labels = [
            str(label)
            for label in payload.get("supporting_labels", [])
            if isinstance(label, str)
        ]
        source_labels = {source.label for source in bundle.sources}
        supporting_labels = [label for label in supporting_labels if label in source_labels]
        refined_query = str(payload.get("refined_query") or "").strip()
        return {
            "is_sufficient": is_sufficient,
            "reason": str(payload.get("reason") or ""),
            "supporting_labels": supporting_labels,
            "refined_query": refined_query,
            "mode": "llm",
            "raw": payload,
        }
    except Exception as exc:
        return {
            "is_sufficient": deterministic.valid,
            "reason": f"LLM evidence judge failed; used deterministic result. error={exc}",
            "supporting_labels": [source.label for source in bundle.sources],
            "refined_query": "",
            "mode": "fallback",
        }


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
    payload = extract_json_object(text)
    if not isinstance(payload, dict):
        raise ValueError("LLM response JSON root must be an object")
    return payload


def extract_json_object(text: str) -> Any:
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


def _coerce_llm_search_tasks(
    raw_tasks: list[Any],
    *,
    fallback: list[SearchTask],
    filters: dict[str, Any],
    limit: int,
    iteration: int,
) -> list[SearchTask]:
    tasks: list[SearchTask] = []
    for index, raw_task in enumerate(raw_tasks[:3], start=1):
        if not isinstance(raw_task, dict):
            continue
        query = str(raw_task.get("query") or "").strip()
        if not query:
            continue
        purpose = str(raw_task.get("purpose") or _task_purpose(index, iteration)).strip()
        tasks.append(
            SearchTask(
                task_id=f"llm_search_{iteration}_{index}",
                query=query,
                purpose=purpose[:80],
                limit=limit,
                filters=filters,
            )
        )
    return tasks or fallback


def _task_purpose(index: int, iteration: int) -> str:
    if index == 1:
        return "direct_question" if iteration == 1 else "retry_keyword_focus"
    if index == 2:
        return "keyword_compaction"
    return "domain_expansion"


def _clean_filters(filters: dict[str, Any]) -> dict[str, Any]:
    allowed = {"document_type", "status", "source_system", "language"}
    return {key: value for key, value in filters.items() if key in allowed and value}
