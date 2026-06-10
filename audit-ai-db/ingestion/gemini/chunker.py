from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from ingestion.chunker import estimate_token_count
from ingestion.gemini.reader import GeminiTokenUsage, call_gemini_text
from ingestion.models import ChunkRecord, DocumentMetadata, IngestionError, SummaryResult


GEMINI_CHUNK_SYSTEM = (
    "You are an internal audit/legal document parent-section boundary engine. "
    "Return only valid JSON. Preserve source wording. Do not invent content."
)

GEMINI_JSON_REPAIR_SYSTEM = (
    "You repair malformed JSON. Return only valid JSON. "
    "Do not add, remove, summarize, or translate content."
)


def chunk_markdown_with_gemini(
    markdown: str,
    metadata: DocumentMetadata,
    output_dir: Path,
    output_name: str | None = None,
) -> tuple[list[ChunkRecord], SummaryResult, Path, GeminiTokenUsage]:
    safe_title = re.sub(r'[\\/:"*?<>|]+', "_", output_name or metadata.title).strip()
    prompt = _build_chunk_prompt(markdown, metadata)
    call_result = call_gemini_text(
        prompt=prompt,
        system=GEMINI_CHUNK_SYSTEM,
        max_tokens=8192,
        call_name="gemini_chunking",
    )
    raw = call_result.text
    usage = call_result.usage
    raw_response_path = _write_raw_response(
        output_dir,
        safe_title,
        raw,
        suffix="raw",
    )
    try:
        parsed = _parse_json_object(raw)
    except IngestionError as first_error:
        repair_result = call_gemini_text(
            prompt=_build_json_repair_prompt(raw),
            system=GEMINI_JSON_REPAIR_SYSTEM,
            max_tokens=8192,
            call_name="gemini_chunking_json_repair",
        )
        usage = GeminiTokenUsage.combine(
            "gemini_chunking_with_json_repair",
            [call_result.usage, repair_result.usage],
        )
        repaired_raw = repair_result.text
        _write_raw_response(
            output_dir,
            safe_title,
            repaired_raw,
            suffix="repaired",
        )
        try:
            parsed = _parse_json_object(repaired_raw)
        except IngestionError as second_error:
            raise IngestionError(
                "gemini_chunking",
                (
                    "Gemini returned invalid JSON and repair failed: "
                    f"{second_error.message}; raw_response_path={raw_response_path}"
                ),
            ) from first_error

    chunks = _chunk_records_from_json(parsed, markdown=markdown)
    if not chunks:
        raise IngestionError("gemini_chunking", "Gemini returned no parent chunks")

    summary = SummaryResult(
        short_summary=_optional_string(parsed.get("short_summary")),
        keywords=_string_list(parsed.get("keywords")),
        main_topics=_string_list(parsed.get("main_topics")),
        summary_generated=bool(_optional_string(parsed.get("short_summary"))),
    )

    output_path = output_dir / "chunks" / f"{safe_title}.chunks.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(parsed, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return chunks, summary, output_path, usage


def _write_raw_response(
    output_dir: Path,
    safe_title: str,
    raw: str,
    *,
    suffix: str,
) -> Path:
    path = output_dir / "chunk_raw" / f"{safe_title}.{suffix}.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(raw, encoding="utf-8")
    return path


def _build_json_repair_prompt(raw: str) -> str:
    return f"""
Repair the following malformed JSON into one valid JSON object.

Rules:
- Return JSON only. No markdown fences.
- Preserve every original field and every source text value.
- Do not summarize, translate, or invent content.
- The repaired JSON must have the same top-level schema:
	  document_type, short_summary, keywords, main_topics, parent_chunks.
- parent_chunks must be an array.

Malformed JSON:
{raw}
""".strip()


