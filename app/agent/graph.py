from collections.abc import Callable
from datetime import UTC, datetime
from time import perf_counter
from uuid import uuid4

from langgraph.graph import END, START, StateGraph
from pydantic import ValidationError

from app.agent.cancellation import (
    constrain_online_cancellation,
    needs_partial_cancellation_reconsideration,
)
from app.agent.evidence import missing_related_rule_groups
from app.agent.models import AgentState, NextAction
from app.consultation_contract import (
    ConsultationRequest,
    ConsultationResponse,
    ConsultationStatus,
    MissingField,
    OrderNotRequested,
    OrderToolEvent,
    OrderToolInput,
    Recommendation,
    SearchToolEvent,
    SearchToolInput,
    Topic,
)
from app.rag.retrieval import PolicySearchResult
from app.schemas import OrderError, OrderLookupResult

MAX_TOOL_CALLS = 3
MAX_SEARCH_CALLS = 2
MAX_MODEL_CALLS = 4


def terminal_response(
    state: AgentState,
    status: ConsultationStatus,
    message: str,
    missing: list[MissingField] | None = None,
) -> ConsultationResponse:
    return ConsultationResponse(
        request_id=state["request_id"],
        reference_time=state["reference_time"],
        status=status,
        order_result=state["order_result"],
        sources=state["sources"],
        applied_policies=[],
        recommendation=Recommendation(text=message, evidence_ids=[]),
        draft_reply=None,
        missing_fields=missing or [],
        tool_events=state["tool_events"],
    )


def missing_response(state: AgentState, field: str, question: str) -> ConsultationResponse:
    return terminal_response(
        state,
        "needs_information",
        question,
        [MissingField(field=field, item_id=state["request"].target_item_id, question=question)],
    )


def order_guard(state: AgentState) -> ConsultationResponse | None:
    request = state["request"]
    result = state["order_result"]
    if result.kind != "found":
        return None
    items = result.order.items
    if request.target_item_id:
        items = [item for item in items if item.item_id == request.target_item_id]
        if not items:
            return missing_response(
                state, "item_id", "주문에 해당 품목이 없습니다. 품목번호를 확인해 주세요."
            )
    decision = state["decision"]
    if decision and decision.topic == "returns" and len(items) > 1:
        return missing_response(
            state,
            "item_id",
            "품목별 배송 상태와 수령일이 다를 수 있습니다. 반품할 품목번호를 알려주세요.",
        )
    if any(item.status == "unknown" for item in items):
        return missing_response(
            state, "order_status", "확인되지 않은 품목의 주문 상태를 먼저 확인해 주세요."
        )
    return None


