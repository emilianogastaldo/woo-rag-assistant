from unittest.mock import AsyncMock

import pytest

from app.resilience import RecoverableFailure
from app.tools.catalog import CatalogService


async def test_catalog_overview_reads_published_products_and_marks_partial_results():
    woo = AsyncMock()
    woo.get_json.return_value = [
        {"name": f"Product {i}", "sku": f"SKU-{i}", "price": "19.90",
         "stock_status": "instock", "permalink": f"http://store/product/{i}"}
        for i in range(11)
    ]
    result = await CatalogService(woo).list_products()
    woo.get_json.assert_awaited_once_with(
        "products", {"status": "publish", "per_page": 11, "orderby": "id", "order": "asc"}
    )
    assert result.count("Prodotto:") == 10
    assert "SKU-10" not in result
    assert "Elenco parziale" in result
    assert "19.90 EUR" in result
    assert "http://store/product/0" in result


async def test_empty_catalog():
    woo = AsyncMock()
    woo.get_json.return_value = []
    assert "Nessun prodotto pubblicato" in await CatalogService(woo).list_products()


@pytest.mark.parametrize("rows", [{"error": "bad"}, [None]])
async def test_catalog_rejects_malformed_response(rows):
    woo = AsyncMock()
    woo.get_json.return_value = rows
    with pytest.raises(RecoverableFailure):
        await CatalogService(woo).list_products()
