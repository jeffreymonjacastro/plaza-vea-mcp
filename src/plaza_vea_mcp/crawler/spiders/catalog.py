"""Catalog spider using only Plaza Vea's public VTEX JSON endpoints."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any, ClassVar
from urllib.parse import urlencode

import scrapy

from plaza_vea_mcp.config import Settings
from plaza_vea_mcp.utils import parse_resource_total
from plaza_vea_mcp.vtex import products_to_offers


class PlazaVeaCatalogSpider(scrapy.Spider):
    name = "plaza_vea_catalog"
    allowed_domains: ClassVar[list[str]] = ["www.plazavea.com.pe"]

    def __init__(
        self,
        run_id: str,
        category_id: str | None = None,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.run_id = run_id
        self.category_id = category_id
        self.app_settings = Settings.from_env()
        self.offers_processed = 0
        self._seen: set[tuple[str, str, str]] = set()

    async def start(self) -> AsyncIterator[scrapy.Request]:
        if self.category_id:
            yield self._category_request(self.category_id, 0)
            return
        yield scrapy.Request(
            f"{self.app_settings.vtex_base_url}/api/catalog_system/pub/category/tree/10",
            callback=self.parse_category_tree,
        )

    def parse_category_tree(self, response: scrapy.http.Response) -> Any:
        tree = json.loads(response.text)
        leaf_ids = self._leaf_category_ids(tree)
        self.logger.info("Se encontraron %d categorias hoja", len(leaf_ids))
        for category_id in leaf_ids:
            yield self._category_request(category_id, 0)

    def parse_category(self, response: scrapy.http.Response) -> Any:
        payload = json.loads(response.text)
        for offer in products_to_offers(payload, base_url=self.app_settings.vtex_base_url):
            key = (offer.product_id, offer.sku_id, offer.seller_id)
            if key in self._seen:
                continue
            self._seen.add(key)
            self.offers_processed += 1
            yield offer.model_dump(mode="json")

        resources = (response.headers.get("resources") or b"").decode()
        total = parse_resource_total(resources, len(payload))
        offset = int(response.meta["offset"])
        category_id = str(response.meta["category_id"])
        next_offset = offset + 50
        if next_offset < total:
            yield self._category_request(category_id, next_offset)

    def _category_request(self, category_id: str, offset: int) -> scrapy.Request:
        params = [
            ("fq", f"C:/{category_id}/"),
            ("_from", str(offset)),
            ("_to", str(offset + 49)),
            ("O", "OrderByNameASC"),
            ("sc", self.app_settings.sales_channel),
        ]
        url = (
            f"{self.app_settings.vtex_base_url}/api/catalog_system/pub/products/search?"
            f"{urlencode(params)}"
        )
        return scrapy.Request(
            url,
            callback=self.parse_category,
            meta={"category_id": category_id, "offset": offset},
        )

    @classmethod
    def _leaf_category_ids(cls, nodes: list[dict[str, Any]]) -> list[str]:
        leaves: list[str] = []
        for node in nodes:
            children = node.get("children") or []
            if children:
                leaves.extend(cls._leaf_category_ids(children))
            elif node.get("id") is not None:
                leaves.append(str(node["id"]))
        return sorted(set(leaves), key=int)
