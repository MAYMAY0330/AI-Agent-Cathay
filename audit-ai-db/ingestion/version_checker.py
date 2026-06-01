from __future__ import annotations

from ingestion import db_writer
from ingestion.models import VersionDecision


def check_version(conn, internal_code: str, file_checksum: str) -> VersionDecision:
    document = db_writer.fetch_document_by_internal_code(conn, internal_code)
    if document is None:
        return VersionDecision(action="new_document", next_version_label="v1")

    current_version = db_writer.fetch_current_version(conn, document["id"])
    if current_version and current_version.get("file_checksum") == file_checksum:
        return VersionDecision(
            action="duplicate",
            document_id=document["id"],
            current_version_id=current_version["id"],
            next_version_label=current_version.get("version_label") or "v1",
        )

    next_number = db_writer.count_document_versions(conn, document["id"]) + 1
    return VersionDecision(
        action="updated_version",
        document_id=document["id"],
        current_version_id=current_version["id"] if current_version else None,
        next_version_label=f"v{next_number}",
    )

