from __future__ import annotations

import re

from ingestion.models import TextBlock


PAGE_COMMENT_RE = re.compile(r"<!--\s*page:(\d+)\b[^>]*-->")


def markdown_to_blocks(markdown: str) -> list[TextBlock]:
    blocks: list[TextBlock] = []
    current_page: int | None = None
    for raw_line in markdown.splitlines():
        page_match = PAGE_COMMENT_RE.search(raw_line)
        if page_match:
            current_page = int(page_match.group(1))
            continue

        text = raw_line.strip()
        if not text:
            continue
        blocks.append(
            TextBlock(
                block_index=len(blocks) + 1,
                text=_strip_markdown_heading(text),
                style=_markdown_style(text),
                page=current_page,
            )
        )
    return blocks


def _markdown_style(line: str) -> str:
    if line.startswith("#"):
        return f"heading{min(6, len(line) - len(line.lstrip('#')))}"
    if line.startswith("|") and line.endswith("|"):
        return "table"
    return "paragraph"


def _strip_markdown_heading(line: str) -> str:
    return re.sub(r"^#{1,6}\s+", "", line).strip()
