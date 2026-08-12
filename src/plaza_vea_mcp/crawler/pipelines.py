"""Persist crawler items and price observations."""

from __future__ import annotations

from typing import Any

from plaza_vea_mcp.config import Settings
from plaza_vea_mcp.db import CatalogRepository, create_database_engine
from plaza_vea_mcp.schemas import CatalogOffer


class CatalogPipeline:
    def __init__(self, crawler: Any) -> None:
        self.crawler = crawler
        settings = Settings.from_env()
        self.repository = CatalogRepository(create_database_engine(settings))
        self.repository.initialize()

    @classmethod
    def from_crawler(cls, crawler: Any) -> CatalogPipeline:
        return cls(crawler)

    def process_item(self, item: dict[str, Any]) -> dict[str, Any]:
        offer = CatalogOffer.model_validate(item)
        self.repository.upsert_offers([offer], run_id=self.crawler.spider.run_id)
        return item

    def close_spider(self) -> None:
        self.repository.close()
