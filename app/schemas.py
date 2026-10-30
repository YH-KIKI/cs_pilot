from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

OrderId = Annotated[str, StringConstraints(pattern=r"^A[0-9]{2,6}$")]
OrderStatus = Literal[
    "received", "processing", "preparing", "shipped", "delivered", "cancelled", "unknown"
]


class OrderItem(BaseModel):
    item_id: str
    product_name: str
    product_type: str
    quantity: int = Field(gt=0)
    status: OrderStatus
    shipped_at: datetime | None
    estimated_delivery_date: date | None
    delivered_at: datetime | None
    tracking_number: str | None
    last_tracking_event: str | None
    snapshot_at: datetime
    condition: Literal["original", "damaged", "other", "unknown"]
    components_complete: bool | None
    security_lock_disabled: bool | None
    return_requested_at: datetime | None


class Order(BaseModel):
    order_id: str
    is_synthetic: Literal[True]
    store: str
    purchase_country: str
    ordered_at: datetime
    payment_method: Literal["card", "bank_transfer", "other", "unknown"]
    card_brand: str | None
    items: list[OrderItem] = Field(min_length=1)


class OrderFound(BaseModel):
    kind: Literal["found"] = "found"
    order: Order
    snapshot_at: datetime


class OrderNotFound(BaseModel):
    kind: Literal["not_found"] = "not_found"
    order_id: str


class OrderError(BaseModel):
    kind: Literal["error"] = "error"
    message: str


OrderLookupResult = Annotated[OrderFound | OrderNotFound | OrderError, Field(discriminator="kind")]


class HealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["ok"] = "ok"
    database: Literal["ready"] = "ready"
    ai_enabled: bool = False
    message: str = "상담 API가 연결됐습니다. 실제 AI 실행에는 서버의 명시적 API 허용이 필요합니다."
