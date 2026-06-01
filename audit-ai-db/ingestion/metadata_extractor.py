from __future__ import annotations

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
        short_summary=metadata.get("short_summary"),
        keywords=_clean_list(metadata.get("keywords")),
        main_topics=_clean_list(metadata.get("main_topics")),
    )

