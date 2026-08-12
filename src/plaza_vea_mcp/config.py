"""Runtime configuration for the local MCP server and crawler."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Settings:
    """Application settings derived from environment variables."""

    project_root: Path
    data_dir: Path
    database_path: Path
    vtex_base_url: str = "https://www.plazavea.com.pe"
    sales_channel: str = "1"
    request_timeout_seconds: float = 20.0
    user_agent: str = "plaza-vea-mcp/0.1 (+https://github.com/jeffreymonjacastro/plaza-vea-mcp)"

    @classmethod
    def from_env(cls) -> Settings:
        project_root = Path(os.environ.get("PLAZA_VEA_PROJECT_ROOT", Path.cwd())).resolve()
        data_dir = Path(os.environ.get("PLAZA_VEA_DATA_DIR", project_root / "data")).resolve()
        database_path = Path(
            os.environ.get("PLAZA_VEA_DATABASE_PATH", data_dir / "catalog.sqlite3")
        ).resolve()
        return cls(
            project_root=project_root,
            data_dir=data_dir,
            database_path=database_path,
        )

    @property
    def database_url(self) -> str:
        return f"sqlite+pysqlite:///{self.database_path.as_posix()}"

    def ensure_directories(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        (self.data_dir / "logs").mkdir(parents=True, exist_ok=True)
