"""Pydantic domain models and MCP input/output schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CatalogOffer(StrictModel):
    product_id: str
    product_name: str
    brand: str
    categories: list[str] = Field(default_factory=list)
    product_url: str
    sku_id: str
    sku_name: str
    seller_id: str
    seller_name: str
    price_cents: int = Field(ge=0)
    list_price_cents: int = Field(ge=0)
    currency: Literal["PEN"] = "PEN"
    is_available: bool
    available_quantity: int = Field(ge=0)
    image_urls: list[str] = Field(default_factory=list)
    add_to_cart_url: str
    fetched_at: datetime


class ProductSummary(StrictModel):
    product_id: str
    product_name: str
    brand: str
    categories: list[str]
    product_url: str
    sku_id: str
    sku_name: str
    seller_id: str
    seller_name: str
    price_cents: int
    list_price_cents: int
    currency: Literal["PEN"] = "PEN"
    is_available: bool
    image_url: str | None
    fetched_at: datetime

    @classmethod
    def from_offer(cls, offer: CatalogOffer) -> ProductSummary:
        return cls(
            product_id=offer.product_id,
            product_name=offer.product_name,
            brand=offer.brand,
            categories=offer.categories,
            product_url=offer.product_url,
            sku_id=offer.sku_id,
            sku_name=offer.sku_name,
            seller_id=offer.seller_id,
            seller_name=offer.seller_name,
            price_cents=offer.price_cents,
            list_price_cents=offer.list_price_cents,
            is_available=offer.is_available,
            image_url=offer.image_urls[0] if offer.image_urls else None,
            fetched_at=offer.fetched_at,
        )


class SearchProductsInput(StrictModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    brand: str | None = Field(default=None, min_length=1, max_length=100)
    sort: Literal["price_asc", "price_desc", "name_asc"] = "price_asc"
    only_available: bool = True
    limit: int = Field(default=20, ge=1, le=50)


class SearchProductsOutput(StrictModel):
    products: list[ProductSummary]
    source: Literal["live", "cache"]
    stale: bool
    fetched_at: datetime


class GetProductInput(StrictModel):
    product_id: str = Field(min_length=1, max_length=64)


class ProductDetails(StrictModel):
    product_id: str
    product_name: str
    brand: str
    categories: list[str]
    product_url: str
    offers: list[CatalogOffer]
    source: Literal["live", "cache"]
    stale: bool
    fetched_at: datetime


class ListBrandsInput(StrictModel):
    prefix: str | None = Field(default=None, max_length=100)
    limit: int = Field(default=50, ge=1, le=100)


class BrandSummary(StrictModel):
    brand: str
    available_product_count: int | None = Field(default=None, ge=0)


class ListBrandsOutput(StrictModel):
    brands: list[BrandSummary]
    source: Literal["live", "cache"]
    stale: bool
    fetched_at: datetime


class GetProductImageInput(StrictModel):
    sku_id: str = Field(min_length=1, max_length=64)
    image_index: int = Field(default=0, ge=0, le=20)


class ProductImageOutput(StrictModel):
    product_id: str
    product_name: str
    sku_id: str
    image_index: int
    source_url: HttpUrl
    mime_type: Literal["image/png"] = "image/png"
    width: int = Field(gt=0)
    height: int = Field(gt=0)


class CartItemInput(StrictModel):
    sku_id: str = Field(min_length=1, max_length=64)
    quantity: int = Field(default=1, ge=1, le=99)
    seller_id: str = Field(default="1", min_length=1, max_length=64)


class BuildCartLinksInput(StrictModel):
    items: list[CartItemInput] = Field(min_length=1, max_length=30)

    @model_validator(mode="after")
    def unique_sku_sellers(self) -> BuildCartLinksInput:
        keys = [(item.sku_id, item.seller_id) for item in self.items]
        if len(keys) != len(set(keys)):
            raise ValueError("Cada combinacion de sku_id y seller_id debe aparecer una sola vez")
        return self


class CartLinkItem(StrictModel):
    product_id: str
    product_name: str
    sku_id: str
    seller_id: str
    quantity: int
    price_cents: int
    product_url: str
    add_to_cart_url: str


class BuildCartLinksOutput(StrictModel):
    items: list[CartLinkItem]
    combined_cart_url: str | None
    checkout_url: str
    warning: str


class StartCatalogRefreshInput(StrictModel):
    category_id: str | None = Field(default=None, pattern=r"^\d+$")


class CatalogRefreshStarted(StrictModel):
    run_id: str
    status: Literal["queued", "running"]
    category_id: str | None
    started_at: datetime


class GetCatalogRefreshStatusInput(StrictModel):
    run_id: str = Field(min_length=8, max_length=64)


class CatalogRefreshStatus(StrictModel):
    run_id: str
    status: Literal["queued", "running", "completed", "failed"]
    category_id: str | None
    started_at: datetime
    finished_at: datetime | None
    products_processed: int = Field(ge=0)
    error: str | None
    pid: int | None
