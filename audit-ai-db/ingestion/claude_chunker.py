from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from ingestion.chunker import estimate_token_count
from ingestion.claude_reader import ClaudeTokenUsage, call_claude_text
from ingestion.models import ChunkRecord, DocumentMetadata, IngestionError, SummaryResult


CLAUDE_CHUNK_SYSTEM = (
    "You are an internal audit/legal document structuring engine. "
    "Return only valid JSON. Preserve source wording. Do not invent content."
)

CLAUDE_JSON_REPAIR_SYSTEM = (
    "You repair malformed JSON. Return only valid JSON. "
    "Do not add, remove, summarize, or translate content."
)


def chunk_markdown_with_claude(
    markdown: str,
    metadata: DocumentMetadata,
    output_dir: Path,
    output_name: str | None = None,
) -> tuple[list[ChunkRecord], SummaryResult, Path, ClaudeTokenUsage]:
    safe_title = re.sub(r'[\\/:"*?<>|]+', "_", output_name or metadata.title).strip()
    prompt = _build_chunk_prompt(markdown, metadata)
    call_result = call_claude_text(
        prompt=prompt,
        system=CLAUDE_CHUNK_SYSTEM,
        max_tokens=20000,
        call_name="claude_chunking",
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
        repair_result = call_claude_text(
            prompt=_build_json_repair_prompt(raw),
            system=CLAUDE_JSON_REPAIR_SYSTEM,
            max_tokens=20000,
            call_name="claude_chunking_json_repair",
        )
        usage = ClaudeTokenUsage.combine(
            "claude_chunking_with_json_repair",
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
                "claude_chunking",
                (
                    "Claude returned invalid JSON and repair failed: "
                    f"{second_error.message}; raw_response_path={raw_response_path}"
                ),
            ) from first_error

    chunks = _chunk_records_from_json(parsed)
    if not chunks:
        raise IngestionError("claude_chunking", "Claude returned no chunks")

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
  document_type, short_summary, keywords, main_topics, chunks.
- chunks must be an array.

Malformed JSON:
{raw}
""".strip()


def _build_chunk_prompt(markdown: str, metadata: DocumentMetadata) -> str:
    return f"""
Convert the Markdown document into audit knowledge-base chunks.

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
  "chunks": [
    {{
      "chunk_index": 1,
      "chunk_level": "header | article | section | paragraph",
      "source_structure_type": "document_header | regulation_article | regulation_section | legal_opinion_section | manual_step | unknown",
      "heading_path": "full heading path or section title",
      "section_title": "section title, or 文件標題 for document header",
      "clause_number": "article/clause number such as 第一條 or null",
      "page_start": 1,
      "page_end": 1,
      "chunk_text": "faithful source text for this chunk"
    }}
  ]
}}

Chunking rules:
- Preserve legal and regulatory markers: 第一條, 第二條, 一、, 二、, 法務室意見, 結論.
- For internal_rule: one article or coherent section per chunk.
- For legal_opinion: one legal reasoning section per chunk. Use 法務室意見 when appropriate.
- For system_manual: one operation/process section per chunk.
- The first document title/date/responsible unit block should be chunk_level=header, source_structure_type=document_header, section_title=文件標題.
- Do not summarize inside chunk_text. chunk_text must be source content, not commentary.
- If page markers are present in HTML comments like <!-- page:3 route:... -->, use them for page_start/page_end.
- Return JSON only, no markdown fences.

Markdown document:
{markdown}
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
        raise IngestionError("claude_chunking", f"Claude returned invalid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise IngestionError("claude_chunking", "Claude JSON root must be an object")
    return parsed


def _chunk_records_from_json(parsed: dict[str, Any]) -> list[ChunkRecord]:
    raw_chunks = parsed.get("chunks")
    if not isinstance(raw_chunks, list):
        raise IngestionError("claude_chunking", "Claude JSON missing chunks array")

    chunks: list[ChunkRecord] = []
    for index, item in enumerate(raw_chunks, start=1):
        if not isinstance(item, dict):
            continue
        text = _required_string(item.get("chunk_text"), "chunk_text")
        chunk_level = _optional_string(item.get("chunk_level")) or "section"
        source_structure_type = (
            _optional_string(item.get("source_structure_type")) or "unknown"
        )
        section_title = _optional_string(item.get("section_title"))
        if chunk_level == "header" and not section_title:
            section_title = "文件標題"
        chunks.append(
            ChunkRecord(
                chunk_index=int(item.get("chunk_index") or index),
                chunk_level=chunk_level,
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
            chunk_level=chunk.chunk_level,
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


def _required_string(value: Any, field_name: str) -> str:
    text = _optional_string(value)
    if not text:
        raise IngestionError("claude_chunking", f"Claude chunk missing {field_name}")
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
