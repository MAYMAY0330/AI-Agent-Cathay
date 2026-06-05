from __future__ import annotations

import re


REVIEWER_TIMESTAMP_RE = re.compile(
    r"(?<!\S)[\u4e00-\u9fff]{2,4}\s+20\d{2}-\d{1,2}-\d{1,2}\s+"
    r"\d{1,2}:\d{2}:\d{2}(?:\.\d+)?"
)


def clean_extracted_text(text: str) -> str:
    """Remove recurring extraction artifacts while preserving source content."""
    cleaned = REVIEWER_TIMESTAMP_RE.sub("", text)
    cleaned = re.sub(r"[ \t]+\n", "\n", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()
