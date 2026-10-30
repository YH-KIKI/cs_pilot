from datetime import datetime
from typing import Literal, TypedDict

from app.consultation_contract import (
    AppliedPolicy,
    ConsultationOrderResult,
    ConsultationRequest,
    ConsultationResponse,
    ContractModel,
    MissingField,
    PolicySource,
    Recommendation,
    ToolEvent,
    Topic,
)


class NextAction(ContractModel):
    """LLM proposal only; tool permissions and result facts belong to the server."""

    action: Literal["lookup_order", "search_policy", "finish"]
    requires_order: bool
    topic: Topic | None
    query: str | None
    status: Literal["answered", "needs_information", "insufficient_evidence"] | None
    applied_policies: list[AppliedPolicy]
    recommendation: Recommendation | None
    draft_reply: str | None
    missing_fields: list[MissingField]


class AgentState(TypedDict):
    request: ConsultationRequest
    request_id: str
    reference_time: datetime
    order_result: ConsultationOrderResult
    sources: list[PolicySource]
    tool_events: list[ToolEvent]
    llm_calls: int
    requires_order: bool
    feedback: str | None
    decision: NextAction | None
    response: ConsultationResponse | None
    route: Literal["decide", "lookup", "search", "finish"]
