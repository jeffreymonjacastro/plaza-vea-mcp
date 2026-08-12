"""Background Scrapy process management."""

from __future__ import annotations

import os
import subprocess
import sys
import uuid

from plaza_vea_mcp.config import Settings
from plaza_vea_mcp.db import CatalogRepository
from plaza_vea_mcp.schemas import CatalogRefreshStarted, CatalogRefreshStatus


class RefreshManager:
    def __init__(self, settings: Settings, repository: CatalogRepository):
        self.settings = settings
        self.repository = repository

    def start(self, category_id: str | None) -> CatalogRefreshStarted:
        active = self.repository.active_run()
        if active is not None:
            raise ValueError(f"Ya existe una actualizacion activa: {active.run_id}")

        run_id = uuid.uuid4().hex
        status = self.repository.create_run(run_id, category_id)
        command = [
            sys.executable,
            "-m",
            "plaza_vea_mcp.crawler.runner",
            "--run-id",
            run_id,
        ]
        if category_id:
            command.extend(["--category-id", category_id])
        log_path = self.settings.data_dir / "logs" / f"crawl-{run_id}.log"
        creation_flags: int = 0
        if os.name == "nt":
            creation_flags = int(getattr(subprocess, "CREATE_NO_WINDOW", 0)) | int(
                getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            )
        try:
            with log_path.open("ab") as log_file:
                process = subprocess.Popen(
                    command,
                    cwd=self.settings.project_root,
                    stdin=subprocess.DEVNULL,
                    stdout=log_file,
                    stderr=subprocess.STDOUT,
                    start_new_session=os.name != "nt",
                    creationflags=creation_flags,
                )
        except OSError as exc:
            self.repository.finish_run(
                run_id,
                status="failed",
                products_processed=0,
                error=f"No se pudo iniciar Scrapy: {exc}",
            )
            raise RuntimeError(f"No se pudo iniciar Scrapy: {exc}") from exc
        self.repository.mark_run_running(run_id, process.pid)
        return CatalogRefreshStarted(
            run_id=run_id,
            status="running",
            category_id=category_id,
            started_at=status.started_at,
        )

    def status(self, run_id: str) -> CatalogRefreshStatus:
        status = self.repository.get_run(run_id)
        if status is None:
            raise ValueError(f"No existe una actualizacion con run_id {run_id}")
        return status
