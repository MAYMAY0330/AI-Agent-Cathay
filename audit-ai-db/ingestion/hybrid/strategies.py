from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from ingestion.models import FileInfo, IngestionError


IngestionStrategy = Literal["auto", "local", "gemini"]
SelectedStrategy = Literal["local", "gemini"]

SUPPORTED_STRATEGIES = {"auto", "local", "gemini"}


@dataclass(frozen=True)
class PdfPageStats:
    pages: int
    total_text_chars: int
    pages_with_images: int
    low_text_pages: int
    low_text_image_pages: int

    @property
    def average_text_chars(self) -> float:
        if self.pages == 0:
            return 0.0
        return self.total_text_chars / self.pages

    def to_dict(self) -> dict[str, Any]:
        return {
            "pages": self.pages,
            "total_text_chars": self.total_text_chars,
            "average_text_chars": round(self.average_text_chars, 2),
            "pages_with_images": self.pages_with_images,
            "low_text_pages": self.low_text_pages,
            "low_text_image_pages": self.low_text_image_pages,
        }


@dataclass(frozen=True)
class StrategyDecision:
    requested_strategy: IngestionStrategy
    selected_strategy: SelectedStrategy
    reason: str
    analysis: dict[str, Any]


def choose_ingestion_strategy(
    file_info: FileInfo,
    requested_strategy: str,
    *,
    max_pages: int | None = None,
) -> StrategyDecision:
    strategy = _normalize_strategy(requested_strategy)
    if strategy == "local":
        return StrategyDecision(
            requested_strategy=strategy,
            selected_strategy="local",
            reason="forced_local",
            analysis={},
        )
    if strategy == "gemini":
        return StrategyDecision(
            requested_strategy=strategy,
            selected_strategy="gemini",
            reason="forced_gemini",
            analysis={},
        )

    if max_pages is not None:
        return StrategyDecision(
            requested_strategy="auto",
            selected_strategy="gemini",
            reason="max_pages_requires_gemini_preview",
            analysis={"max_pages": max_pages},
        )

    if file_info.file_type == "docx":
        return StrategyDecision(
            requested_strategy="auto",
            selected_strategy="local",
            reason="docx_text_first",
            analysis={"file_type": file_info.file_type},
        )

    if file_info.file_type == "pdf":
        try:
            stats = analyze_pdf_for_strategy(file_info.file_path)
        except IngestionError as exc:
            return StrategyDecision(
                requested_strategy="auto",
                selected_strategy="local",
                reason="pdf_analysis_unavailable_try_local",
                analysis={"error": exc.message},
            )
        selected, reason = select_pdf_strategy(stats)
        return StrategyDecision(
            requested_strategy="auto",
            selected_strategy=selected,
            reason=reason,
            analysis=stats.to_dict(),
        )

    return StrategyDecision(
        requested_strategy="auto",
        selected_strategy="local",
        reason="unsupported_auto_type_try_local_error_path",
        analysis={"file_type": file_info.file_type},
    )


def analyze_pdf_for_strategy(file_path: Path) -> PdfPageStats:
    try:
        import fitz
    except ImportError as exc:
        raise IngestionError(
            "hybrid_strategy",
            "PyMuPDF is required for PDF strategy analysis",
        ) from exc

    try:
        document = fitz.open(str(file_path))
    except Exception as exc:
        raise IngestionError("hybrid_strategy", f"unable to open PDF: {exc}") from exc

    page_count = document.page_count
    total_text_chars = 0
    pages_with_images = 0
    low_text_pages = 0
    low_text_image_pages = 0
    try:
        for page_index in range(document.page_count):
            page = document.load_page(page_index)
            text_chars = len(page.get_text("text").strip())
            image_count = len(page.get_images(full=True))
            total_text_chars += text_chars
            if image_count > 0:
                pages_with_images += 1
            if text_chars < 120:
                low_text_pages += 1
                if image_count > 0:
                    low_text_image_pages += 1
    finally:
        document.close()

    return PdfPageStats(
        pages=page_count,
        total_text_chars=total_text_chars,
        pages_with_images=pages_with_images,
        low_text_pages=low_text_pages,
        low_text_image_pages=low_text_image_pages,
    )


def select_pdf_strategy(stats: PdfPageStats) -> tuple[SelectedStrategy, str]:
    if stats.pages == 0:
        return "local", "empty_pdf_try_local_error_path"

    image_page_ratio = stats.pages_with_images / stats.pages
    low_text_image_ratio = stats.low_text_image_pages / stats.pages

    if stats.total_text_chars < 500 and stats.pages_with_images > 0:
        return "gemini", "pdf_mostly_images"
    if low_text_image_ratio >= 0.25:
        return "gemini", "pdf_low_text_image_pages"
    if stats.average_text_chars < 120 and image_page_ratio >= 0.5:
        return "gemini", "pdf_image_heavy_low_text"
    return "local", "pdf_text_rich"


def _normalize_strategy(value: str) -> IngestionStrategy:
    normalized = value.strip().lower()
    if normalized not in SUPPORTED_STRATEGIES:
        raise IngestionError(
            "hybrid_configuration",
            f"strategy must be one of {sorted(SUPPORTED_STRATEGIES)}, got: {value}",
        )
    return normalized  # type: ignore[return-value]
