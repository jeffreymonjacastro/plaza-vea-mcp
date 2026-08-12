"""Application services exposed through MCP tools."""

from __future__ import annotations

import base64
from io import BytesIO
from typing import Literal
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import httpx
from PIL import Image, ImageOps

from plaza_vea_mcp.config import Settings
from plaza_vea_mcp.db import CatalogRepository
from plaza_vea_mcp.schemas import (
    BrandSummary,
    BuildCartLinksInput,
    BuildCartLinksOutput,
    CartLinkItem,
    CatalogOffer,
    ListBrandsInput,
    ListBrandsOutput,
    ProductDetails,
    ProductImageOutput,
    ProductSummary,
    SearchProductsInput,
    SearchProductsOutput,
)
from plaza_vea_mcp.utils import utc_now
from plaza_vea_mcp.vtex import BrandNotFoundError, VtexClient, VtexError


class CatalogService:
    def __init__(
        self,
        settings: Settings,
        repository: CatalogRepository,
        vtex: VtexClient,
        http_client: httpx.AsyncClient,
    ):
        self.settings = settings
        self.repository = repository
        self.vtex = vtex
        self.http_client = http_client

    async def search_products(self, request: SearchProductsInput) -> SearchProductsOutput:
        try:
            offers = await self.vtex.search_offers(
                name=request.name,
                brand=request.brand,
                sort=request.sort,
                only_available=request.only_available,
                limit=request.limit,
            )
            self.repository.upsert_offers(offers)
            products = [ProductSummary.from_offer(offer) for offer in offers]
            fetched_at = max((offer.fetched_at for offer in offers), default=utc_now())
            return SearchProductsOutput(
                products=products,
                source="live",
                stale=False,
                fetched_at=fetched_at,
            )
        except BrandNotFoundError:
            raise
        except VtexError as exc:
            products = self.repository.search_products(
                name=request.name,
                brand=request.brand,
                sort=request.sort,
                only_available=request.only_available,
                limit=request.limit,
            )
            if not products:
                raise VtexError(
                    "VTEX no esta disponible y el cache local no contiene resultados"
                ) from exc
            return SearchProductsOutput(
                products=products,
                source="cache",
                stale=True,
                fetched_at=max(product.fetched_at for product in products),
            )

    async def get_product(self, product_id: str) -> ProductDetails:
        try:
            offers = await self.vtex.get_product_offers(product_id)
            if not offers:
                raise ValueError(f"No se encontro el producto {product_id}")
            self.repository.upsert_offers(offers)
            return self._product_details(offers, source="live", stale=False)
        except VtexError as exc:
            cached = self.repository.get_product(product_id)
            if cached is None:
                raise VtexError(
                    "VTEX no esta disponible y el producto no existe en el cache local"
                ) from exc
            return cached

    async def list_brands(self, request: ListBrandsInput) -> ListBrandsOutput:
        try:
            brands = await self.vtex.list_brands(request.prefix, request.limit)
            cached_counts = {
                entry.brand.casefold(): entry.available_product_count
                for entry in self.repository.list_brands(request.prefix, request.limit)
            }
            enriched = [
                BrandSummary(
                    brand=entry.brand,
                    available_product_count=cached_counts.get(entry.brand.casefold()),
                )
                for entry in brands
            ]
            return ListBrandsOutput(
                brands=enriched,
                source="live",
                stale=False,
                fetched_at=utc_now(),
            )
        except VtexError as exc:
            brands = self.repository.list_brands(request.prefix, request.limit)
            if not brands:
                raise VtexError(
                    "VTEX no esta disponible y el cache local no contiene marcas"
                ) from exc
            return ListBrandsOutput(
                brands=brands,
                source="cache",
                stale=True,
                fetched_at=utc_now(),
            )

    async def get_product_image(
        self,
        sku_id: str,
        image_index: int,
    ) -> tuple[ProductImageOutput, str]:
        offers = await self._sku_offers_live_first(sku_id)
        offer = next((candidate for candidate in offers if candidate.image_urls), None)
        if offer is None:
            raise ValueError(f"El SKU {sku_id} no tiene imagenes")
        if image_index >= len(offer.image_urls):
            raise ValueError(
                f"image_index fuera de rango; el SKU {sku_id} tiene "
                f"{len(offer.image_urls)} imagenes"
            )
        source_url = offer.image_urls[image_index]
        self._validate_image_url(source_url)
        response = await self.http_client.get(source_url)
        response.raise_for_status()
        content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
        if not content_type.startswith("image/"):
            raise ValueError(f"La URL no devolvio una imagen valida: {content_type or 'sin MIME'}")
        if len(response.content) > 15 * 1024 * 1024:
            raise ValueError("La imagen supera el limite de 15 MB")

        with Image.open(BytesIO(response.content)) as opened:
            image = ImageOps.exif_transpose(opened)
            # Keep inline MCP images compact enough for text-oriented clients while
            # remaining comfortably below the public contract's 1024 px ceiling.
            image.thumbnail((512, 512), Image.Resampling.LANCZOS)
            if image.mode not in {"RGB", "RGBA"}:
                image = image.convert("RGBA" if "transparency" in image.info else "RGB")
            output = BytesIO()
            image.save(output, format="PNG", optimize=True)
            width, height = image.size

        metadata = ProductImageOutput(
            product_id=offer.product_id,
            product_name=offer.product_name,
            sku_id=offer.sku_id,
            image_index=image_index,
            source_url=source_url,
            width=width,
            height=height,
        )
        return metadata, base64.b64encode(output.getvalue()).decode("ascii")

    async def build_cart_links(self, request: BuildCartLinksInput) -> BuildCartLinksOutput:
        accepted: list[CartLinkItem] = []
        rejected: list[str] = []
        combined_params: list[tuple[str, str]] = []
        for item in request.items:
            offers = await self.vtex.get_sku_offers(item.sku_id)
            offer = next(
                (
                    candidate
                    for candidate in offers
                    if candidate.seller_id == item.seller_id and candidate.is_available
                ),
                None,
            )
            if offer is None:
                rejected.append(f"SKU {item.sku_id} / seller {item.seller_id}")
                continue
            accepted.append(
                CartLinkItem(
                    product_id=offer.product_id,
                    product_name=offer.product_name,
                    sku_id=offer.sku_id,
                    seller_id=offer.seller_id,
                    quantity=item.quantity,
                    price_cents=offer.price_cents,
                    product_url=offer.product_url,
                    add_to_cart_url=self._with_quantity(offer.add_to_cart_url, item.quantity),
                )
            )
            combined_params.extend(
                [
                    ("sku", offer.sku_id),
                    ("qty", str(item.quantity)),
                    ("seller", offer.seller_id),
                ]
            )
        if rejected:
            raise ValueError(
                "No se genero ningun enlace porque estos articulos no estan disponibles: "
                + ", ".join(rejected)
            )

        combined_params.extend([("redirect", "true"), ("sc", self.settings.sales_channel)])
        combined_url = (
            f"{self.settings.vtex_base_url}/checkout/cart/add?{urlencode(combined_params)}"
            if accepted
            else None
        )
        return BuildCartLinksOutput(
            items=accepted,
            combined_cart_url=combined_url,
            checkout_url=f"{self.settings.vtex_base_url}/checkout/#/cart",
            warning=(
                "Precio, stock, promociones y entrega se validan nuevamente en Plaza Vea. "
                "El enlace combinado depende del soporte vigente de VTEX; use los enlaces "
                "individuales si la tienda lo rechaza."
            ),
        )

    async def _sku_offers_live_first(self, sku_id: str) -> list[CatalogOffer]:
        try:
            offers = await self.vtex.get_sku_offers(sku_id)
            if not offers:
                raise ValueError(f"No se encontro el SKU {sku_id}")
            self.repository.upsert_offers(offers)
            return offers
        except VtexError as exc:
            cached = self.repository.get_sku_offers(sku_id)
            if not cached:
                raise VtexError(
                    "VTEX no esta disponible y el SKU no existe en el cache local"
                ) from exc
            return cached

    @staticmethod
    def _product_details(
        offers: list[CatalogOffer],
        *,
        source: Literal["live", "cache"],
        stale: bool,
    ) -> ProductDetails:
        first = offers[0]
        return ProductDetails(
            product_id=first.product_id,
            product_name=first.product_name,
            brand=first.brand,
            categories=first.categories,
            product_url=first.product_url,
            offers=offers,
            source=source,
            stale=stale,
            fetched_at=max(offer.fetched_at for offer in offers),
        )

    @staticmethod
    def _validate_image_url(value: str) -> None:
        parsed = urlparse(value)
        hostname = (parsed.hostname or "").lower()
        allowed = hostname == "plazavea.com.pe" or hostname.endswith(".plazavea.com.pe")
        allowed = allowed or hostname == "vteximg.com.br" or hostname.endswith(".vteximg.com.br")
        if parsed.scheme != "https" or not allowed:
            raise ValueError("La imagen no pertenece a un host HTTPS permitido de Plaza Vea/VTEX")

    @staticmethod
    def _with_quantity(url: str, quantity: int) -> str:
        if not url:
            raise ValueError("VTEX no devolvio addToCartLink para un articulo seleccionado")
        parsed = urlparse(url)
        params = parse_qsl(parsed.query, keep_blank_values=True)
        updated: list[tuple[str, str]] = []
        replaced = False
        for key, value in params:
            if key == "qty":
                if not replaced:
                    updated.append((key, str(quantity)))
                    replaced = True
            else:
                updated.append((key, value))
        if not replaced:
            updated.append(("qty", str(quantity)))
        return urlunparse(parsed._replace(query=urlencode(updated)))
