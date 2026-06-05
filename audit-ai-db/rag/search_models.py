from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class SearchFilters:
    document_type: str | None = None
    status: str | None = "active"
    source_system: str | None = None
    language: str | None = None


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
    score_details: dict[str, float] = field(default_factory=dict)

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
        )

    def merge(self, other: "SearchResult") -> None:
        self.score = max(self.score, other.score)
        for source in other.match_sources:
            if source not in self.match_sources:
                self.match_sources.append(source)
        self.score_details.update(other.score_details)

