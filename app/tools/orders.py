from langchain.tools import tool
from pydantic import BaseModel, TypeAdapter

from app.config import get_settings
from app.repositories.orders import fetch_order
from app.schemas import OrderId, OrderLookupResult


class LookupOrderInput(BaseModel):
    order_id: OrderId


def lookup_order_result(order_id: str) -> OrderLookupResult:
    validated = TypeAdapter(OrderId).validate_python(order_id)
    return fetch_order(validated, get_settings().db_path)


@tool(args_schema=LookupOrderInput)
def lookup_order(order_id: str) -> dict:
    """Look up a synthetic order by the exact order ID supplied by the user; read-only."""
    return lookup_order_result(order_id).model_dump(mode="json")
