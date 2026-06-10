from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class SearchFilters:
    document_type: str | None = None
    status: str | None = "active"
    source_system: str | None = None
    language: str | None = None
    is_latest: bool | None = True


@dataclass
class SearchResult:
    chunk_id: str
    document_id: str
    version_id: str
    internal_code: str | None
    title: str
    document_type: str
    source_system: str | None
    section_title: str | None
    heading_path: str | None
    clause_number: str | None
    page_start: int | None
    page_end: int | None
    chunk_index: int
    chunk_text: str
    score: float
    match_sources: list[str] = field(default_factory=list)
    score_details: dict[str, Any] = field(default_factory=dict)
    parent_chunk_id: str | None = None
    matched_chunk_id: str | None = None
    matched_chunk_text: str | None = None
    source_chunk_id: str | None = None
    matched_text_preview: str | None = None

    def __post_init__(self) -> None:
        if self.source_chunk_id is None:
            self.source_chunk_id = self.chunk_id
        if self.matched_text_preview is None and self.matched_chunk_text:
            self.matched_text_preview = _preview(self.matched_chunk_text)

    @classmethod
    def from_row(
        cls,
        row: dict[str, Any],
        *,
        match_sources: list[str],
        score_details: dict[str, float] | None = None,
    ) -> "SearchResult":
        return cls(
            chunk_id=str(row["chunk_id"]),
            document_id=str(row["document_id"]),
            version_id=str(row["version_id"]),
            internal_code=row.get("internal_code"),
            title=str(row["title"]),
            document_type=str(row["document_type"]),
            source_system=row.get("source_system"),
            section_title=row.get("section_title"),
            heading_path=row.get("heading_path"),
            clause_number=row.get("clause_number"),
            page_start=row.get("page_start"),
            page_end=row.get("page_end"),
            chunk_index=int(row.get("chunk_index") or 0),
            chunk_text=str(row["chunk_text"]),
            score=float(row.get("score") or 0),
            match_sources=match_sources,
            score_details=score_details or {},
            parent_chunk_id=(
                str(row["parent_chunk_id"]) if row.get("parent_chunk_id") else None
            ),
            matched_chunk_id=(
                str(row["matched_chunk_id"]) if row.get("matched_chunk_id") else None
            ),
            matched_chunk_text=row.get("matched_chunk_text"),
            source_chunk_id=str(row["chunk_id"]),
            matched_text_preview=_preview(row.get("matched_chunk_text")),
        )

    def merge(self, other: "SearchResult") -> None:
        self.score = max(self.score, other.score)
        for source in other.match_sources:
            if source not in self.match_sources:
                self.match_sources.append(source)
        self.score_details.update(other.score_details)
        if self.matched_chunk_id is None:
            self.matched_chunk_id = other.matched_chunk_id
        if self.matched_chunk_text is None:
            self.matched_chunk_text = other.matched_chunk_text
        if self.matched_text_preview is None:
            self.matched_text_preview = other.matched_text_preview


def _preview(text: str | None, *, limit: int = 180) -> str | None:
    if not text:
        return None
    clean = " ".join(str(text).split())
    if len(clean) <= limit:
        return clean
    return clean[: max(0, limit - 3)] + "..."
