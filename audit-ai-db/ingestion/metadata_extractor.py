from __future__ import annotations

import re
from dataclasses import replace
from datetime import date
import hashlib
from typing import Any

from ingestion.models import DocumentMetadata, FileInfo


DATA_TYPE_BY_DOCUMENT_TYPE = {
    "internal_rule": "text_regulation",
    "policy_guideline": "text_regulation",
    "legal_opinion": "legal_analysis",
    "system_manual": "technical_manual",
    "user_manual": "technical_manual",
}


def _clean_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def _generated_internal_code(file_info: FileInfo, source_record_id: str | None) -> str:
    stable_source = source_record_id or file_info.file_path.stem
    digest = hashlib.sha1(stable_source.encode("utf-8")).hexdigest()[:12].upper()
    return f"MANUAL-{digest}"


def _parse_bool(value: Any, default: bool = True) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "y", "latest", "active"}:
        return True
    if normalized in {"0", "false", "no", "n", "expired", "inactive"}:
        return False
    return default


def _parse_date_value(value: Any) -> date | None:
    if value is None or isinstance(value, date):
        return value
    return _parse_date_text(str(value))


def _parse_int_value(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_date_text(text: str) -> date | None:
    normalized = text.strip()
    patterns = [
        r"(?P<year>20\d{2}|19\d{2})[-/.年]\s*(?P<month>\d{1,2})[-/.月]\s*(?P<day>\d{1,2})",
        r"(?P<year>\d{2,3})\s*年\s*(?P<month>\d{1,2})\s*月\s*(?P<day>\d{1,2})\s*日",
    ]
    for pattern in patterns:
        match = re.search(pattern, normalized)
        if not match:
            continue
        year = int(match.group("year"))
        if year < 1911:
            year += 1911
        month = int(match.group("month"))
        day = int(match.group("day"))
        try:
            return date(year, month, day)
        except ValueError:
            continue
    return None


def enrich_metadata_from_markdown(
    metadata: DocumentMetadata,
    markdown: str,
) -> DocumentMetadata:
    text = markdown.strip()
    inferred_issuing_unit = _extract_unit(text)
    effective_date = metadata.effective_date or _extract_labeled_date(
        text,
        labels=("生效", "施行", "實施", "適用"),
    )
    revision_date = metadata.revision_date or _extract_labeled_date(
        text,
        labels=("修正", "修訂", "修訂日期", "更新"),
    )
    effective_year = (
        metadata.effective_year
        or (effective_date.year if effective_date else None)
        or _extract_year(text)
    )
    document_family = metadata.document_family or _normalize_document_family(
        metadata.title
    )
    normalized_version_label = metadata.normalized_version_label or _version_label(
        effective_date=effective_date,
        revision_date=revision_date,
        effective_year=effective_year,
    )

    return replace(
        metadata,
        issuing_unit=metadata.issuing_unit or inferred_issuing_unit,
        responsible_unit=metadata.responsible_unit or inferred_issuing_unit,
        effective_date=effective_date,
        effective_year=effective_year,
        revision_date=revision_date,
        document_family=document_family,
        normalized_version_label=normalized_version_label,
    )


def _extract_unit(text: str) -> str | None:
    patterns = [
        r"(?:發文單位|權責單位|主辦單位|負責單位|承辦單位|制定單位)[:：\s]+([^\n|。；;]{2,40})",
        r"\|\s*(?:發文單位|權責單位|主辦單位|負責單位|承辦單位|制定單位)\s*\|\s*([^|\n]{2,40})\s*\|",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return _clean_unit(match.group(1))
    return None


def _clean_unit(value: str) -> str | None:
    unit = re.sub(r"\s+", "", value.strip(" ：:|"))
    unit = re.sub(r"(股份有限公司|有限公司)$", "", unit)
    if not unit or unit in {"無", "不適用"}:
        return None
    return unit[:40]


def _extract_labeled_date(text: str, *, labels: tuple[str, ...]) -> date | None:
    label_re = "|".join(re.escape(label) for label in labels)
    for line in text.splitlines()[:80]:
        if not re.search(label_re, line):
            continue
        parsed = _parse_date_text(line)
        if parsed:
            return parsed
    return None


def _extract_year(text: str) -> int | None:
    match = re.search(r"(20\d{2}|19\d{2})", text[:2000])
    if match:
        return int(match.group(1))
    roc_match = re.search(r"(?<!\d)(\d{2,3})\s*年", text[:2000])
    if roc_match:
        year = int(roc_match.group(1))
        if year < 1911:
            return year + 1911
    return None


def _normalize_document_family(title: str) -> str:
    family = re.sub(r"\.[A-Za-z0-9]+$", "", title)
    family = re.sub(r"\s+", "", family)
    family = re.sub(r"[\(（][^)）]*(?:版|修正|修訂|草案|v\d+|V\d+|20\d{2})[^)）]*[\)）]", "", family)
    family = re.sub(r"(?:19|20)\d{2}(?:年|年度)?", "", family)
    family = re.sub(r"(?:民國)?\d{2,3}年(?:度)?", "", family)
    family = re.sub(r"(?:第[一二三四五六七八九十百零〇\d]+版|v\d+|V\d+|修正版|草案|最新版)", "", family)
    family = re.sub(r"(?:新版|舊版|年版|版)$", "", family)
    family = re.sub(r"[_\-\s]+", "", family)
    return family or title.strip()


def _version_label(
    *,
    effective_date: date | None,
    revision_date: date | None,
    effective_year: int | None,
) -> str | None:
    if effective_date:
        return effective_date.isoformat()
    if revision_date:
        return revision_date.isoformat()
    if effective_year:
        return str(effective_year)
    return None


def prepare_metadata(file_info: FileInfo, metadata: dict[str, Any]) -> DocumentMetadata:
    document_type = str(metadata.get("document_type") or "other").strip() or "other"
    source_record_id = metadata.get("source_record_id")
    internal_code = (
        str(metadata.get("internal_code")).strip()
        if metadata.get("internal_code")
        else _generated_internal_code(file_info, source_record_id)
    )

    data_type = (
        str(metadata.get("data_type")).strip()
        if metadata.get("data_type")
        else DATA_TYPE_BY_DOCUMENT_TYPE.get(document_type, "unknown")
    )

    return DocumentMetadata(
        internal_code=internal_code,
        title=str(metadata.get("title") or file_info.file_path.stem).strip(),
        document_type=document_type,
        data_type=data_type,
        source_system=str(metadata.get("source_system") or "manual_upload").strip(),
        source_record_id=source_record_id,
        source_url=metadata.get("source_url"),
        storage_path=str(file_info.file_path),
        original_file_name=file_info.file_name,
        file_type=file_info.file_type,
        language=str(metadata.get("language") or "zh-TW").strip(),
        status=str(metadata.get("status") or "active").strip(),
        system_category=metadata.get("system_category"),
        responsible_unit=metadata.get("responsible_unit"),
        issuing_unit=metadata.get("issuing_unit"),
        effective_date=_parse_date_value(metadata.get("effective_date")),
        effective_year=_parse_int_value(metadata.get("effective_year")),
        revision_date=_parse_date_value(metadata.get("revision_date")),
        document_family=metadata.get("document_family"),
        normalized_version_label=metadata.get("normalized_version_label"),
        is_latest=_parse_bool(metadata.get("is_latest"), default=True),
        supersedes_document_id=metadata.get("supersedes_document_id"),
        short_summary=metadata.get("short_summary"),
        keywords=_clean_list(metadata.get("keywords")),
        main_topics=_clean_list(metadata.get("main_topics")),
    )
