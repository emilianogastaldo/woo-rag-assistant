"""Validate untrusted Woo response shapes before formatting or authorization checks."""
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

from app.resilience import FailureKind, RecoverableFailure


class Customer(BaseModel):
    model_config = ConfigDict(strict=True)
    id: int = Field(gt=0)


class Item(BaseModel):
    model_config = ConfigDict(strict=True)
    name: str = ""
    quantity: int = 1


class Order(Customer):
    customer_id: int
    status: str = ""
    line_items: list[Item] = Field(default_factory=list)


class Product(BaseModel):
    model_config = ConfigDict(strict=True)
    name: str = ""
    stock_status: str = ""


SCHEMAS = {"customers": TypeAdapter(list[Customer]), "orders": TypeAdapter(list[Order]),
           "products": TypeAdapter(list[Product])}


def validate_rows(path, rows):
    schema = SCHEMAS.get(path)
    if schema is not None:
        try:
            schema.validate_python(rows)
        except ValidationError as exc:
            raise RecoverableFailure(FailureKind.MALFORMED_RESPONSE) from exc
    return rows
