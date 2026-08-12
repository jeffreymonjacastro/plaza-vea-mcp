"""Low-level MCP server implemented with the official Python SDK."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

import httpx
import mcp.server.stdio
import mcp.types as types
from mcp.server.lowlevel import NotificationOptions, Server
from mcp.server.models import InitializationOptions
from pydantic import BaseModel

from plaza_vea_mcp import __version__
from plaza_vea_mcp.config import Settings
from plaza_vea_mcp.db import CatalogRepository, create_database_engine
from plaza_vea_mcp.refresh import RefreshManager
from plaza_vea_mcp.schemas import (
    BuildCartLinksInput,
    BuildCartLinksOutput,
    CatalogRefreshStarted,
    CatalogRefreshStatus,
    GetCatalogRefreshStatusInput,
    GetProductImageInput,
    GetProductInput,
    ListBrandsInput,
    ListBrandsOutput,
    ProductDetails,
    ProductImageOutput,
    SearchProductsInput,
    SearchProductsOutput,
    StartCatalogRefreshInput,
)
from plaza_vea_mcp.service import CatalogService
from plaza_vea_mcp.vtex import VtexClient


@dataclass(slots=True)
class AppContext:
    settings: Settings
    http_client: httpx.AsyncClient
    repository: CatalogRepository
    service: CatalogService
    refresh: RefreshManager


@asynccontextmanager
async def server_lifespan(_server: Server[AppContext]) -> AsyncIterator[AppContext]:
    settings = Settings.from_env()
    settings.ensure_directories()
    repository = CatalogRepository(create_database_engine(settings))
    repository.initialize()
    async with httpx.AsyncClient(
        base_url=settings.vtex_base_url,
        timeout=settings.request_timeout_seconds,
        follow_redirects=True,
        headers={"User-Agent": settings.user_agent, "Accept": "application/json"},
    ) as http_client:
        vtex = VtexClient(settings, http_client)
        service = CatalogService(settings, repository, vtex, http_client)
        refresh = RefreshManager(settings, repository)
        yield AppContext(settings, http_client, repository, service, refresh)
    repository.close()


server: Server[AppContext] = Server("plaza-vea", lifespan=server_lifespan)


def _schema(model: type[BaseModel]) -> dict[str, Any]:
    return model.model_json_schema(mode="validation")


READ_ONLY = types.ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=True,
)
LOCAL_WRITE = types.ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=False,
    idempotentHint=False,
    openWorldHint=True,
)


@server.list_tools()  # type: ignore[untyped-decorator,no-untyped-call]
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="search_products",
            title="Buscar productos de Plaza Vea",
            description=(
                "Busca el catalogo publico por nombre parcial y marca exacta. Puede ordenar por "
                "precio minimo o nombre; precio y stock se revalidan al abrir Plaza Vea."
            ),
            inputSchema=_schema(SearchProductsInput),
            outputSchema=_schema(SearchProductsOutput),
            annotations=READ_ONLY,
        ),
        types.Tool(
            name="get_product",
            title="Consultar un producto",
            description="Devuelve todas las variantes, sellers, ofertas e imagenes de un producto.",
            inputSchema=_schema(GetProductInput),
            outputSchema=_schema(ProductDetails),
            annotations=READ_ONLY,
        ),
        types.Tool(
            name="list_brands",
            title="Listar marcas",
            description="Lista marcas activas y permite filtrar por prefijo.",
            inputSchema=_schema(ListBrandsInput),
            outputSchema=_schema(ListBrandsOutput),
            annotations=READ_ONLY,
        ),
        types.Tool(
            name="get_product_image",
            title="Mostrar imagen de producto",
            description=(
                "Descarga una imagen publica de un SKU y la devuelve como ImageContent PNG para "
                "vision del modelo. Para hacerla visible al usuario en Codex, copia tambien en "
                "la respuesta final el Markdown de imagen incluido en TextContent."
            ),
            inputSchema=_schema(GetProductImageInput),
            outputSchema=_schema(ProductImageOutput),
            annotations=READ_ONLY,
        ),
        types.Tool(
            name="build_cart_links",
            title="Construir enlaces de carrito",
            description=(
                "Valida SKUs y genera enlaces para que el usuario abra Plaza Vea y agregue los "
                "productos. No abre el navegador, no modifica un carrito y no realiza pagos."
            ),
            inputSchema=_schema(BuildCartLinksInput),
            outputSchema=_schema(BuildCartLinksOutput),
            annotations=READ_ONLY,
        ),
        types.Tool(
            name="start_catalog_refresh",
            title="Actualizar cache del catalogo",
            description=(
                "Inicia un crawler Scrapy local en segundo plano. Escribe catalogo e historial de "
                "precios en SQLite, sin modificar datos remotos."
            ),
            inputSchema=_schema(StartCatalogRefreshInput),
            outputSchema=_schema(CatalogRefreshStarted),
            annotations=LOCAL_WRITE,
        ),
        types.Tool(
            name="get_catalog_refresh_status",
            title="Consultar actualizacion del catalogo",
            description="Consulta progreso, resultado y errores de una actualizacion Scrapy.",
            inputSchema=_schema(GetCatalogRefreshStatusInput),
            outputSchema=_schema(CatalogRefreshStatus),
            annotations=READ_ONLY,
        ),
    ]


@server.call_tool()  # type: ignore[untyped-decorator]
async def call_tool(name: str, arguments: dict[str, Any]) -> Any:
    """Validate, dispatch and serialize every MCP tool explicitly."""

    context = server.request_context.lifespan_context
    if name == "search_products":
        search_request = SearchProductsInput.model_validate(arguments)
        search_result = await context.service.search_products(search_request)
        return _result_content(_search_summary(search_result), search_result)
    if name == "get_product":
        product_request = GetProductInput.model_validate(arguments)
        product_result = await context.service.get_product(product_request.product_id)
        return _result_content(
            f"{product_result.product_name}: {len(product_result.offers)} oferta(s) encontrada(s).",
            product_result,
        )
    if name == "list_brands":
        brands_request = ListBrandsInput.model_validate(arguments)
        brands_result = await context.service.list_brands(brands_request)
        return _result_content(
            f"{len(brands_result.brands)} marca(s) encontrada(s).",
            brands_result,
        )
    if name == "get_product_image":
        image_request = GetProductImageInput.model_validate(arguments)
        metadata, image_base64 = await context.service.get_product_image(
            image_request.sku_id,
            image_request.image_index,
        )
        content = [
            types.TextContent(
                type="text",
                text=(
                    f"Imagen {metadata.image_index} de {metadata.product_name} "
                    f"(SKU {metadata.sku_id}, {metadata.width}x{metadata.height}).\n"
                    "Para que el usuario la vea, incluye literalmente este Markdown en tu "
                    f"respuesta final:\n![{metadata.product_name}]({metadata.source_url})"
                ),
            ),
            types.ImageContent(type="image", data=image_base64, mimeType="image/png"),
        ]
        return content, metadata.model_dump(mode="json")
    if name == "build_cart_links":
        cart_request = BuildCartLinksInput.model_validate(arguments)
        cart_result = await context.service.build_cart_links(cart_request)
        return _result_content(
            f"Se generaron enlaces para {len(cart_result.items)} articulo(s). "
            "Abra Plaza Vea para continuar.",
            cart_result,
        )
    if name == "start_catalog_refresh":
        refresh_request = StartCatalogRefreshInput.model_validate(arguments)
        refresh_result = context.refresh.start(refresh_request.category_id)
        return _result_content(
            f"Actualizacion iniciada: {refresh_result.run_id}.",
            refresh_result,
        )
    if name == "get_catalog_refresh_status":
        status_request = GetCatalogRefreshStatusInput.model_validate(arguments)
        status_result = context.refresh.status(status_request.run_id)
        return _result_content(
            f"Actualizacion {status_result.run_id}: {status_result.status}, "
            f"{status_result.products_processed} ofertas.",
            status_result,
        )
    raise ValueError(f"Tool desconocida: {name}")


def _result_content(
    summary: str,
    result: BaseModel,
) -> tuple[list[types.TextContent], dict[str, Any]]:
    structured = result.model_dump(mode="json")
    return [
        types.TextContent(type="text", text=summary),
        types.TextContent(
            type="text",
            text=json.dumps(structured, ensure_ascii=False, indent=2),
        ),
    ], structured


def _search_summary(result: SearchProductsOutput) -> str:
    if not result.products:
        return "No se encontraron productos con esos filtros."
    lowest = min(product.price_cents for product in result.products)
    return (
        f"{len(result.products)} producto(s) encontrado(s); precio minimo S/ {lowest / 100:.2f}. "
        f"Fuente: {result.source}."
    )


async def run() -> None:
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="plaza-vea",
                server_version=__version__,
                capabilities=server.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                ),
            ),
        )


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
