from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from plaza_vea_mcp.config import Settings
from plaza_vea_mcp.db import CatalogRepository, create_database_engine


@pytest.fixture
def vtex_products() -> list[dict[str, Any]]:
    path = Path(__file__).parent / "fixtures" / "vtex_products.json"
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        project_root=tmp_path,
        data_dir=tmp_path / "data",
        database_path=tmp_path / "data" / "catalog.sqlite3",
    )


@pytest.fixture
def repository(settings: Settings) -> Iterator[CatalogRepository]:
    result = CatalogRepository(create_database_engine(settings))
    result.initialize()
    yield result
    result.close()
