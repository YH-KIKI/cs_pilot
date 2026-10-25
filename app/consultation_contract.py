"""Version 1 consultation DTOs. These schemas do not implement an agent."""

from datetime import date
from typing import Annotated, Literal, Self

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    StringConstraints,
    model_validator,
)

from app.schemas import OrderError, OrderFound, OrderId, OrderNotFound

Topic = Literal["shipping", "cancellation", "returns"]
ConsultationStatus = Literal[
    "answered",
    "needs_information",
    "order_not_found",
    "insufficient_evidence",
    "limit_reached",
    "system_error",
]
MissingFieldName = Literal[
    "order_id",
    "item_id",
    "order_status",
    "delivered_at",
    "condition",
    "components_complete",
    "security_lock_disabled",
    "payment_method",
    "card_brand",
    "purchase_country",
    "current_country",
    "receipt_available",
    "other",
]


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ConsultationRequest(ContractModel):
    question: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)
    ]
    order_id: OrderId | None = None
    target_item_id: Annotated[str, StringConstraints(pattern=r"^[0-9]{2,6}$")] | None = None

    @model_validator(mode="after")
    def item_needs_order(self) -> Self:
        if self.target_item_id is not None and self.order_id is None:
            raise ValueError("target_item_id requires order_id")
        return self


class OrderNotRequested(ContractModel):
    kind: Literal["not_requested"] = "not_requested"


ConsultationOrderResult = Annotated[
    OrderNotRequested | OrderFound | OrderNotFound | OrderError, Field(discriminator="kind")
]


class PolicySource(ContractModel):
    evidence_id: str = Field(min_length=1)
    document_id: str = Field(min_length=1)
    rule_group_id: str = Field(min_length=1)
    chunk_id: str | None
    title: str = Field(min_length=1)
    heading: str = Field(min_length=1)
    source_url: HttpUrl
    collected_at: AwareDatetime
    effective_date: date | None
    excerpt: str = Field(min_length=1)


class AppliedPolicy(ContractModel):
    text: str = Field(min_length=1)
    evidence_ids: list[str] = Field(min_length=1)


class Recommendation(ContractModel):
    text: str = Field(min_length=1)
    evidence_ids: list[str]


class MissingField(ContractModel):
    field: MissingFieldName
    item_id: str | None
    question: str = Field(min_length=1)


class OrderToolInput(ContractModel):
    order_id: OrderId


class SearchToolInput(ContractModel):
    query: str = Field(min_length=1, max_length=1000)
    topic: Topic | None


class ToolEventBase(ContractModel):
    sequence: int = Field(ge=1, le=3)
    duration_ms: int = Field(ge=0)
    status: Literal["success", "error"]
    result_summary: str = Field(min_length=1)


class OrderToolEvent(ToolEventBase):
    tool_name: Literal["lookup_order"]
    input: OrderToolInput


class SearchToolEvent(ToolEventBase):
    tool_name: Literal["search_policy"]
    input: SearchToolInput
    evidence_ids: list[str]


ToolEvent = Annotated[OrderToolEvent | SearchToolEvent, Field(discriminator="tool_name")]


class ConsultationResponse(ContractModel):
    contract_version: Literal["1.0"] = "1.0"
    request_id: str = Field(min_length=1)
    reference_time: AwareDatetime
    status: ConsultationStatus
    order_result: ConsultationOrderResult
    sources: list[PolicySource]
    applied_policies: list[AppliedPolicy]
    recommendation: Recommendation
    draft_reply: str | None
    missing_fields: list[MissingField]
    tool_events: list[ToolEvent] = Field(max_length=3)

    @model_validator(mode="after")
    def enforce_response_contract(self) -> Self:
        source_ids = [source.evidence_id for source in self.sources]
        if len(set(source_ids)) != len(source_ids):
            raise ValueError("Duplicate evidence IDs")
        referenced = set(self.recommendation.evidence_ids)
        for policy in self.applied_policies:
            referenced.update(policy.evidence_ids)
        for event in self.tool_events:
            if isinstance(event, SearchToolEvent):
                referenced.update(event.evidence_ids)
        if not referenced.issubset(set(source_ids)):
            raise ValueError("Unknown evidence ID")
        if self.status == "answered" and (not self.sources or not self.applied_policies):
            raise ValueError("Answered policy questions require policy evidence")
        if self.status == "needs_information" and not self.missing_fields:
            raise ValueError("Missing information must be specified")
        if self.status == "order_not_found" and self.order_result.kind != "not_found":
            raise ValueError("order_not_found requires a not_found lookup result")
        if sum(e.tool_name == "lookup_order" for e in self.tool_events) > 1:
            raise ValueError("Order lookup limit exceeded")
        if sum(e.tool_name == "search_policy" for e in self.tool_events) > 2:
            raise ValueError("Policy search limit exceeded")
        if [e.sequence for e in self.tool_events] != list(range(1, len(self.tool_events) + 1)):
            raise ValueError("Tool events must be ordered consecutively")
        return self


class ApiError(ContractModel):
    code: Literal["not_implemented"]
    message: str
