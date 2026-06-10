from __future__ import annotations

import re

from ingestion.models import ChunkRecord, StructuredSection


CJK_RE = re.compile(r"[\u4e00-\u9fff]")
ASCII_WORD_RE = re.compile(r"[A-Za-z0-9_]+")


def estimate_token_count(text: str) -> int:
    cjk_count = len(CJK_RE.findall(text))
    ascii_word_count = len(ASCII_WORD_RE.findall(text))
    punctuation_count = max(0, len(text) - cjk_count) // 12
    return max(1, cjk_count + ascii_word_count + punctuation_count)


def create_chunks(
    sections: list[StructuredSection],
    target_tokens: int = 800,
    max_tokens: int = 1200,
    overlap_tokens: int = 100,
    hierarchical: bool = True,
    child_target_tokens: int = 250,
    child_max_tokens: int = 350,
    child_overlap_tokens: int = 40,
) -> list[ChunkRecord]:
    if hierarchical:
        return create_hierarchical_chunks(
            sections,
            child_target_tokens=child_target_tokens,
            child_max_tokens=child_max_tokens,
            child_overlap_tokens=child_overlap_tokens,
        )

    chunks: list[ChunkRecord] = []

    for section in sections:
        parts = _split_section_text(
            section.text,
            target_tokens=target_tokens,
            max_tokens=max_tokens,
            overlap_tokens=overlap_tokens,
        )
        for part_index, part in enumerate(parts, start=1):
            title = section.section_title
            if len(parts) > 1 and title:
                title = f"{title} ({part_index}/{len(parts)})"

            chunks.append(
                ChunkRecord(
                    chunk_index=len(chunks) + 1,
                    chunk_level=section.chunk_level,
                    source_structure_type=section.source_structure_type,
                    heading_path=section.heading_path,
                    section_title=title,
                    clause_number=section.clause_number,
                    page_start=section.page_start,
                    page_end=section.page_end,
                    chunk_text=part,
                    token_count=estimate_token_count(part),
                    char_count=len(part),
                )
            )

    return chunks


def create_hierarchical_chunks(
    sections: list[StructuredSection],
    *,
    child_target_tokens: int = 250,
    child_max_tokens: int = 350,
    child_overlap_tokens: int = 40,
) -> list[ChunkRecord]:
    chunks: list[ChunkRecord] = []

    for section in sections:
        text = section.text.strip()
        if not text:
            continue

        parent_index = len(chunks) + 1
        chunks.append(
            ChunkRecord(
                chunk_index=parent_index,
                chunk_level="parent",
                source_structure_type=section.source_structure_type or section.chunk_level,
                heading_path=section.heading_path,
                section_title=section.section_title,
                clause_number=section.clause_number,
                page_start=section.page_start,
                page_end=section.page_end,
                chunk_text=text,
                token_count=estimate_token_count(text),
                char_count=len(text),
            )
        )

        child_parts = _split_section_text(
            text,
            target_tokens=child_target_tokens,
            max_tokens=child_max_tokens,
            overlap_tokens=child_overlap_tokens,
        )
        for child_part_index, child_text in enumerate(child_parts, start=1):
            child_title = section.section_title
            if len(child_parts) > 1 and child_title:
                child_title = f"{child_title} ({child_part_index}/{len(child_parts)})"

            chunks.append(
                ChunkRecord(
                    chunk_index=len(chunks) + 1,
                    chunk_level="child",
                    source_structure_type=f"{section.source_structure_type}_child",
                    heading_path=section.heading_path,
                    section_title=child_title,
                    clause_number=section.clause_number,
                    page_start=section.page_start,
                    page_end=section.page_end,
                    chunk_text=child_text,
                    token_count=estimate_token_count(child_text),
                    char_count=len(child_text),
                    parent_chunk_id=parent_index,
                )
            )

    return chunks


def add_child_chunks(
    parent_chunks: list[ChunkRecord],
    *,
    child_target_tokens: int = 250,
    child_max_tokens: int = 350,
    child_overlap_tokens: int = 40,
) -> list[ChunkRecord]:
    chunks: list[ChunkRecord] = []
    for parent in parent_chunks:
        parent_index = len(chunks) + 1
        normalized_parent = ChunkRecord(
            chunk_index=parent_index,
            chunk_level="parent",
            source_structure_type=parent.source_structure_type or parent.chunk_level,
            heading_path=parent.heading_path,
            section_title=parent.section_title,
            clause_number=parent.clause_number,
            page_start=parent.page_start,
            page_end=parent.page_end,
            chunk_text=parent.chunk_text,
            token_count=parent.token_count,
            char_count=parent.char_count,
        )
        chunks.append(normalized_parent)

        child_parts = _split_section_text(
            parent.chunk_text,
            target_tokens=child_target_tokens,
            max_tokens=child_max_tokens,
            overlap_tokens=child_overlap_tokens,
        )
        for child_part_index, child_text in enumerate(child_parts, start=1):
            child_title = parent.section_title
            if len(child_parts) > 1 and child_title:
                child_title = f"{child_title} ({child_part_index}/{len(child_parts)})"
            chunks.append(
                ChunkRecord(
                    chunk_index=len(chunks) + 1,
                    chunk_level="child",
                    source_structure_type=f"{parent.source_structure_type}_child",
                    heading_path=parent.heading_path,
                    section_title=child_title,
                    clause_number=parent.clause_number,
                    page_start=parent.page_start,
                    page_end=parent.page_end,
                    chunk_text=child_text,
                    token_count=estimate_token_count(child_text),
                    char_count=len(child_text),
                    parent_chunk_id=parent_index,
                )
            )

    return chunks


def _split_section_text(
    text: str,
    target_tokens: int,
    max_tokens: int,
    overlap_tokens: int,
) -> list[str]:
    if estimate_token_count(text) <= max_tokens:
        return [text]

    paragraphs = [paragraph.strip() for paragraph in text.splitlines() if paragraph.strip()]
    parts: list[str] = []
    current: list[str] = []

    for paragraph in paragraphs:
        candidate = "\n".join([*current, paragraph]).strip()
        if current and estimate_token_count(candidate) > target_tokens:
            parts.append("\n".join(current).strip())
            current = _overlap_tail(current, overlap_tokens)
        if estimate_token_count(paragraph) > max_tokens:
            if current:
                parts.append("\n".join(current).strip())
                current = []
            parts.extend(_split_long_paragraph(paragraph, target_tokens, overlap_tokens))
        else:
            current.append(paragraph)

    if current:
        parts.append("\n".join(current).strip())

    return [part for part in parts if part]


def _overlap_tail(paragraphs: list[str], overlap_tokens: int) -> list[str]:
    tail: list[str] = []
    total = 0
    for paragraph in reversed(paragraphs):
        total += estimate_token_count(paragraph)
        tail.insert(0, paragraph)
        if total >= overlap_tokens:
            break
    return tail


def _split_long_paragraph(
    paragraph: str,
    target_tokens: int,
    overlap_tokens: int,
) -> list[str]:
    approx_chars = max(600, target_tokens)
    overlap_chars = max(80, overlap_tokens)
    parts: list[str] = []
    start = 0
    while start < len(paragraph):
        end = min(len(paragraph), start + approx_chars)
        parts.append(paragraph[start:end].strip())
        if end == len(paragraph):
            break
        start = max(end - overlap_chars, start + 1)
    return [part for part in parts if part]
