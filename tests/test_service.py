from __future__ import annotations

import base64
from io import BytesIO
from typing import Any

import httpx
import pytest
from PIL import Image

from plaza_vea_mcp.config import Settings
from plaza_vea_mcp.db import CatalogRepository
from plaza_vea_mcp.schemas import BuildCartLinksInput, SearchProductsInput
from plaza_vea_mcp.service import CatalogService
from plaza_vea_mcp.vtex import VtexClient


def _png_bytes() -> bytes:
    output = BytesIO()
    Image.new("RGB", (1600, 800), color=(10, 120, 200)).save(output, format="PNG")
    return output.getvalue()


@pytest.mark.asyncio
async def test_search_image_and_cart_links(
    settings: Settings,
    repository: CatalogRepository,
    vtex_products: list[dict[str, Any]],
) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "plazavea.vteximg.com.br":
            return httpx.Response(200, content=_png_bytes(), headers={"content-type": "image/png"})
        if request.url.path.endswith("/products/search"):
            sku_filter = request.url.params.get("fq", "")
            products = vtex_products
            if sku_filter.startswith("skuId:"):
                sku_id = sku_filter.split(":", 1)[1]
                products = [
                    product
                    for product in vtex_products
                    if any(str(item["itemId"]) == sku_id for item in product["items"])
                ]
            return httpx.Response(
                206,
                json=products,
                headers={"resources": f"0-49/{len(products)}"},
            )
        raise AssertionError(f"Unexpected request: {request.url}")

    async with httpx.AsyncClient(
        base_url=settings.vtex_base_url,
        transport=httpx.MockTransport(handler),
    ) as http_client:
        service = CatalogService(
            settings,
            repository,
            VtexClient(settings, http_client),
            http_client,
        )
        search = await service.search_products(
            SearchProductsInput(name="cafe", sort="price_asc", limit=10)
        )
        assert search.source == "live"
        assert [product.price_cents for product in search.products] == [555, 1240]

        metadata, encoded = await service.get_product_image("9357", 0)
        assert metadata.width == 512
        assert metadata.height == 256
        assert base64.b64decode(encoded).startswith(b"\x89PNG")

        links = await service.build_cart_links(
            BuildCartLinksInput.model_validate(
                {"items": [{"sku_id": "9357", "quantity": 3, "seller_id": "1"}]}
            )
        )
        assert "qty=3" in links.items[0].add_to_cart_url
        assert links.combined_cart_url is not None
        assert "sku=9357" in links.combined_cart_url
        assert links.checkout_url.endswith("/checkout/#/cart")


@pytest.mark.asyncio
async def test_live_failure_uses_sqlite_cache(
    settings: Settings,
    repository: CatalogRepository,
    vtex_products: list[dict[str, Any]],
) -> None:
    from plaza_vea_mcp.vtex import products_to_offers

    repository.upsert_offers(products_to_offers(vtex_products, base_url=settings.vtex_base_url))

    async def fail(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline", request=request)

    async with httpx.AsyncClient(
        base_url=settings.vtex_base_url,
        transport=httpx.MockTransport(fail),
    ) as http_client:
        service = CatalogService(
            settings,
            repository,
            VtexClient(settings, http_client),
            http_client,
        )
        result = await service.search_products(
            SearchProductsInput(name="cafe", brand="marca aguila", limit=10)
        )
        assert result.source == "cache"
        assert result.stale is True
        assert len(result.products) == 2
