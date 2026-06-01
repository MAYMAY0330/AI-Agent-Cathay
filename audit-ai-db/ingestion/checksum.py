from __future__ import annotations

import hashlib
from pathlib import Path

from ingestion.models import IngestionError


def generate_file_checksum(file_path: Path, algorithm: str = "sha256") -> str:
    try:
        hasher = hashlib.new(algorithm)
    except ValueError as exc:
        raise IngestionError(
            "checksum_generation", f"unsupported checksum algorithm: {algorithm}"
        ) from exc

    try:
        with file_path.open("rb") as file:
            for chunk in iter(lambda: file.read(1024 * 1024), b""):
                hasher.update(chunk)
    except OSError as exc:
        raise IngestionError(
            "checksum_generation", "unable to generate file checksum"
        ) from exc

    return hasher.hexdigest()

