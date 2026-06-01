from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _load_dotenv_file(env_path: Path) -> None:
    if not env_path.exists():
        return

    try:
        from dotenv import load_dotenv

        load_dotenv(env_path)
        return
    except ImportError:
        pass

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'\"")
        os.environ.setdefault(key, value)


@dataclass(frozen=True)
class DBConfig:
    host: str
    port: int
    dbname: str
    user: str
    password: str

    @classmethod
    def from_env(cls, project_root: Path | None = None) -> "DBConfig":
        root = project_root or Path(__file__).resolve().parents[1]
        _load_dotenv_file(root / ".env")

        return cls(
            host=os.getenv("POSTGRES_HOST", os.getenv("DB_HOST", "localhost")),
            port=int(os.getenv("POSTGRES_PORT", os.getenv("DB_PORT", "5432"))),
            dbname=os.getenv("POSTGRES_DB", os.getenv("DB_NAME", "audit_ai_db")),
            user=os.getenv("POSTGRES_USER", os.getenv("DB_USER", "audit_user")),
            password=os.getenv(
                "POSTGRES_PASSWORD", os.getenv("DB_PASSWORD", "audit_password")
            ),
        )

