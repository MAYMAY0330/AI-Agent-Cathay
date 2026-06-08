from __future__ import annotations

import os
from pathlib import Path

from ingestion.config import _load_dotenv_file
from ingestion.models import IngestionError


DEFAULT_EMBEDDING_MODEL = "gemini-embedding-001"
DEFAULT_EMBEDDING_DIMENSION = 1536


def load_embedding_settings() -> tuple[str, str, int]:
    project_root = Path(__file__).resolve().parents[1]
    _load_dotenv_file(project_root / ".env")

    api_key = os.getenv("GEMINI_API_KEY")
    model = os.getenv("GEMINI_EMBEDDING_MODEL", DEFAULT_EMBEDDING_MODEL)
    dimension = int(os.getenv("GEMINI_EMBEDDING_DIMENSION", str(DEFAULT_EMBEDDING_DIMENSION)))

    if not api_key:
        raise IngestionError(
            "embedding_configuration",
            "GEMINI_API_KEY is required in .env for Gemini embeddings",
        )
    if dimension != DEFAULT_EMBEDDING_DIMENSION:
        raise IngestionError(
            "embedding_configuration",
            (
                "GEMINI_EMBEDDING_DIMENSION must be 1536 because "
                "chunk_embeddings.embedding is vector(1536)"
            ),
        )

    return api_key, model, dimension


def embed_text(
    text: str,
    *,
    task_type: str,
    model: str | None = None,
    dimension: int | None = None,
) -> list[float]:
    if not text.strip():
        raise IngestionError("embedding_generation", "text to embed must not be empty")

    api_key, configured_model, configured_dimension = load_embedding_settings()
    model_name = model or configured_model
    output_dimension = dimension or configured_dimension
    try:
        import google.generativeai as genai
    except ImportError as exc:
        raise IngestionError(
            "embedding_configuration",
            "google-generativeai is required. Install dependencies with: pip install -r requirements.txt",
        ) from exc

    genai.configure(api_key=api_key, transport="rest")
    try:
        response = genai.embed_content(
            model=model_name,
            content=text,
            task_type=task_type,
            output_dimensionality=output_dimension,
        )
    except TypeError:
        response = genai.embed_content(
            model=model_name,
            content=text,
            task_type=task_type,
        )
    except Exception as exc:
        raise IngestionError("embedding_generation", f"Gemini embedding failed: {exc}") from exc

    embedding = _extract_embedding(response)
    if len(embedding) != output_dimension:
        raise IngestionError(
            "embedding_generation",
            f"expected embedding dimension {output_dimension}, got {len(embedding)}",
        )
    return embedding


def _extract_embedding(response) -> list[float]:
    if isinstance(response, dict):
        raw = response.get("embedding")
    else:
        raw = getattr(response, "embedding", None)

    if raw is None:
        raise IngestionError("embedding_generation", "Gemini embedding response has no embedding")

    return [float(value) for value in raw]


def embedding_to_pgvector(embedding: list[float]) -> str:
    return "[" + ",".join(f"{value:.9g}" for value in embedding) + "]"
