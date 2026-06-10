from __future__ import annotations

import re
from pathlib import Path

from ingestion.models import DocumentMetadata, FileInfo, TextBlock
from ingestion.text_cleaner import clean_extracted_text


def blocks_to_markdown(
    blocks: list[TextBlock],
    *,
    file_info: FileInfo,
    metadata: DocumentMetadata,
) -> str:
    """Convert locally extracted blocks into a stable Markdown parse artifact."""
    parts: list[str] = [f"# {metadata.title or file_info.file_path.stem}"]

    for block in blocks:
        text = clean_extracted_text(block.text)
        if not text:
            continue

        if block.page is not None:
            parts.append(f"<!-- page:{block.page} route:local_text -->")
            parts.append(f"## Page {block.page}")
            parts.append(text)
            continue

        if block.style == "table":
            parts.append(_table_block_to_markdown(text))
            continue

        heading_level = _heading_level(block.style)
        if heading_level is not None:
            parts.append(f"{'#' * heading_level} {text}")
            continue

        parts.append(text)

    return "\n\n".join(part for part in parts if part.strip()).strip() + "\n"


def write_markdown_artifact(
    markdown: str,
    output_root: Path,
    output_name: str,
) -> Path:
    path = output_root / "markdown" / f"{safe_name(output_name)}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(markdown, encoding="utf-8")
    return path


def safe_name(value: str) -> str:
    return "".join("_" if char in '\\/:*?"<>|' else char for char in value).strip()


def _heading_level(style: str) -> int | None:
    normalized = style.lower().strip()
    if not normalized.startswith("heading"):
        return None

    match = re.search(r"(\d+)", normalized)
    if not match:
        return 2

    # The document title is emitted as H1, so source Heading 1 starts at H2.
    return min(6, int(match.group(1)) + 1)


def _table_block_to_markdown(text: str) -> str:
    rows = [
        [cell.strip() for cell in line.split("|")]
        for line in text.splitlines()
        if line.strip()
    ]
    rows = [[cell for cell in row if cell] for row in rows]
    rows = [row for row in rows if row]
    if not rows:
        return text

    column_count = max(len(row) for row in rows)
    normalized_rows = [row + [""] * (column_count - len(row)) for row in rows]
    markdown_rows = ["| " + " | ".join(row) + " |" for row in normalized_rows]
    if len(markdown_rows) >= 2:
        separator = "| " + " | ".join(["---"] * column_count) + " |"
        markdown_rows.insert(1, separator)
    return "\n".join(markdown_rows)