def _build_chunk_prompt(markdown: str, metadata: DocumentMetadata) -> str:
    return f"""
Convert the Markdown document into audit knowledge-base parent chunks.

Document metadata:
- title: {metadata.title}
- document_type: {metadata.document_type}
- language: {metadata.language}

Output exactly one JSON object with this schema:
{{
  "document_type": "internal_rule | legal_opinion | system_manual | other",
  "short_summary": "2-4 sentence summary based only on source text",
  "keywords": ["..."],
  "main_topics": ["..."],
  "parent_chunks": [
    {{
      "chunk_index": 1,
      "chunk_level": "parent",
      "source_structure_type": "document_header | regulation_article | regulation_section | legal_opinion_section | manual_step | unknown",
      "heading_path": "full heading path or section title",
      "section_title": "section title, or 文件標題 for document header",
      "clause_number": "article/clause number such as 第一條 or null",
      "page_start": 1,
      "page_end": 1,
      "start_line": 12,
      "end_line": 35,
      "parent_reason": "short reason why this boundary is a complete logical parent section"
    }}
  ]
}}

Parent chunking rules:
- Return parent chunks only. Do not create small retrieval chunks.
- A parent chunk should be one complete legal article, policy section, manual step, legal reasoning section, table/form section, or document header block.
- Keep a table together with the heading/rule it belongs to.
- Do not split a legal article in the middle, even if it has numbered subitems.
- Do not merge unrelated articles or sections.
- Preserve legal and regulatory markers: 第一條, 第二條, 一、, 二、, 法務室意見, 結論.
- For internal_rule: one article or coherent policy section per parent chunk.
- For legal_opinion: one legal reasoning section per parent chunk. Use 法務室意見 when appropriate.
- For system_manual: one operation/process section per parent chunk.
- The first document title/date/responsible unit block should be chunk_level=parent, source_structure_type=document_header, section_title=文件標題.
- Do not return chunk_text unless line numbers are impossible.
- Use start_line and end_line from the numbered Markdown preview below.
- The preview may truncate long lines; choose boundaries by line number anyway.
- The application will extract full source text locally from the original Markdown.
- Put reasoning only in parent_reason.
- If page markers are present in HTML comments like <!-- page:3 route:... -->, use them for page_start/page_end.
- Return JSON only, no markdown fences.

Numbered Markdown document:
{_number_markdown_lines(markdown)}
""".strip()


