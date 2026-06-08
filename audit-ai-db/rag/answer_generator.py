from __future__ import annotations

from dataclasses import dataclass

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


def generate_answer(context: RAGContext) -> RAGAnswer:
    if not context.sources:
        return RAGAnswer(
            answer="目前沒有找到足夠的資料來源，無法根據已匯入文件回答此問題。",
            model="none",
        )

    api_key, model_name = load_gemini_settings()
    model = create_gemini_model(api_key, model_name)
    try:
        response = model.generate_content(context.prompt)
    except Exception as exc:
        raise IngestionError("rag_answer_generation", f"Gemini answer generation failed: {exc}") from exc

    text = getattr(response, "text", None)
    if text:
        return RAGAnswer(answer=str(text).strip(), model=model_name)

    return RAGAnswer(answer=str(response).strip(), model=model_name)
