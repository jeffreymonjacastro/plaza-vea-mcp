from __future__ import annotations

from typing import Any

from plaza_vea_mcp.utils import parse_resource_total
from plaza_vea_mcp.vtex import products_to_offers


def test_products_to_offers_expands_all_skus_and_sellers(
    vtex_products: list[dict[str, Any]],
) -> None:
    offers = products_to_offers(vtex_products, base_url="https://www.plazavea.com.pe")

    assert len(offers) == 4
    assert {(offer.sku_id, offer.seller_id) for offer in offers} == {
        ("9357", "1"),
        ("9357", "marketplace"),
        ("9358", "1"),
        ("201", "1"),
    }
    primary = next(offer for offer in offers if offer.sku_id == "9357" and offer.seller_id == "1")
    assert primary.price_cents == 1240
    assert primary.list_price_cents == 1590
    assert primary.product_url == "https://www.plazavea.com.pe/cafe-peruano-premium/p"
    assert primary.add_to_cart_url.startswith("https://www.plazavea.com.pe/checkout/cart/add")
    unavailable = next(offer for offer in offers if offer.sku_id == "9358")
    assert unavailable.is_available is False


def test_resource_header_total() -> None:
    assert parse_resource_total("0-49/453", 50) == 453
    assert parse_resource_total(None, 7) == 7