def _parse_json_object(raw: str) -> dict[str, Any]:
    clean = raw.strip()
    clean = re.sub(r"^```(?:json)?\s*", "", clean)
    clean = re.sub(r"\s*```$", "", clean)
    match = re.search(r"\{.*\}", clean, flags=re.DOTALL)
    if match:
        clean = match.group(0)
    try:
        parsed = json.loads(clean)
    except json.JSONDecodeError as exc:
        raise IngestionError("gemini_chunking", f"Gemini returned invalid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise IngestionError("gemini_chunking", "Gemini JSON root must be an object")
    return parsed


def _chunk_records_from_json(
    parsed: dict[str, Any],
    *,
    markdown: str | None = None,
) -> list[ChunkRecord]:
    raw_chunks = parsed.get("parent_chunks")
    if raw_chunks is None:
        raw_chunks = parsed.get("chunks")
    if not isinstance(raw_chunks, list):
        raise IngestionError("gemini_chunking", "Gemini JSON missing parent_chunks array")
    if markdown is not None:
        _infer_missing_line_ranges(raw_chunks, markdown)

    chunks: list[ChunkRecord] = []
    for index, item in enumerate(raw_chunks, start=1):
        if not isinstance(item, dict):
            continue
        text = _chunk_text_from_json_item(item, markdown)
        raw_chunk_level = _optional_string(item.get("chunk_level"))
        source_structure_type = (
            _optional_string(item.get("source_structure_type"))
            or raw_chunk_level
            or "llm_parent_section"
        )
        section_title = _optional_string(item.get("section_title"))
        if source_structure_type == "document_header" and not section_title:
            section_title = "文件標題"
        chunks.append(
            ChunkRecord(
                chunk_index=int(item.get("chunk_index") or index),
                chunk_level="parent",
                source_structure_type=source_structure_type,
                heading_path=_optional_string(item.get("heading_path")) or section_title,
                section_title=section_title,
                clause_number=_optional_string(item.get("clause_number")),
                page_start=_optional_int(item.get("page_start")),
                page_end=_optional_int(item.get("page_end")),
                chunk_text=text,
                token_count=estimate_token_count(text),
                char_count=len(text),
            )
        )

    chunks.sort(key=lambda chunk: chunk.chunk_index)
    return [
        ChunkRecord(
            chunk_index=index,
            chunk_level="parent",
            source_structure_type=chunk.source_structure_type,
            heading_path=chunk.heading_path,
            section_title=chunk.section_title,
            clause_number=chunk.clause_number,
            page_start=chunk.page_start,
            page_end=chunk.page_end,
            chunk_text=chunk.chunk_text,
            token_count=chunk.token_count,
            char_count=chunk.char_count,
            parent_chunk_id=chunk.parent_chunk_id,
        )
        for index, chunk in enumerate(chunks, start=1)
    ]


def _number_markdown_lines(markdown: str, max_line_chars: int = 220) -> str:
    lines = markdown.splitlines()
    width = max(4, len(str(len(lines))))
    numbered_lines: list[str] = []
    for line_number, line in enumerate(lines, start=1):
        preview = re.sub(r"\s+", " ", line).strip()
        if len(preview) > max_line_chars:
            preview = preview[:max_line_chars].rstrip() + "..."
        numbered_lines.append(f"{line_number:0{width}d}: {preview}")
    return "\n".join(numbered_lines)


def _infer_missing_line_ranges(raw_chunks: list[Any], markdown: str) -> None:
    line_count = len(markdown.splitlines())
    chunk_items = [item for item in raw_chunks if isinstance(item, dict)]
    for index, item in enumerate(chunk_items):
        if _optional_int(item.get("start_line")) is not None and _optional_int(item.get("end_line")) is not None:
            continue

        previous_end = None
        for previous in reversed(chunk_items[:index]):
            previous_end = _optional_int(previous.get("end_line"))
            if previous_end is not None:
                break

        next_start = None
        for following in chunk_items[index + 1 :]:
            next_start = _optional_int(following.get("start_line"))
            if next_start is not None:
                break

        inferred_start = (previous_end + 1) if previous_end is not None else 1
        inferred_end = (next_start - 1) if next_start is not None else line_count
        if inferred_start <= inferred_end:
            item.setdefault("start_line", inferred_start)
            item.setdefault("end_line", inferred_end)


def _chunk_text_from_json_item(item: dict[str, Any], markdown: str | None) -> str:
    text = _optional_string(item.get("chunk_text"))
    if text:
        return text
    if markdown is None:
        raise IngestionError(
            "gemini_chunking",
            "Gemini parent chunk missing chunk_text and no source Markdown was provided",
        )
    start_line = _optional_int(item.get("start_line"))
    end_line = _optional_int(item.get("end_line"))
    if start_line is None or end_line is None:
        raise IngestionError(
            "gemini_chunking",
            "Gemini parent chunk must include start_line and end_line",
        )
    lines = markdown.splitlines()
    if start_line < 1:
        start_line = 1
    if end_line > len(lines):
        end_line = len(lines)
    if end_line < start_line:
        raise IngestionError(
            "gemini_chunking",
            f"Gemini parent chunk has invalid line range: {start_line}-{end_line}",
        )
    return "\n".join(lines[start_line - 1 : end_line]).strip()


def _required_string(value: Any, field_name: str) -> str:
    text = _optional_string(value)
    if not text:
        raise IngestionError("gemini_chunking", f"Gemini chunk missing {field_name}")
    return text


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() == "null":
        return None
    return text


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def _optional_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
