from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from pydantic import BaseModel

from plaza_vea_mcp.server import _result_content


class ExampleResult(BaseModel):
    value: int


def test_result_content_avoids_client_incompatible_content_annotations() -> None:
    content, structured = _result_content("Resultado", ExampleResult(value=1))

    assert structured == {"value": 1}
    assert all(block.annotations is None for block in content)


@pytest.mark.asyncio
async def test_stdio_server_lists_tools_and_returns_validation_error(tmp_path: Path) -> None:
    environment = os.environ.copy()
    environment.update(
        {
            "PLAZA_VEA_PROJECT_ROOT": str(tmp_path),
            "PLAZA_VEA_DATA_DIR": str(tmp_path / "data"),
        }
    )
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-m", "plaza_vea_mcp.server"],
        env=environment,
    )
    async with (
        stdio_client(parameters) as (read_stream, write_stream),
        ClientSession(read_stream, write_stream) as session,
    ):
        await session.initialize()
        tools = await session.list_tools()
        assert {tool.name for tool in tools.tools} == {
            "search_products",
            "get_product",
            "list_brands",
            "get_product_image",
            "build_cart_links",
            "start_catalog_refresh",
            "get_catalog_refresh_status",
        }
        invalid = await session.call_tool("search_products", {"limit": 100})
        assert invalid.isError is True
        assert "Input validation error" in invalid.content[0].text  # type: ignore[union-attr]
