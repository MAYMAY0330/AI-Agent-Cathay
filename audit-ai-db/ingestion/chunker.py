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
) -> list[ChunkRecord]:
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

