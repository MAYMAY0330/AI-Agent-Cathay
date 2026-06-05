from __future__ import annotations

import re


CJK_RE = re.compile(r"[\u4e00-\u9fff]+")
TOKEN_RE = re.compile(r"[A-Za-z0-9_@.-]+|[\u4e00-\u9fff]+")


def build_query_terms(query: str, *, max_terms: int = 64) -> list[str]:
    cleaned = re.sub(r"\s+", " ", query).strip()
    if not cleaned:
        return []

    terms: list[str] = []
    for token in TOKEN_RE.findall(cleaned):
        if len(token) >= 2:
            terms.append(token)

    for cjk_text in CJK_RE.findall(cleaned):
        if len(cjk_text) <= 4:
            continue
        terms.extend(_cjk_windows(cjk_text))

    return _dedupe_terms(terms, max_terms=max_terms)


def _cjk_windows(text: str) -> list[str]:
    windows: list[str] = []
    for size in (4, 3, 2):
        for index in range(0, len(text) - size + 1):
            windows.append(text[index : index + size])
    return windows


def _dedupe_terms(terms: list[str], *, max_terms: int) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for term in terms:
        normalized = term.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        unique.append(normalized)
        if len(unique) >= max_terms:
            break
    return unique
