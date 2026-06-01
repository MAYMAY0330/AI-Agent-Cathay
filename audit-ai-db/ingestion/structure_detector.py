from __future__ import annotations

import re

from ingestion.models import StructureResult, StructuredSection, TextBlock


ARTICLE_RE = re.compile(
    r"^\s*(第[一二三四五六七八九十百零〇\d]+條)\s*(.*)$"
)
LEGAL_SECTION_RE = re.compile(
    r"^\s*([一二三四五六七八九十]+、|法務室意見|結論)\s*(.*)$"
)
NUMBERED_HEADING_RE = re.compile(r"^\s*(\d+(?:\.\d+)*)[.)、]?\s+(.{1,80})$")
PAREN_HEADING_RE = re.compile(r"^\s*[\(（]([^()（）]{1,30})[\)）]\s*$")
CHINESE_NUMBERED_RE = re.compile(r"^\s*[一二三四五六七八九十]+[、.]\s*[^。；;]{1,80}$")
HEADING_KEYWORD_RE = re.compile(
    r"(目的|依據|適用|範圍|定義|權責|角色|申請|作業|管理|限制|安全|保密|"
    r"附則|施行|日期|通報|揭露|訓練|驗證|救濟|風險|資料|平台|系統|流程|步驟)"
)


def detect_structure(
    blocks: list[TextBlock],
    document_type: str,
) -> StructureResult:
    normalized_type = document_type.lower()
    if normalized_type in {"internal_rule", "policy_guideline"}:
        result = _detect_internal_rule_sections(blocks)
        if result.sections:
            return result
    elif normalized_type == "legal_opinion":
        result = _detect_by_line_marker(
            blocks,
            LEGAL_SECTION_RE,
            chunk_level="section",
            source_structure_type="legal_opinion_section",
        )
        if result.sections:
            return result
    elif normalized_type in {"system_manual", "user_manual"}:
        result = _detect_manual_sections(blocks)
        if result.sections:
            return result

    return _fallback_sections(blocks)


def _detect_internal_rule_sections(blocks: list[TextBlock]) -> StructureResult:
    article_result = _detect_by_line_marker(
        blocks,
        ARTICLE_RE,
        chunk_level="article",
        source_structure_type="regulation_article",
    )
    if article_result.sections:
        return article_result

    heading_result = _detect_by_headings(
        blocks,
        chunk_level="section",
        source_structure_type="regulation_section",
    )
    if heading_result.sections:
        return heading_result

    return StructureResult(sections=[])


def _detect_by_line_marker(
    blocks: list[TextBlock],
    marker_re: re.Pattern[str],
    chunk_level: str,
    source_structure_type: str,
) -> StructureResult:
    sections: list[StructuredSection] = []
    current_lines: list[str] = []
    current_clause: str | None = None
    current_title: str | None = None
    page_start: int | None = None
    page_end: int | None = None

    def flush() -> None:
        nonlocal current_lines, current_clause, current_title, page_start, page_end
        text = "\n".join(current_lines).strip()
        if not text:
            current_lines = []
            return
        title_parts = [part for part in [current_clause, current_title] if part]
        section_title = " ".join(title_parts) if title_parts else None
        sections.append(
            StructuredSection(
                section_index=len(sections) + 1,
                text=text,
                chunk_level=chunk_level,
                source_structure_type=source_structure_type,
                heading_path=section_title,
                section_title=section_title,
                clause_number=current_clause,
                page_start=page_start,
                page_end=page_end,
            )
        )
        current_lines = []
        current_clause = None
        current_title = None
        page_start = None
        page_end = None

    for block in blocks:
        for line in _block_lines(block):
            match = marker_re.match(line)
            if match:
                flush()
                current_clause = match.group(1).strip()
                current_title = match.group(2).strip() if match.lastindex == 2 else None
                current_lines.append(line)
                page_start = block.page
                page_end = block.page
                continue

            if current_lines:
                current_lines.append(line)
                page_end = block.page or page_end

    flush()
    return StructureResult(sections=sections)


def _detect_manual_sections(blocks: list[TextBlock]) -> StructureResult:
    return _detect_by_headings(
        blocks,
        chunk_level="section",
        source_structure_type="manual_step",
    )


