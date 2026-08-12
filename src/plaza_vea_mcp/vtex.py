"""Client and parsers for Plaza Vea's public VTEX catalog endpoints."""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

import httpx

from plaza_vea_mcp.config import Settings
from plaza_vea_mcp.schemas import BrandSummary, CatalogOffer
from plaza_vea_mcp.utils import (
    absolute_url,
    normalize_text,
    parse_resource_total,
    soles_to_cents,
    utc_now,
)


class VtexError(RuntimeError):
    """Base exception for remote catalog failures."""


class BrandNotFoundError(ValueError):
    """Raised when a requested exact brand does not exist in the active brand list."""


def products_to_offers(
    products: list[dict[str, Any]],
    *,
    base_url: str,
    fetched_at: datetime | None = None,
) -> list[CatalogOffer]:
    """Expand every VTEX product into one record per SKU and seller."""

    observed_at = fetched_at or utc_now()
    offers: list[CatalogOffer] = []
    for product in products:
        categories = [str(value).strip("/") for value in product.get("categories", []) if value]
        product_url = absolute_url(base_url, product.get("link"))
        for item in product.get("items") or []:
            image_urls = [
                absolute_url(base_url, image.get("imageUrl"))
                for image in item.get("images") or []
                if image.get("imageUrl")
            ]
            for seller in item.get("sellers") or []:
                commercial_offer = seller.get("commertialOffer") or {}
                quantity = max(int(commercial_offer.get("AvailableQuantity") or 0), 0)
                is_available = (
                    bool(commercial_offer.get("IsAvailable", quantity > 0)) and quantity > 0
                )
                offers.append(
                    CatalogOffer(
                        product_id=str(product.get("productId") or ""),
                        product_name=str(product.get("productName") or "").strip(),
                        brand=str(product.get("brand") or "").strip(),
                        categories=categories,
                        product_url=product_url,
                        sku_id=str(item.get("itemId") or ""),
                        sku_name=str(item.get("nameComplete") or item.get("name") or "").strip(),
                        seller_id=str(seller.get("sellerId") or ""),
                        seller_name=str(seller.get("sellerName") or "").strip(),
                        price_cents=soles_to_cents(commercial_offer.get("Price")),
                        list_price_cents=soles_to_cents(commercial_offer.get("ListPrice")),
                        is_available=is_available,
                        available_quantity=quantity,
                        image_urls=image_urls,
                        add_to_cart_url=absolute_url(base_url, seller.get("addToCartLink")),
                        fetched_at=observed_at,
                    )
                )
    return [offer for offer in offers if offer.product_id and offer.sku_id and offer.seller_id]


