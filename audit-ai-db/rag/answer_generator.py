from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from ingestion.gemini.reader import (
    create_gemini_model,
    load_gemini_settings,
)
from ingestion.models import IngestionError
from rag.context_builder import RAGContext


@dataclass(frozen=True)
class RAGAnswer:
    answer: str
    model: str
    citations: list[str]
    raw_payload: dict[str, Any] | None = None


ANSWER_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "answer": {"type": "string"},
        "citations": {
            "type": "array",
            "items": {"type": "string"},
        },
    },
    "required": ["answer", "citations"],
}


def generate_answer(context: RAGContext) -> RAGAnswer:
    if not context.sources:
        return RAGAnswer(
            answer="目前沒有找到足夠的資料來源，無法根據已匯入文件回答此問題。",
            model="none",
            citations=[],
        )

    api_key, model_name = load_gemini_settings()
    model = create_gemini_model(api_key, model_name)
    try:
        response = model.generate_content(
            _structured_answer_prompt(context.prompt),
            generation_config={
                "response_mime_type": "application/json",
                "response_schema": ANSWER_RESPONSE_SCHEMA,
            },
        )
    except Exception as exc:
        raise IngestionError("rag_answer_generation", f"Gemini answer generation failed: {exc}") from exc

    text = getattr(response, "text", None)
    try:
        payload = _extract_json_object(str(text or response).strip())
    except Exception as exc:
        raise IngestionError(
            "rag_answer_generation",
            f"Gemini answer JSON parsing failed: {exc}",
        ) from exc
    if not isinstance(payload, dict):
        raise IngestionError("rag_answer_generation", "Gemini answer JSON root must be an object")

    answer = str(payload.get("answer") or "").strip()
    citations = [
        str(label)
        for label in payload.get("citations", [])
        if isinstance(label, str)
    ]
    if not answer:
        raise IngestionError("rag_answer_generation", "Gemini answer JSON missing non-empty answer")
    return RAGAnswer(
        answer=answer,
        model=model_name,
        citations=_dedupe_labels(citations),
        raw_payload=payload,
    )


def _structured_answer_prompt(prompt: str) -> str:
    return "\n".join(
        [
            prompt,
            "",
            "Structured output requirements:",
            "- Return only valid JSON.",
            "- JSON shape: {\"answer\": string, \"citations\": string[]}.",
            "- citations must contain only labels that directly support the answer, for example S1 or S2.",
            "- If the sources are insufficient, answer that the retrieved documents cannot determine the answer and use an empty citations array.",
        ]
    )


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


def _dedupe_labels(labels: list[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for label in labels:
        if label in seen:
            continue
        seen.add(label)
        unique.append(label)
    return unique