def _detect_by_headings(
    blocks: list[TextBlock],
    chunk_level: str,
    source_structure_type: str,
) -> StructureResult:
    sections: list[StructuredSection] = []
    current_lines: list[str] = []
    current_title: str | None = None
    page_start: int | None = None
    page_end: int | None = None

    def flush() -> None:
        nonlocal current_lines, current_title, page_start, page_end
        text = "\n".join(current_lines).strip()
        if not text:
            current_lines = []
            return
        section_chunk_level = chunk_level if current_title else "header"
        section_structure_type = (
            source_structure_type if current_title else "document_header"
        )
        section_title = current_title if current_title else "文件標題"
        sections.append(
            StructuredSection(
                section_index=len(sections) + 1,
                text=text,
                chunk_level=section_chunk_level,
                source_structure_type=section_structure_type,
                heading_path=section_title,
                section_title=section_title,
                clause_number=None,
                page_start=page_start,
                page_end=page_end,
            )
        )
        current_lines = []
        current_title = None
        page_start = None
        page_end = None

    for block in blocks:
        lines = _block_lines(block)
        for line in lines:
            is_initial_preamble = not sections and current_title is None
            if (
                _is_section_heading(line, block.style)
                and not (is_initial_preamble and _looks_like_preamble_line(line))
            ):
                flush()
                current_title = _normalize_heading(line)
                current_lines.append(line)
                page_start = block.page
                page_end = block.page
                continue

            current_lines.append(line)
            page_start = page_start or block.page
            page_end = block.page or page_end

    flush()
    return StructureResult(sections=sections)


def _fallback_sections(blocks: list[TextBlock]) -> StructureResult:
    sections: list[StructuredSection] = []
    for block in blocks:
        text = block.text.strip()
        if not text:
            continue
        sections.append(
            StructuredSection(
                section_index=len(sections) + 1,
                text=text,
                chunk_level="paragraph",
                source_structure_type="unknown",
                heading_path=None,
                section_title=None,
                clause_number=None,
                page_start=block.page,
                page_end=block.page,
            )
        )
    return StructureResult(
        sections=sections,
        used_fallback=True,
        warning="structure detection failed; used paragraph fallback chunking",
    )


def _block_lines(block: TextBlock) -> list[str]:
    text = re.sub(
        r"\s+(第[一二三四五六七八九十百零〇\d]+條)\s*",
        r"\n\1 ",
        block.text,
    )
    text = re.sub(r"\s+([一二三四五六七八九十]+、)\s*", r"\n\1 ", text)
    return [
        line.strip()
        for line in text.splitlines()
        if line.strip() and not re.fullmatch(r"\d+", line.strip())
    ]


def _is_section_heading(line: str, style: str) -> bool:
    normalized = line.strip()
    if not normalized:
        return False

    if style.lower() == "table":
        return False
    if style.lower().startswith("heading"):
        return True
    if PAREN_HEADING_RE.match(normalized):
        return True
    if re.fullmatch(r"\d+", normalized):
        return False
    if re.search(r"\d{2,4}\s*年|\d{1,2}\s*月|\d{1,2}\s*日|權責單位", normalized):
        return False
    if NUMBERED_HEADING_RE.match(normalized):
        return True
    if (
        len(normalized) <= 45
        and CHINESE_NUMBERED_RE.match(normalized)
        and not re.search(r"[。；;：:]", normalized)
    ):
        return True
    if len(normalized) > 35:
        return False
    if re.search(r"[。；;：:]$", normalized):
        return False
    if re.search(r"[，,。；;：:]", normalized):
        return False
    return bool(HEADING_KEYWORD_RE.search(normalized))


def _normalize_heading(line: str) -> str:
    match = PAREN_HEADING_RE.match(line)
    if match:
        return match.group(1).strip()
    return line.strip()


def _looks_like_preamble_line(line: str) -> bool:
    normalized = line.strip()
    if re.search(r"\d{2,4}\s*年|\d{1,2}\s*月|\d{1,2}\s*日|權責單位", normalized):
        return True
    return bool(re.search(r"(要點|辦法|政策|說明)$", normalized))
