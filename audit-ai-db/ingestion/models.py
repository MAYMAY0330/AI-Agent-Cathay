from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


class IngestionError(Exception):
    """Pipeline error with the stage that should be written to ingestion_logs."""

    def __init__(self, stage: str, message: str, status: str = "failed") -> None:
        super().__init__(message)
        self.stage = stage
        self.message = message
        self.status = status


@dataclass(frozen=True)
class FileInfo:
    file_path: Path
    file_name: str
    file_extension: str
    file_size: int
    file_type: str


@dataclass(frozen=True)
class DocumentMetadata:
    internal_code: str
    title: str
    document_type: str
    data_type: str
    source_system: str
    source_record_id: str | None
    source_url: str | None
    storage_path: str
    original_file_name: str
    file_type: str
    language: str
    status: str
    system_category: str | None = None
    responsible_unit: str | None = None
    short_summary: str | None = None
    keywords: list[str] = field(default_factory=list)
    main_topics: list[str] = field(default_factory=list)

    def document_values(self) -> dict[str, Any]:
        return {
            "internal_code": self.internal_code,
            "title": self.title,
            "document_type": self.document_type,
            "data_type": self.data_type,
            "short_summary": self.short_summary,
            "keywords": self.keywords or None,
            "main_topics": self.main_topics or None,
            "system_category": self.system_category,
            "responsible_unit": self.responsible_unit,
            "source_system": self.source_system,
            "source_record_id": self.source_record_id,
            "source_url": self.source_url,
            "storage_path": self.storage_path,
            "original_file_name": self.original_file_name,
            "file_type": self.file_type,
            "language": self.language,
            "status": self.status,
        }


@dataclass(frozen=True)
class TextBlock:
    block_index: int
    text: str
    style: str = "paragraph"
    page: int | None = None


@dataclass(frozen=True)
class StructuredSection:
    section_index: int
    text: str
    chunk_level: str
    source_structure_type: str
    heading_path: str | None = None
    section_title: str | None = None
    clause_number: str | None = None
    page_start: int | None = None
    page_end: int | None = None


@dataclass(frozen=True)
class StructureResult:
    sections: list[StructuredSection]
    used_fallback: bool = False
    warning: str | None = None


@dataclass(frozen=True)
class ChunkRecord:
    chunk_index: int
    chunk_level: str
    source_structure_type: str
    heading_path: str | None
    section_title: str | None
    clause_number: str | None
    page_start: int | None
    page_end: int | None
    chunk_text: str
    token_count: int
    char_count: int
    parent_chunk_id: Any | None = None


@dataclass(frozen=True)
class SummaryResult:
    short_summary: str | None
    keywords: list[str]
    main_topics: list[str]
    summary_generated: bool


@dataclass(frozen=True)
class VersionDecision:
    action: str
    document_id: Any | None = None
    current_version_id: Any | None = None
    next_version_label: str = "v1"

    @property
    def is_duplicate(self) -> bool:
        return self.action == "duplicate"

