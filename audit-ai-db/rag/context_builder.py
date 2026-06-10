from __future__ import annotations

from dataclasses import dataclass

from rag.search_models import SearchResult


@dataclass(frozen=True)
class ContextSource:
    label: str
    chunk_id: str
    source_chunk_id: str | None
    matched_chunk_id: str | None
    matched_text_preview: str | None
    title: str
    internal_code: str | None
    document_type: str
    section_title: str | None
    heading_path: str | None
    clause_number: str | None
    page_start: int | None
    page_end: int | None
    score: float
    match_sources: list[str]
    text: str


@dataclass(frozen=True)
class RAGContext:
    question: str
    prompt: str
    sources: list[ContextSource]


def build_rag_context(
    question: str,
    results: list[SearchResult],
    *,
    max_sources: int = 6,
    max_context_chars: int = 12000,
    preserve_order: bool = False,
) -> RAGContext:
    sources: list[ContextSource] = []
    prompt_parts = [
        "You are an internal audit/legal knowledge assistant.",
        "Answer in Traditional Chinese.",
        "Use only the provided sources. Do not invent facts.",
        "If the sources are insufficient, say you cannot determine the answer from the retrieved documents.",
        "Cite sources inline using labels like [S1], [S2].",
        "",
        f"Question:\n{question.strip()}",
        "",
        "Sources:",
    ]

    used_chars = 0
    if preserve_order:
        evidence_results = results
    else:
        evidence_results = sorted(
            results,
            key=lambda result: (
                1 if _has_chunk_evidence(result) else 0,
                result.score,
            ),
            reverse=True,
        )
    for index, result in enumerate(evidence_results[:max_sources], start=1):
        remaining = max_context_chars - used_chars
        if remaining <= 0:
            break

        text = _truncate(result.chunk_text, remaining)
        label = f"S{index}"
        source = ContextSource(
            label=label,
            chunk_id=result.chunk_id,
            source_chunk_id=result.source_chunk_id or result.chunk_id,
            matched_chunk_id=result.matched_chunk_id,
            matched_text_preview=result.matched_text_preview,
            title=result.title,
            internal_code=result.internal_code,
            document_type=result.document_type,
            section_title=result.section_title,
            heading_path=result.heading_path,
            clause_number=result.clause_number,
            page_start=result.page_start,
            page_end=result.page_end,
            score=result.score,
            match_sources=result.match_sources,
            text=text,
        )
        sources.append(source)
        used_chars += len(text)

        prompt_parts.extend(
            [
                "",
                f"[{label}]",
                f"title: {source.title}",
                f"internal_code: {source.internal_code or '-'}",
                f"document_type: {source.document_type}",
                f"section: {source.section_title or source.heading_path or '-'}",
                f"clause: {source.clause_number or '-'}",
                f"page: {_format_page_range(source.page_start, source.page_end)}",
                f"retrieval_score: {source.score:.4f}",
                "text:",
                text,
            ]
        )

    prompt_parts.extend(
        [
            "",
            "Answer requirements:",
            "- Give a concise answer first.",
            "- Then list the supporting source labels.",
            "- Do not cite a source unless it directly supports the statement.",
        ]
    )

    return RAGContext(
        question=question,
        prompt="\n".join(prompt_parts).strip(),
        sources=sources,
    )


def _truncate(text: str, limit: int) -> str:
    clean = text.strip()
    if len(clean) <= limit:
        return clean
    return clean[: max(0, limit - 20)].rstrip() + "\n[內容因長度限制截斷]"


def _has_chunk_evidence(result: SearchResult) -> bool:
    return "keyword" in result.match_sources or "vector" in result.match_sources


def _format_page_range(page_start: int | None, page_end: int | None) -> str:
    if page_start is None and page_end is None:
        return "-"
    if page_start == page_end or page_end is None:
        return str(page_start)
    if page_start is None:
        return str(page_end)
    return f"{page_start}-{page_end}"
