from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from rag.context_builder import ContextSource, RAGContext
from rag.search_models import SearchResult


@dataclass(frozen=True)
class SearchTask:
    task_id: str
    query: str
    purpose: str
    limit: int
    filters: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class EvidenceBundle:
    sources: list[ContextSource]
    selected_results: list[SearchResult]
    all_results_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "sources": [asdict(source) for source in self.sources],
            "selected_results": [asdict(result) for result in self.selected_results],
            "all_results_count": self.all_results_count,
        }


@dataclass(frozen=True)
class AgentAnswer:
    status: str
    answer: str
    model: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class VerificationResult:
    valid: bool
    cited_labels: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AgentState:
    run_id: str
    question: str
    normalized_question: str = ""
    keywords: list[str] = field(default_factory=list)
    inferred_filters: dict[str, Any] = field(default_factory=dict)
    search_tasks: list[SearchTask] = field(default_factory=list)
    retrieved_results: list[SearchResult] = field(default_factory=list)
    evidence_bundle: EvidenceBundle | None = None
    rag_context: RAGContext | None = None
    answer: AgentAnswer | None = None
    verification: VerificationResult | None = None
    status: str = "initialized"
    iterations: int = 0
    started_at: str = ""
    finished_at: str = ""
    log_path: str | None = None

    def to_dict(self, *, include_prompt: bool = False) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "run_id": self.run_id,
            "question": self.question,
            "normalized_question": self.normalized_question,
            "keywords": self.keywords,
            "inferred_filters": self.inferred_filters,
            "search_tasks": [task.to_dict() for task in self.search_tasks],
            "sources": (
                [asdict(source) for source in self.evidence_bundle.sources]
                if self.evidence_bundle
                else []
            ),
            "answer": self.answer.to_dict() if self.answer else None,
            "verification": self.verification.to_dict() if self.verification else None,
            "status": self.status,
            "iterations": self.iterations,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "log_path": self.log_path,
        }
        if include_prompt and self.rag_context is not None:
            payload["prompt"] = self.rag_context.prompt
        return payload


@dataclass(frozen=True)
class AgentRunLog:
    run_id: str
    started_at: str
    finished_at: str
    question: str
    normalized_question: str
    status: str
    search_tasks: list[dict[str, Any]]
    sources: list[dict[str, Any]]
    answer: dict[str, Any] | None
    verification: dict[str, Any] | None
    iterations: int
    dry_run: bool
    model: str | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
