from __future__ import annotations

from typing import Any

from sqlalchemy import func, select

from plaza_vea_mcp.db import CatalogRepository, PriceObservationRecord
from plaza_vea_mcp.vtex import products_to_offers


def test_repository_filters_accents_and_uses_lowest_offer(
    repository: CatalogRepository,
    vtex_products: list[dict[str, Any]],
) -> None:
    offers = products_to_offers(vtex_products, base_url="https://www.plazavea.com.pe")
    assert repository.upsert_offers(offers, run_id="test") == 4

    results = repository.search_products(
        name="cafe",
        brand="marca aguila",
        sort="price_asc",
        only_available=True,
        limit=10,
    )

    assert [product.product_id for product in results] == ["200", "9253"]
    assert [product.price_cents for product in results] == [555, 1240]
    with repository.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(PriceObservationRecord)) == 4
