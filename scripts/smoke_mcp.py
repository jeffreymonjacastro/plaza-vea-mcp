"""End-to-end smoke test against the local MCP server and live Plaza Vea catalog."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from typing import Any

import mcp.types as types
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def run() -> dict[str, Any]:
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-m", "plaza_vea_mcp.server"],
        env=os.environ.copy(),
    )
    async with (
        stdio_client(parameters) as (read_stream, write_stream),
        ClientSession(read_stream, write_stream) as session,
    ):
        await session.initialize()
        tools = await session.list_tools()
        search = await session.call_tool(
            "search_products",
            {"name": "pollo", "sort": "price_asc", "only_available": True, "limit": 3},
        )
        if search.isError or not search.structuredContent:
            raise RuntimeError(f"search_products failed: {search.content}")
        products = search.structuredContent["products"]
        if not products:
            raise RuntimeError("search_products returned no live products")
        sku_id = products[0]["sku_id"]
        seller_id = products[0]["seller_id"]

        image = await session.call_tool(
            "get_product_image",
            {"sku_id": sku_id, "image_index": 0},
        )
        image_blocks = [block for block in image.content if isinstance(block, types.ImageContent)]
        if image.isError or not image_blocks:
            raise RuntimeError(f"get_product_image failed: {image.content}")

        cart = await session.call_tool(
            "build_cart_links",
            {"items": [{"sku_id": sku_id, "quantity": 1, "seller_id": seller_id}]},
        )
        if cart.isError or not cart.structuredContent:
            raise RuntimeError(f"build_cart_links failed: {cart.content}")

        return {
            "tools": [tool.name for tool in tools.tools],
            "search_source": search.structuredContent["source"],
            "products": products,
            "image": {
                "mime_type": image_blocks[0].mimeType,
                "base64_characters": len(image_blocks[0].data),
                "metadata": image.structuredContent,
            },
            "cart": cart.structuredContent,
        }


def main() -> None:
    print(json.dumps(asyncio.run(run()), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
