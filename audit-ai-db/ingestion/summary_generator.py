from __future__ import annotations

import re
from collections import Counter

from ingestion.models import DocumentMetadata, SummaryResult, TextBlock


SENTENCE_RE = re.compile(r"(?<=[。！？.!?])\s*|\n+")
TERM_RE = re.compile(r"[A-Za-z][A-Za-z0-9_-]{2,}|[\u4e00-\u9fff]{2,8}")


def generate_summary(
    blocks: list[TextBlock],
    metadata: DocumentMetadata,
) -> SummaryResult:
    text = "\n".join(block.text for block in blocks if block.text.strip())

    short_summary = metadata.short_summary or _extract_leading_summary(text)
    keywords = metadata.keywords or _extract_keywords(text)
    main_topics = metadata.main_topics or _extract_main_topics(metadata)

    return SummaryResult(
        short_summary=short_summary,
        keywords=keywords,
        main_topics=main_topics,
        summary_generated=bool(short_summary),
    )


def _extract_leading_summary(text: str) -> str | None:
    compact = re.sub(r"\s+", " ", text).strip()
    if not compact:
        return None

    sentences = [item.strip() for item in SENTENCE_RE.split(text) if item.strip()]
    if not sentences:
        return compact[:500]
    return " ".join(sentences[:4])[:800]


def _extract_keywords(text: str, limit: int = 12) -> list[str]:
    candidates = [match.group(0).strip() for match in TERM_RE.finditer(text)]
    stopwords = {
        "the",
        "and",
        "for",
        "with",
        "this",
        "that",
        "from",
        "shall",
    }
    normalized = [
        candidate
        for candidate in candidates
        if candidate.lower() not in stopwords and len(candidate) >= 2
    ]
    return [term for term, _ in Counter(normalized).most_common(limit)]


def _extract_main_topics(metadata: DocumentMetadata) -> list[str]:
    topics = []
    if metadata.system_category:
        topics.append(metadata.system_category)
    if metadata.document_type:
        topics.append(metadata.document_type)
    return topics
