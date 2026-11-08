from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from app.config import settings
from app.resilience import RecoverableFailure
from app.tools.catalog import CatalogService, ProductSearch
from tests.conftest import FakeWooClient


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


def make_product(product_id=1, **overrides):
    return {"id": product_id, "name": f"Prodotto {product_id}", "sku": f"SKU-{product_id}",
            "price": "19.90", "stock_status": "instock", "status": "publish",
            "catalog_visibility": "visible", "type": "simple",
            "permalink": f"https://store.test/product/{product_id}",
            "images": [{"src": "https://store.test/product.jpg"}],
            "categories": [{"id": 7, "name": "Accessori", "slug": "accessori"}], **overrides}


async def test_filtered_search_uses_real_category_and_rechecks_budget_visibility_stock(monkeypatch):
    monkeypatch.setattr(settings, "wc_currency", "GBP")
    woo = FakeWooClient({
        "products/categories": [{"id": 7, "name": "Accessori", "slug": "accessori"}],
        "products": [make_product(), make_product(2, price="51"),
                     make_product(3, stock_status="outofstock"),
                     make_product(4, status="private"),
                     make_product(5, catalog_visibility="hidden"),
                     make_product(6, categories=[{"id": 8}]),
                     make_product(7, price="")],
    })
    result = await CatalogService(woo).search_products(category="Accessori", min_price=0,
                                                       max_price=50, page=2, per_page=10)
    assert [p.id for p in result.products] == [1]
    assert result.products[0].currency == "GBP"
    assert result.products[0].image == "https://store.test/product.jpg"
    assert woo.params_for("products") == {
        "status": "publish", "page": 2, "per_page": 10, "orderby": "id", "order": "asc",
        "stock_status": "instock", "min_price": "0.0", "max_price": "50.0", "category": 7,
    }
    assert len(woo.calls) == 2


async def test_paging_does_not_scan_catalog_and_marks_possible_more_results():
    woo = FakeWooClient({"products": lambda params: [make_product(params["page"])]})
    service = CatalogService(woo)
    first = await service.search_products(per_page=1)
    second = await service.search_products(page=2, per_page=1, query="regalo")
    assert [p.id for p in first.products] == [1]
    assert [p.id for p in second.products] == [2]
    assert second.may_have_more
    assert len(woo.calls) == 2
    assert woo.calls[1][1]["search"] == "regalo"


@pytest.mark.parametrize("categories", [[], [{"id": 7, "name": "Accessori"},
                                           {"id": 8, "slug": "accessori"}]])
async def test_category_must_be_verified_and_unambiguous(categories):
    woo = FakeWooClient({"products/categories": categories})
    result = await CatalogService(woo).search_products(category="accessori")
    assert result.products == []
    assert "Categoria non identificata" in result.message
    assert len(woo.calls) == 1


@pytest.mark.parametrize("filters", [
    {"page": 0}, {"page": 101}, {"per_page": 11}, {"category": 7}, {"stock_status": "oops"},
    {"max_price": -1}, {"max_price": float("inf")}, {"max_price": float("nan")},
    {"min_price": 20, "max_price": 10}, {"query": "x" * 201}, {"customer_id": 123},
])
async def test_invalid_search_never_calls_woo(filters):
    woo = FakeWooClient()
    with pytest.raises(ValidationError):
        await CatalogService(woo).search_products(**filters)
    assert woo.calls == []


async def test_zero_and_unavailable_prices_and_stock_opt_in():
    woo = FakeWooClient({"products": [make_product(price="0"), make_product(2, price=""),
                                     make_product(3, stock_status="outofstock")]})
    service = CatalogService(woo)
    free = await service.search_products(max_price=0)
    assert [(p.id, p.price) for p in free.products] == [(1, "0")]
    all_stock = await service.search_products(stock_status="any")
    assert [p.id for p in all_stock.products] == [1, 2, 3]
    assert all_stock.products[1].price is None
    assert "stock_status" not in woo.calls[-1][1]


async def test_variable_product_uses_only_current_matching_variants():
    woo = FakeWooClient({
        "products": [make_product(type="variable", price="1")],
        "products/1/variations": [
            {"id": 11, "status": "publish", "price": "49.90", "stock_status": "instock",
             "attributes": [{"name": "Colore", "option": "Blu"}]},
            {"id": 12, "status": "publish", "price": "51", "stock_status": "instock"},
            {"id": 13, "status": "publish", "price": "1", "stock_status": "outofstock"},
            {"id": 14, "status": "private", "price": "1", "stock_status": "instock"},
        ],
    })
    result = await CatalogService(woo).search_products(max_price=50)
    product = result.products[0]
    assert product.price is None
    assert [v.id for v in product.variants] == [11]
    assert product.variants[0].attributes == {"Colore": "Blu"}
    assert product.variants[0].price == "49.90"
    assert woo.params_for("products/1/variations")["per_page"] == 10
    assert len(woo.calls) == 2


async def test_variable_unknown_or_nonmatching_variants_are_not_recommended():
    woo = FakeWooClient({"products": [make_product(type="variable")],
                         "products/1/variations": []})
    result = await CatalogService(woo).search_products(max_price=50)
    assert result.products == []


@pytest.mark.parametrize("change", [{"id": "1"}, {"price": "NaN"}, {"price": "-1"},
                                     {"images": "wrong"}, {"stock_status": "perhaps"}])
async def test_structured_search_rejects_malformed_products(change):
    woo = FakeWooClient({"products": [make_product(**change)]})
    with pytest.raises(RecoverableFailure):
        await CatalogService(woo).search_products()


async def test_invalid_product_urls_are_omitted():
    woo = FakeWooClient({"products": [make_product(permalink="javascript:alert(1)",
                                                 images=[{"src": "https://user:secret@x/a"}])]})
    product = (await CatalogService(woo).search_products()).products[0]
    assert product.url is None
    assert product.image is None


async def test_sku_then_name_lookup_stays_compatible_and_filters_hidden(monkeypatch):
    monkeypatch.setattr(settings, "wc_currency", "USD")
    woo = FakeWooClient({"products": lambda params: [] if "sku" in params else [
        make_product(), make_product(2, catalog_visibility="hidden")]})
    result = await CatalogService(woo).check_availability("prod")
    assert woo.calls[0][1]["sku"] == "prod"
    assert woo.calls[1][1]["search"] == "prod"
    assert "19.90 USD" in result
    assert "Prodotto 2" not in result


def test_currency_config_is_an_iso_code():
    from app.config import Settings

    assert Settings(_env_file=None, wc_currency="GBP").wc_currency == "GBP"
    with pytest.raises(ValidationError):
        Settings(_env_file=None, wc_currency="<bad>")


def test_tool_search_schema_bounds_are_shared_with_service():
    assert ProductSearch().stock_status == "instock"