class VtexClient:
    SEARCH_PATH = "/api/catalog_system/pub/products/search"
    BRAND_PATH = "/api/catalog_system/pub/brand/list"
    CATEGORY_TREE_PATH = "/api/catalog_system/pub/category/tree/10"

    def __init__(self, settings: Settings, client: httpx.AsyncClient):
        self.settings = settings
        self.client = client
        self._brand_cache: list[dict[str, Any]] | None = None

    async def search_offers(
        self,
        *,
        name: str | None,
        brand: str | None,
        sort: str,
        only_available: bool,
        limit: int,
    ) -> list[CatalogOffer]:
        params: dict[str, str | int] = {
            "_from": 0,
            "_to": 49,
            "O": self._vtex_sort(sort),
            "sc": self.settings.sales_channel,
        }
        if name:
            params["ft"] = name
        if brand:
            brand_id = await self.resolve_brand_id(brand)
            params["fq"] = f"B:{brand_id}"

        matches: list[CatalogOffer] = []
        offset = 0
        total = 1
        pages = 0
        while offset < total and len(matches) < limit and pages < 10:
            params["_from"] = offset
            params["_to"] = offset + 49
            response = await self._request("GET", self.SEARCH_PATH, params=params)
            payload = response.json()
            if not isinstance(payload, list):
                raise VtexError("VTEX devolvio una respuesta de busqueda inesperada")
            offers = products_to_offers(
                payload,
                base_url=self.settings.vtex_base_url,
                fetched_at=utc_now(),
            )
            matches.extend(
                offer
                for offer in offers
                if (not name or normalize_text(name) in normalize_text(offer.product_name))
                and (not brand or normalize_text(brand) == normalize_text(offer.brand))
                and (not only_available or offer.is_available)
            )
            total = parse_resource_total(response.headers.get("resources"), len(payload))
            offset += 50
            pages += 1

        return self._best_offers(matches, sort, limit)

    async def get_product_offers(self, product_id: str) -> list[CatalogOffer]:
        return await self._get_by_filter(f"productId:{product_id}")

    async def get_sku_offers(self, sku_id: str) -> list[CatalogOffer]:
        return await self._get_by_filter(f"skuId:{sku_id}")

    async def _get_by_filter(self, filter_value: str) -> list[CatalogOffer]:
        response = await self._request(
            "GET",
            self.SEARCH_PATH,
            params={
                "fq": filter_value,
                "_from": 0,
                "_to": 49,
                "sc": self.settings.sales_channel,
            },
        )
        payload = response.json()
        if not isinstance(payload, list):
            raise VtexError("VTEX devolvio una respuesta de producto inesperada")
        return products_to_offers(payload, base_url=self.settings.vtex_base_url)

    async def list_brands(self, prefix: str | None, limit: int) -> list[BrandSummary]:
        brands = await self._active_brands()
        normalized_prefix = normalize_text(prefix) if prefix else ""
        names = sorted(
            {
                str(brand.get("name") or "").strip()
                for brand in brands
                if str(brand.get("name") or "").strip()
                and (
                    not normalized_prefix
                    or normalize_text(str(brand.get("name") or "")).startswith(normalized_prefix)
                )
            },
            key=normalize_text,
        )
        return [BrandSummary(brand=name, available_product_count=None) for name in names[:limit]]

    async def resolve_brand_id(self, brand_name: str) -> int:
        normalized = normalize_text(brand_name)
        for brand in await self._active_brands():
            if normalize_text(str(brand.get("name") or "")) == normalized:
                return int(brand["id"])
        raise BrandNotFoundError(f"No existe una marca activa con el nombre exacto: {brand_name}")

    async def category_tree(self) -> list[dict[str, Any]]:
        response = await self._request("GET", self.CATEGORY_TREE_PATH)
        payload = response.json()
        if not isinstance(payload, list):
            raise VtexError("VTEX devolvio un arbol de categorias inesperado")
        return payload

    async def _active_brands(self) -> list[dict[str, Any]]:
        if self._brand_cache is None:
            response = await self._request("GET", self.BRAND_PATH)
            payload = response.json()
            if not isinstance(payload, list):
                raise VtexError("VTEX devolvio una lista de marcas inesperada")
            self._brand_cache = [brand for brand in payload if brand.get("isActive")]
        return self._brand_cache

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str | int] | None = None,
    ) -> httpx.Response:
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                response = await self.client.request(method, path, params=params)
                if response.status_code == 429 or response.status_code >= 500:
                    raise VtexError(f"VTEX respondio HTTP {response.status_code}")
                response.raise_for_status()
                return response
            except (httpx.HTTPError, VtexError) as exc:
                last_error = exc
                if attempt < 2:
                    await asyncio.sleep(0.5 * (2**attempt))
        raise VtexError(f"No se pudo consultar VTEX: {last_error}") from last_error

    @staticmethod
    def _vtex_sort(sort: str) -> str:
        return {
            "price_asc": "OrderByPriceASC",
            "price_desc": "OrderByPriceDESC",
            "name_asc": "OrderByNameASC",
        }[sort]

    @staticmethod
    def _best_offers(offers: list[CatalogOffer], sort: str, limit: int) -> list[CatalogOffer]:
        by_product: dict[str, CatalogOffer] = {}
        for offer in offers:
            current = by_product.get(offer.product_id)
            candidate_rank = (not offer.is_available, offer.price_cents)
            if current is None or candidate_rank < (not current.is_available, current.price_cents):
                by_product[offer.product_id] = offer
        result = list(by_product.values())
        if sort == "price_desc":
            result.sort(key=lambda offer: offer.price_cents, reverse=True)
        elif sort == "name_asc":
            result.sort(key=lambda offer: normalize_text(offer.product_name))
        else:
            result.sort(key=lambda offer: offer.price_cents)
        return result[:limit]
