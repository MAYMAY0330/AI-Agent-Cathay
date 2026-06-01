from __future__ import annotations

from pathlib import Path

from ingestion.models import FileInfo, IngestionError


ALLOWED_EXTENSIONS = {".pdf", ".docx"}


def load_file(file_path: str) -> FileInfo:
    path = Path(file_path).expanduser()
    if not path.exists():
        raise IngestionError("file_loading", f"file does not exist: {path}")
    if not path.is_file():
        raise IngestionError("file_loading", f"path is not a file: {path}")

    extension = path.suffix.lower()
    if extension not in ALLOWED_EXTENSIONS:
        allowed = ", ".join(sorted(ALLOWED_EXTENSIONS))
        raise IngestionError(
            "file_loading",
            f"unsupported file extension '{extension}'. Allowed: {allowed}",
        )

    file_size = path.stat().st_size
    if file_size <= 0:
        raise IngestionError("file_loading", "file is empty")

    try:
        with path.open("rb") as file:
            file.read(1)
    except OSError as exc:
        raise IngestionError("file_loading", f"file cannot be opened: {exc}") from exc

    return FileInfo(
        file_path=path.resolve(),
        file_name=path.name,
        file_extension=extension,
        file_size=file_size,
        file_type=extension.removeprefix("."),
    )