class ConsultationEngine:
    def __init__(
        self,
        decide: Callable[[AgentState], NextAction],
        lookup: Callable[[str], OrderLookupResult],
        search: Callable[[str, Topic | None], PolicySearchResult],
    ) -> None:
        self.decider = decide
        self.lookup = lookup
        self.search = search
        self.last_model_error: dict | None = None
        self.last_response_error: dict | None = None
        self.response_normalizations: list[str] = []
        builder = StateGraph(AgentState)
        builder.add_node("decide", self.decide)
        builder.add_node("lookup", self.lookup_node)
        builder.add_node("search", self.search_node)
        builder.add_node("finish", lambda state: {})
        builder.add_edge(START, "decide")
        builder.add_conditional_edges("decide", lambda state: state["route"])
        for node in ("lookup", "search"):
            builder.add_conditional_edges(
                node, lambda state: "finish" if state["response"] is not None else "decide"
            )
        builder.add_edge("finish", END)
        self.graph = builder.compile()

    def decide(self, state: AgentState) -> dict:
        calls = state["llm_calls"] + 1
        if calls > MAX_MODEL_CALLS:
            response = terminal_response(
                state, "limit_reached", "모델 판단 상한으로 상담을 종료했습니다."
            )
            return {"response": response, "route": "finish"}
        try:
            decision = NextAction.model_validate(self.decider(state))
        except Exception as error:
            self.last_model_error = {
                "type": type(error).__name__,
                "status_code": getattr(error, "status_code", None),
                "code": getattr(error, "code", None),
            }
            response = terminal_response(
                state,
                "system_error",
                "AI 판단을 완료하지 못했습니다. API 설정·연결 또는 응답을 확인해 주세요.",
            )
            return {"llm_calls": calls, "response": response, "route": "finish"}
        current = {
            **state,
            "llm_calls": calls,
            "decision": decision,
            "requires_order": state["requires_order"] or decision.requires_order,
        }
        response = None
        feedback = None
        route = "finish"
        if current["requires_order"] and not state["request"].order_id:
            response = missing_response(
                current, "order_id", "주문별 확인을 위해 주문번호를 알려주세요."
            )
        elif current["requires_order"] and state["order_result"].kind == "not_requested":
            route = "lookup"
        elif guard := order_guard(current):
            response = guard
        elif decision.action == "finish":
            searched = any(e.tool_name == "search_policy" for e in state["tool_events"])
            if (
                decision.status == "needs_information"
                and not decision.missing_fields
                and calls < MAX_MODEL_CALLS
            ):
                route = "decide"
                feedback = (
                    "needs_information에는 missing_fields의 구체적인 확인 질문이 필요합니다. "
                    "정말 정보가 부족하면 질문을 작성하세요. 조회와 정책으로 답할 수 있다면 "
                    "answered와 고객 초안을 작성하세요. 신청/취소를 대신 실행하지 않는 것은 "
                    "정보 부족과 다릅니다. 근거가 없다면 insufficient_evidence로 판단하세요."
                )
            elif calls < MAX_MODEL_CALLS and needs_partial_cancellation_reconsideration(current):
                route = "decide"
                feedback = (
                    "조회한 카드·다품목·대상 품목과 적용한 검수 정책으로 부분 취소 제한을 "
                    "설명할 수 있습니다. missing_fields가 실제 판단 정보 부족인지 다시 확인하세요. "
                    "전체 주문 취소나 재주문에 대한 고객 동의는 실행 단계의 확인이며, "
                    "이 서비스는 실제 처리를 실행하지 않으므로 정책 안내의 필수 정보가 아닙니다. "
                    "동의 여부만 미확인이라면 제한과 대안을 answered/고객 초안으로 안내하세요. "
                    "그 밖에 실제로 필요한 사실이나 근거가 부족하면 "
                    "구체적인 확인 질문을 유지하세요."
                )
            elif (
                decision.status == "answered"
                and not state["sources"]
                and not searched
                and calls < MAX_MODEL_CALLS
            ):
                route = "decide"
                feedback = (
                    "answered에는 실제 정책 검색 근거가 필요합니다. "
                    "조회 사실만으로 종료하지 말고 관련 정책을 검색한 뒤 판단하세요."
                )
            else:
                response = self.finish_response(current)
                if response.status == "answered":
                    try:
                        missing_groups = missing_related_rule_groups(
                            response.applied_policies, response.sources
                        )
                    except (OSError, ValueError, KeyError):
                        response = terminal_response(
                            current, "system_error", "검수된 정책 연결 정보를 확인하지 못했습니다."
                        )
                    else:
                        if missing_groups:
                            if calls < MAX_MODEL_CALLS:
                                response = None
                                route = "decide"
                                feedback = (
                                    "적용한 정책의 관련 조건·예외 근거가 누락됐습니다: "
                                    + ", ".join(missing_groups)
                                    + ". related_policy_requirements를 확인하세요. "
                                    "이미 검색된 근거는 재검색 없이 적용 정책과 고객 초안에 "
                                    "조건·예외를 설명하고 인용하세요. "
                                    "없는 근거만 한도 내 검색하세요."
                                )
                            else:
                                response = terminal_response(
                                    current,
                                    "insufficient_evidence",
                                    "정책의 관련 조건·예외를 함께 적용하지 못했습니다. "
                                    "검색된 출처를 상담원이 확인해 주세요.",
                                )
        else:
            route = "lookup" if decision.action == "lookup_order" else "search"
        if response is None:
            events = state["tool_events"]
            exhausted = len(events) >= MAX_TOOL_CALLS
            if route == "lookup":
                exhausted |= any(event.tool_name == "lookup_order" for event in events)
                if not state["request"].order_id:
                    response = missing_response(current, "order_id", "주문번호를 확인해 주세요.")
            elif route == "search":
                exhausted |= sum(e.tool_name == "search_policy" for e in events) >= MAX_SEARCH_CALLS
            if response is None and exhausted:
                response = terminal_response(
                    current, "limit_reached", "실행 상한에 도달했습니다. 확인된 사실만 표시합니다."
                )
        return {
            "llm_calls": calls,
            "requires_order": current["requires_order"],
            "decision": decision,
            "feedback": feedback,
            "route": "finish" if response else route,
            "response": response,
        }

    def lookup_node(self, state: AgentState) -> dict:
        started = perf_counter()
        try:
            result = self.lookup(state["request"].order_id)
        except Exception:
            result = OrderError(message="주문 조회 중 오류가 발생했습니다.")
        event = OrderToolEvent(
            sequence=len(state["tool_events"]) + 1,
            duration_ms=int((perf_counter() - started) * 1000),
            status="error" if result.kind == "error" else "success",
            result_summary={
                "found": "가상 주문 조회 완료",
                "not_found": "주문 없음",
                "error": "주문 조회 오류",
            }[result.kind],
            tool_name="lookup_order",
            input=OrderToolInput(order_id=state["request"].order_id),
        )
        current = {**state, "order_result": result, "tool_events": [*state["tool_events"], event]}
        response = None
        if result.kind == "error":
            response = terminal_response(
                current, "system_error", "주문 DB 조회 오류입니다. 다시 확인해 주세요."
            )
        elif result.kind == "not_found":
            response = terminal_response(
                current, "order_not_found", "해당 주문이 없습니다. 주문번호를 재확인해 주세요."
            )
        else:
            response = order_guard(current)
        return {"order_result": result, "tool_events": current["tool_events"], "response": response}

    def search_node(self, state: AgentState) -> dict:
        decision = state["decision"]
        try:
            search_input = SearchToolInput(query=decision.query, topic=decision.topic)
            if not search_input.query.strip():
                raise ValueError("Empty search query")
        except ValueError:
            return {
                "response": terminal_response(
                    state, "system_error", "정책 검색 입력이 올바르지 않습니다."
                )
            }
        started = perf_counter()
        try:
            result = self.search(search_input.query, search_input.topic)
        except Exception:
            result = PolicySearchResult(
                kind="error",
                query=search_input.query,
                embedding_provider="openai",
                message="검색 오류",
            )
        failed = result.kind != "candidates"
        sources = {source.evidence_id: source for source in state["sources"]}
        hits = [] if failed else [hit.source for hit in result.hits]
        sources.update({source.evidence_id: source for source in hits})
        event = SearchToolEvent(
            sequence=len(state["tool_events"]) + 1,
            duration_ms=int((perf_counter() - started) * 1000),
            status="error" if failed else "success",
            result_summary=f"정책 근거 후보 {len(hits)}개"
            if not failed
            else "정책 검색 준비 또는 실행 오류",
            tool_name="search_policy",
            input=search_input,
            evidence_ids=[source.evidence_id for source in hits],
        )
        current = {
            **state,
            "sources": list(sources.values()),
            "tool_events": [*state["tool_events"], event],
        }
        response = None
        if failed:
            response = terminal_response(
                current,
                "system_error",
                "정책 검색을 완료하지 못했습니다. 인덱스·API 허용·연결을 확인해 주세요.",
            )
        return {
            "sources": current["sources"],
            "tool_events": current["tool_events"],
            "response": response,
        }

    def finish_response(self, state: AgentState) -> ConsultationResponse:
        decision = state["decision"]
        order = state["order_result"]
        if decision.status == "answered" and decision.topic == "returns" and order.kind == "found":
            items = [
                item
                for item in order.order.items
                if state["request"].target_item_id is None
                or item.item_id == state["request"].target_item_id
            ]
            if any(item.delivered_at is None for item in items):
                return missing_response(
                    state,
                    "delivered_at",
                    "수령 여부와 실제 수령일이 확인되지 않았습니다. 확인해 주세요.",
                )
        if decision.status == "answered" and not state["sources"]:
            return terminal_response(
                state, "insufficient_evidence", "수집한 정책에서 답변 근거를 확인하지 못했습니다."
            )
        try:
            if decision.status == "answered" and not (decision.draft_reply or "").strip():
                raise ValueError("Answered response needs a customer draft")
            if decision.status == "answered" and not decision.recommendation.evidence_ids:
                raise ValueError("Answer recommendation requires evidence")
            recommendation = decision.recommendation
            if decision.status == "insufficient_evidence" and recommendation is None:
                recommendation = Recommendation(
                    text=(
                        "수집한 정책에서 질문을 직접 뒷받침하는 근거를 확인하지 못했습니다. "
                        "추가 정책 또는 담당자 확인이 필요합니다."
                    ),
                    evidence_ids=[],
                )
                self.response_normalizations.append("insufficient_evidence.recommendation")
            status = decision.status
            if status == "insufficient_evidence" and decision.missing_fields:
                # An explicit confirmation question takes precedence over a generic
                # no-evidence label. Preserve facts, questions and citation validation.
                status = "needs_information"
                self.response_normalizations.append(
                    "status.insufficient_evidence_to_needs_information"
                )
            response = ConsultationResponse(
                request_id=state["request_id"],
                reference_time=state["reference_time"],
                status=status,
                order_result=state["order_result"],
                sources=state["sources"],
                applied_policies=decision.applied_policies,
                recommendation=recommendation,
                draft_reply=decision.draft_reply if decision.status == "answered" else None,
                missing_fields=decision.missing_fields,
                tool_events=state["tool_events"],
            )
            constrained = constrain_online_cancellation(response, state["request"])
            if constrained is not response:
                self.response_normalizations.append(
                    "answer.reviewed_online_cancellation_denial"
                    if constrained.status == "answered"
                    else "answer.unmatched_cancellation_rule_withheld"
                )
            return constrained
        except (ValueError, AttributeError) as error:
            self.last_response_error = {
                "type": type(error).__name__,
                "fields": [
                    {"location": list(e["loc"]), "type": e["type"], "message": e["msg"]}
                    for e in error.errors(include_input=False, include_url=False)
                ]
                if isinstance(error, ValidationError)
                else [],
            }
            return terminal_response(
                state,
                "system_error",
                "AI 응답의 상태·인용 검증에 실패했습니다. 수동 확인해 주세요.",
            )

    def run(
        self, request: ConsultationRequest, *, reference_time: datetime | None = None
    ) -> ConsultationResponse:
        reference = reference_time or datetime.now(UTC)
        if reference.tzinfo is None:
            raise ValueError("Reference time must be timezone-aware")
        self.last_model_error = None
        self.last_response_error = None
        self.response_normalizations = []
        initial: AgentState = {
            "request": request,
            "request_id": str(uuid4()),
            "reference_time": reference,
            "order_result": OrderNotRequested(),
            "sources": [],
            "tool_events": [],
            "llm_calls": 0,
            "requires_order": request.order_id is not None,
            "feedback": None,
            "decision": None,
            "response": None,
            "route": "finish",
        }
        result = self.graph.invoke(initial, {"recursion_limit": 16})
        return result["response"]
