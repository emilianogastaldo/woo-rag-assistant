"""Tool catalogo: disponibilità e prezzo in tempo reale.

Lo stock è stato *dinamico*: non viene indicizzato nel RAG (dove sarebbe subito
obsoleto) ma letto al momento dalle API WooCommerce. Il tool è disponibile anche
agli utenti anonimi: non espone nulla di riservato.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError, model_validator

from app.config import settings
from app.resilience import FailureKind, RecoverableFailure
from app.tools.woo_client import WooClient, shared_woo_client

NOT_FOUND = (
    "Nessun prodotto corrispondente nel catalogo. Comunica che non risulta a "
    "catalogo e non inventare disponibilità o prezzi."
)

STOCK_LABELS = {
    "instock": "disponibile",
    "outofstock": "esaurito",
    "onbackorder": "ordinabile su prenotazione",
}


def safe_url(value: str | None) -> str | None:
    """Woo URLs are untrusted; preserve local demo URLs, never active schemes/credentials."""
    if not value or any(ord(char) < 33 for char in value) or "\\" in value:
        return None
    try:
        parsed = urlsplit(value)
        if (parsed.scheme in {"http", "https"} and parsed.hostname
                and not parsed.username and not parsed.password):
            return value
    except ValueError:
        pass
    return None


class ProductSearch(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True,
                              allow_inf_nan=False)

    query: str = Field(default="", max_length=200)
    category: str | None = Field(default=None, min_length=1, max_length=100,
                                description="Nome o slug della categoria, mai un ID inventato")
    min_price: float | None = Field(default=None, ge=0, le=1_000_000_000)
    max_price: float | None = Field(default=None, ge=0, le=1_000_000_000)
    stock_status: str = Field(default="instock", pattern="^(instock|outofstock|onbackorder|any)$")
    page: int = Field(default=1, ge=1, le=100)
    per_page: int = Field(default=3, ge=1, le=10)

    @model_validator(mode="after")
    def ordered_prices(self):
        if (self.min_price is not None and self.max_price is not None
                and self.min_price > self.max_price):
            raise ValueError("min_price must be <= max_price")
        return self


class WooImage(BaseModel):
    model_config = ConfigDict(strict=True)
    src: str = ""


class WooCategory(BaseModel):
    model_config = ConfigDict(strict=True)
    id: int = Field(gt=0)
    name: str = ""
    slug: str = ""


class WooAttribute(BaseModel):
    model_config = ConfigDict(strict=True)
    name: str
    option: str


class WooVariation(BaseModel):
    model_config = ConfigDict(strict=True)
    id: int = Field(gt=0)
    status: str
    price: str = Field(default="", pattern=r"^(?:[0-9]+(?:\.[0-9]+)?)?$", max_length=32)
    stock_status: str = Field(pattern="^(instock|outofstock|onbackorder)$")
    attributes: list[WooAttribute] = Field(default_factory=list)


class WooProduct(WooVariation):
    name: str = Field(min_length=1, max_length=500)
    sku: str = ""
    type: str
    catalog_visibility: str
    permalink: str = ""
    images: list[WooImage] = Field(default_factory=list)
    categories: list[WooCategory] = Field(default_factory=list)
    # Parent attributes have options, whereas variation attributes have one option.
    attributes: list[dict] = Field(default_factory=list)


class ProductVariant(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    id: int
    price: str | None
    stock_status: str
    attributes: dict[str, str] = Field(default_factory=dict)


class CatalogProduct(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    id: int
    name: str
    sku: str
    url: str | None
    image: str | None
    currency: str
    price: str | None
    stock_status: str
    type: str
    variants: list[ProductVariant] = Field(default_factory=list)
    variants_may_have_more: bool = False


class ProductPage(BaseModel):
    products: list[CatalogProduct] = Field(default_factory=list)
    page: int
    may_have_more: bool = False
    message: str = ""


def _rows(rows: Any, model: type[BaseModel]) -> list:
    try:
        return TypeAdapter(list[model]).validate_python(rows)
    except ValidationError as exc:
        raise RecoverableFailure(FailureKind.MALFORMED_RESPONSE) from exc


def _public_rows(rows: Any) -> list[dict]:
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise RecoverableFailure(FailureKind.MALFORMED_RESPONSE)
    return [row for row in rows if row.get("status", "publish") == "publish"
            and row.get("catalog_visibility", "visible") in {"visible", "catalog", "search"}]


def _matches(price: str, stock: str, query: ProductSearch) -> bool:
    if query.stock_status != "any" and stock != query.stock_status:
        return False
    if query.min_price is None and query.max_price is None:
        return True
    if not price:
        return False
    amount = Decimal(price)
    return ((query.min_price is None or amount >= Decimal(str(query.min_price)))
            and (query.max_price is None or amount <= Decimal(str(query.max_price))))


def format_product(product: dict[str, Any]) -> str:
    stock_status = product.get("stock_status", "")
    lines = [
        f"Prodotto: {product.get('name', 'n/d')} (SKU {product.get('sku') or 'n/d'})",
        f"Disponibilità: {STOCK_LABELS.get(stock_status, stock_status or 'n/d')}",
    ]
    quantity = product.get("stock_quantity")
    if quantity is not None:
        lines.append(f"Pezzi a magazzino: {quantity}")
    if product.get("price"):
        lines.append(f"Prezzo: {product['price']} {settings.wc_currency}")
    if product.get("permalink"):
        lines.append(f"Scheda: {product['permalink']}")
    return "\n".join(lines)


class CatalogService:
    def __init__(self, client: WooClient | None = None) -> None:
        self._woo = client or shared_woo_client()

    async def search_products(self, **filters: Any) -> ProductPage:
        query = ProductSearch.model_validate(filters)
        result = ProductPage(page=query.page)
        params: dict[str, Any] = {"status": "publish", "page": query.page,
                                  "per_page": query.per_page, "orderby": "id", "order": "asc"}
        if query.query:
            params["search"] = query.query
        if query.stock_status != "any":
            params["stock_status"] = query.stock_status
        for key in ("min_price", "max_price"):
            if getattr(query, key) is not None:
                params[key] = str(getattr(query, key))
        category_id = None
        if query.category is not None:
            categories = _rows(await self._woo.get_json("products/categories", {
                "search": query.category, "per_page": 20, "page": 1,
            }), WooCategory)
            matches = [c for c in categories if query.category.casefold()
                       in {c.name.casefold(), c.slug.casefold()}]
            if len(matches) != 1:
                result.message = ("Categoria non identificata univocamente. Chiedi il nome o "
                                  "lo slug esatto della categoria; non inventare ID.")
                return result
            category_id = matches[0].id
            params["category"] = category_id
        products = _rows(await self._woo.get_json("products", params), WooProduct)
        result.may_have_more = len(products) >= query.per_page
        for row in products[:query.per_page]:
            if row.status != "publish" or row.catalog_visibility not in {"visible", "catalog",
                                                                         "search"}:
                continue
            if category_id is not None and category_id not in {c.id for c in row.categories}:
                continue
            if query.stock_status != "any" and row.stock_status != query.stock_status:
                continue
            product = CatalogProduct(
                id=row.id, name=row.name, sku=row.sku, url=safe_url(row.permalink),
                image=safe_url(row.images[0].src) if row.images else None,
                currency=settings.wc_currency, price=row.price or None,
                stock_status=row.stock_status, type=row.type,
            )
            if row.type == "variable":
                # shortcut: one page per parent, request a specific SKU for further variants.
                variations = _rows(await self._woo.get_json(f"products/{row.id}/variations", {
                    **{k: v for k, v in params.items() if k in {"min_price", "max_price",
                                                               "stock_status", "status"}},
                    "per_page": 10, "page": 1,
                }), WooVariation)
                product.price = None  # A parent's lowest price need not be purchasable/in stock.
                product.variants_may_have_more = len(variations) >= 10
                product.variants = [ProductVariant(
                    id=v.id, price=v.price or None, stock_status=v.stock_status,
                    attributes={a.name: a.option for a in v.attributes},
                ) for v in variations[:10] if v.status == "publish"
                    and _matches(v.price, v.stock_status, query)]
                if not product.variants:
                    continue
            elif not _matches(row.price, row.stock_status, query):
                continue
            result.products.append(product)
        result.message = ("Dati live verificati per questa pagina. Le varianti elencate sono "
                          "un sottoinsieme verificato, non una fascia di prezzo completa."
                          if result.products else "Nessun prodotto verificato in questa pagina.")
        if result.may_have_more:
            result.message += " Possono esserci altre pagine; non è un elenco esaustivo."
        return result

    async def list_products(self) -> str:
        rows = await self._woo.get_json(
            "products", {"status": "publish", "per_page": 11, "orderby": "id", "order": "asc"}
        )
        rows = _public_rows(rows)
        if not rows:
            return "Nessun prodotto pubblicato nel catalogo."
        result = "\n\n".join(format_product(row) for row in rows[:10])
        if len(rows) > 10:
            result += ("\n\nElenco parziale: primi 10 prodotti. "
                       "Chiedi un nome o SKU per cercare altro.")
        return result

    async def check_availability(self, product: str, limit: int = 3) -> str:
        query = (product or "").strip()
        if not query:
            return NOT_FOUND

        rows = await self._woo.get_json(
            "products", {"sku": query, "status": "publish", "per_page": 1}
        )
        rows = _public_rows(rows)
        if not rows:
            rows = await self._woo.get_json(
                "products", {"search": query, "status": "publish", "per_page": limit}
            )
            rows = _public_rows(rows)
        if not rows:
            return NOT_FOUND
        return "\n\n".join(format_product(row) for row in rows)
