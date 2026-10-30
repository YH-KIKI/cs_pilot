from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from app.agent.graph import ConsultationEngine
from app.agent.model import model_context
from app.agent.models import NextAction
from app.agent.service import get_consultation_engine
from app.config import ROOT
from app.consultation_contract import (
    AppliedPolicy,
    ConsultationRequest,
    ConsultationResponse,
    MissingField,
    PolicySource,
    Recommendation,
)
from app.main import app
from app.rag.chunks import load_chunks
from app.rag.retrieval import PolicyHit, PolicySearchResult
from app.repositories.orders import fetch_order
from app.schemas import OrderError

REFERENCE = datetime.fromisoformat("2026-10-22T12:00:00+09:00")


def action(name, *, requires_order=False, topic="cancellation", query=None, **kwargs):
    return NextAction(
        action=name,
        requires_order=requires_order,
        topic=topic,
        query=query,
        status=kwargs.get("status"),
        applied_policies=kwargs.get("applied_policies", []),
        recommendation=kwargs.get("recommendation"),
        draft_reply=kwargs.get("draft_reply"),
        missing_fields=kwargs.get("missing_fields", []),
    )


def policy_result(groups):
    chunks, _ = load_chunks()
    sources = [
        PolicySource(
            evidence_id="evidence-" + c.chunk_id,
            document_id=c.document_id,
            rule_group_id=c.rule_group_id,
            chunk_id=c.chunk_id,
            title=c.title,
            heading=c.heading,
            source_url=c.source_url,
            collected_at=c.collected_at,
            effective_date=c.effective_date,
            excerpt=c.text,
        )
        for c in chunks
        if c.rule_group_id in groups
    ]
    return PolicySearchResult(
        kind="candidates",
        query="test query",
        embedding_provider="fixture",
        hits=[PolicyHit(source=s, distance=0.0, reason="retrieved") for s in sources],
        message="Fixed tool results, not semantic evaluation",
    )


def answer(groups, *, requires_order=False, topic="cancellation", evidence_ids=None):
    ids = evidence_ids or [h.source.evidence_id for h in policy_result(groups).hits]
    return action(
        "finish",
        requires_order=requires_order,
        topic=topic,
        status="answered",
        applied_policies=[AppliedPolicy(text="실제 근거 범위의 정책 안내", evidence_ids=ids)],
        recommendation=Recommendation(
            text="상담원이 근거를 확인하고 신청 방향을 안내합니다.", evidence_ids=ids
        ),
        draft_reply="확인한 정책에 따라 신청 방향을 안내드립니다. 처리를 실행하지 않았습니다.",
    )


def make_engine(decisions, searches=None, *, lookup=None):
    states = []
    iterator = iter(decisions)
    search_iterator = iter(searches or [])

    def decide(state):
        states.append(state)
        return next(iterator)

    def search(query, topic):
        value = next(search_iterator)
        if isinstance(value, Exception):
            raise value
        return value

    engine = ConsultationEngine(
        decide,
        lookup or (lambda order_id: fetch_order(order_id, ROOT / "data/runtime/orders.sqlite3")),
        search,
    )
    return engine, states


def run(engine, **kwargs):
    return engine.run(ConsultationRequest(question="문의", **kwargs), reference_time=REFERENCE)


def test_general_policy_only_uses_search():
    engine, _ = make_engine(
        [
            action("search_policy", topic="shipping", query="표준 배송비"),
            answer(["shipping-options"], topic="shipping"),
        ],
        [policy_result(["shipping-options"])],
    )
    result = run(engine)
    assert result.status == "answered"
    assert result.order_result.kind == "not_requested"
    assert [e.tool_name for e in result.tool_events] == ["search_policy"]
    assert result.sources[0].effective_date is None
    ConsultationResponse.model_validate(result.model_dump())


def test_specific_order_is_looked_up_before_answer_and_cannot_be_replaced():
    engine, states = make_engine(
        [
            action("lookup_order", requires_order=True),
            action("search_policy", requires_order=True, query="출고됨 취소"),
            answer(["order-cancellation"], requires_order=True),
        ],
        [policy_result(["order-cancellation"])],
    )
    result = run(engine, order_id="A04")
    assert result.status == "answered"
    assert result.order_result.order.items[0].status == "shipped"
    assert [e.tool_name for e in result.tool_events] == ["lookup_order", "search_policy"]
    assert states[-1]["requires_order"] is True


@pytest.mark.parametrize(
    "order_id,status,field",
    [
        (None, "needs_information", "order_id"),
        ("A999", "order_not_found", None),
        ("A12", "needs_information", "order_status"),
    ],
)
def test_missing_order_unknown_state_and_not_found_exit(order_id, status, field):
    engine, _ = make_engine([action("lookup_order", requires_order=True)])
    result = run(engine, order_id=order_id)
    assert result.status == status
    if field:
        assert result.missing_fields[0].field == field
    assert len(result.tool_events) == (0 if order_id is None else 1)
    assert result.draft_reply is None


@pytest.mark.parametrize("target", [None, "99"])
def test_ambiguous_or_nonexistent_item_is_not_selected(target):
    engine, _ = make_engine([action("lookup_order", requires_order=True, topic="returns")])
    result = run(engine, order_id="A06", target_item_id=target)
    assert result.status == "needs_information"
    assert result.missing_fields[0].field == "item_id"
    assert len(result.order_result.order.items) == 2


def test_one_retry_retains_real_sources_and_stops_when_sufficient():
    engine, _ = make_engine(
        [
            action("lookup_order", requires_order=True),
            action("search_policy", requires_order=True, query="주문 상태"),
            action("search_policy", requires_order=True, query="Visa 다품목 부분 취소"),
            answer(["order-cancellation"], requires_order=True),
        ],
        [policy_result(["order-status"]), policy_result(["order-cancellation"])],
    )
    result = run(engine, order_id="A03", target_item_id="01")
    assert result.status == "answered"
    assert len(result.tool_events) == 3
    assert len(result.sources) == 2
    assert [e.sequence for e in result.tool_events] == [1, 2, 3]


def test_third_search_is_blocked_before_tool_execution():
    engine, states = make_engine(
        [
            action("lookup_order", requires_order=True),
            *[action("search_policy", requires_order=True, query="배송 보상") for _ in range(3)],
        ],
        [policy_result([]), policy_result([])],
    )
    result = run(engine, order_id="A04")
    assert result.status == "limit_reached"
    assert len(result.tool_events) == 3
    assert len(states) == 4
    assert result.draft_reply is None


def test_repeated_order_lookup_is_blocked():
    engine, _ = make_engine([action("lookup_order", requires_order=True)] * 2)
    result = run(engine, order_id="A01")
    assert result.status == "limit_reached"
    assert len(result.tool_events) == 1


def test_no_evidence_cannot_be_answered():
    engine, _ = make_engine(
        [
            action("search_policy", query="정액 보상"),
            answer(["order-cancellation"]),
        ],
        [policy_result([])],
    )
    result = run(engine)
    assert result.status == "insufficient_evidence"
    assert result.sources == []
    assert result.draft_reply is None


def test_unknown_citation_does_not_escape_to_customer():
    engine, _ = make_engine(
        [
            action("search_policy", query="취소"),
            answer(["order-cancellation"], evidence_ids=["invented-id"]),
        ],
        [policy_result(["order-cancellation"])],
    )
    result = run(engine)
    assert result.status == "system_error"
    assert result.draft_reply is None
    assert not result.applied_policies


@pytest.mark.parametrize("kind", ["error", "not_ready"])
def test_policy_errors_are_not_hidden_as_no_evidence(kind):
    failure = PolicySearchResult(
        kind=kind, query="취소", embedding_provider="fixture", message="private"
    )
    engine, _ = make_engine([action("search_policy", query="취소")], [failure])
    result = run(engine)
    assert result.status == "system_error"
    assert result.tool_events[0].status == "error"
    assert "private" not in result.model_dump_json()


def test_db_and_model_errors_are_safe():
    engine, _ = make_engine(
        [action("lookup_order", requires_order=True)],
        lookup=lambda _: OrderError(message="private"),
    )
    assert run(engine, order_id="A01").status == "system_error"
    engine, _ = make_engine([])
    result = run(engine)
    assert result.status == "system_error"
    assert result.tool_events == []


def test_fixed_clock_date_calculation_is_injected_not_taken_from_user():
    engine, states = make_engine(
        [
            action("lookup_order", requires_order=True, topic="returns"),
            action(
                "finish",
                requires_order=True,
                topic="returns",
                status="insufficient_evidence",
                recommendation=Recommendation(text="근거 부족", evidence_ids=[]),
            ),
        ]
    )
    result = run(engine, order_id="A08", target_item_id="01")
    assert result.reference_time == REFERENCE
    assert model_context(states[-1])["date_facts"][0]["elapsed_days_since_delivery"] == 14


def test_api_uses_real_graph_and_validates_requests():
    engine, _ = make_engine([action("lookup_order", requires_order=True)])
    app.dependency_overrides[get_consultation_engine] = lambda: engine
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/consultations", json={"question": "주문 취소", "order_id": "A999"}
            )
            assert response.status_code == 200
            assert ConsultationResponse.model_validate(response.json()).status == "order_not_found"
            assert client.post("/api/consultations", json={"question": " "}).status_code == 422
    finally:
        app.dependency_overrides.clear()


def test_answer_without_customer_draft_is_rejected():
    proposal = answer(["order-cancellation"]).model_copy(update={"draft_reply": None})
    engine, _ = make_engine(
        [
            action("search_policy", query="취소"),
            proposal,
        ],
        [policy_result(["order-cancellation"])],
    )
    result = run(engine)
    assert result.status == "system_error"
    assert result.draft_reply is None


def test_graph_state_does_not_leak_between_requests():
    engine, states = make_engine([action("lookup_order", requires_order=True)] * 2)
    first = run(engine, order_id="A999")
    second = run(engine, order_id="A999")
    assert first.request_id != second.request_id
    assert len(first.tool_events) == len(second.tool_events) == 1
    assert states[0]["llm_calls"] == states[1]["llm_calls"] == 0


def test_missing_delivery_date_cannot_be_approved_by_model():
    engine, _ = make_engine(
        [
            action("lookup_order", requires_order=True, topic="returns"),
            action("search_policy", requires_order=True, topic="returns", query="반품 조건"),
            answer(["returns-standard"], requires_order=True, topic="returns"),
        ],
        [policy_result(["returns-standard"])],
    )
    result = run(engine, order_id="A05")
    assert result.status == "needs_information"
    assert result.missing_fields[0].field == "delivered_at"
    assert result.draft_reply is None


def test_premature_order_answer_is_returned_for_policy_search_within_budget():
    engine, states = make_engine(
        [
            action("lookup_order", requires_order=True, topic="shipping"),
            answer(["order-tracking"], requires_order=True, topic="shipping"),
            action(
                "search_policy", requires_order=True, topic="shipping", query="배송 예상일 추적"
            ),
            answer(["order-tracking"], requires_order=True, topic="shipping"),
        ],
        [policy_result(["order-tracking"])],
    )
    result = run(engine, order_id="A04")
    assert result.status == "answered"
    assert len(states) == 4
    assert states[2]["feedback"] is not None
    assert [e.tool_name for e in result.tool_events] == ["lookup_order", "search_policy"]


def test_repeated_premature_answer_stops_at_model_limit_without_inventing_search():
    engine, states = make_engine([answer(["shipping-options"], topic="shipping")] * 4)
    result = run(engine)
    assert result.status == "insufficient_evidence"
    assert result.tool_events == []
    assert len(states) == 4


def test_selected_order_is_looked_up_even_if_model_treats_question_as_general():
    engine, states = make_engine(
        [
            action("search_policy", requires_order=False, query="카드별 부분 취소"),
            action("search_policy", requires_order=False, query="카드별 부분 취소"),
            answer(["order-cancellation"], requires_order=False),
        ],
        [policy_result(["order-cancellation"])],
    )
    result = run(engine, order_id="A03", target_item_id="01")
    assert result.status == "answered"
    assert result.order_result.order.card_brand == "Visa"
    assert [e.tool_name for e in result.tool_events] == ["lookup_order", "search_policy"]
    assert all(state["requires_order"] for state in states)


def test_insufficient_evidence_null_recommendation_gets_safe_procedural_fallback():
    engine, _ = make_engine(
        [
            action("search_policy", query="정액 지연 보상"),
            action(
                "finish", status="insufficient_evidence", draft_reply="금액을 단정할 수 없습니다."
            ),
        ],
        [policy_result(["shipping-eta"])],
    )
    result = run(engine)
    assert result.status == "insufficient_evidence"
    assert result.recommendation.evidence_ids == []
    assert "확인" in result.recommendation.text
    assert result.draft_reply is None
    assert engine.response_normalizations == ["insufficient_evidence.recommendation"]


def test_insufficient_evidence_fallback_does_not_accept_unknown_citations():
    invalid = action(
        "finish",
        status="insufficient_evidence",
        applied_policies=[AppliedPolicy(text="잘못된 인용", evidence_ids=["invented"])],
    )
    engine, _ = make_engine([action("search_policy", query="보상"), invalid], [policy_result([])])
    result = run(engine)
    assert result.status == "system_error"
    assert result.draft_reply is None
    assert engine.last_response_error["type"] == "ValidationError"
    assert "input" not in engine.last_response_error["fields"][0]


def test_o08_recorded_proposal_returns_information_status_with_existing_questions():
    import json

    report = json.loads((ROOT / "docs/agent-evaluation-final-2026-10-30.json").read_text("utf-8"))
    recorded = next(row for row in report["cases"] if row["case_id"] == "O08")
    source_groups = {s["evidence_id"]: s["rule_group_id"] for s in recorded["response"]["sources"]}
    searches = [
        policy_result([source_groups[key] for key in event["evidence_ids"]])
        for event in recorded["response"]["tool_events"]
        if event["tool_name"] == "search_policy"
    ]
    engine, _ = make_engine(
        [NextAction.model_validate(d["proposal"]) for d in recorded["decisions"]], searches
    )
    result = run(engine, order_id="A08", target_item_id="01")
    assert result.status == "needs_information"
    assert result.order_result.order.items[0].delivered_at is not None
    assert [field.model_dump() for field in result.missing_fields] == recorded["response"][
        "missing_fields"
    ]
    assert result.recommendation.text == recorded["response"]["recommendation"]["text"]
    assert result.draft_reply is None
    assert "status.insufficient_evidence_to_needs_information" in engine.response_normalizations


def test_evidence_shortage_without_questions_keeps_original_status():
    engine, _ = make_engine(
        [
            action("search_policy", query="정액 보상"),
            action(
                "finish",
                status="insufficient_evidence",
                recommendation=Recommendation(
                    text="수집한 정책에서 근거를 찾지 못했습니다.", evidence_ids=[]
                ),
            ),
        ],
        [policy_result([])],
    )
    result = run(engine)
    assert result.status == "insufficient_evidence"
    assert result.missing_fields == []
    assert engine.response_normalizations == []


def test_information_status_is_not_rewritten_when_already_consistent():
    field = MissingField(field="other", item_id=None, question="정확한 마감 시각을 확인해 주세요.")
    engine, _ = make_engine(
        [
            action(
                "finish",
                status="needs_information",
                missing_fields=[field],
                recommendation=Recommendation(text="추가 확인이 필요합니다.", evidence_ids=[]),
            ),
        ]
    )
    result = run(engine)
    assert result.status == "needs_information"
    assert result.missing_fields == [field]
    assert engine.response_normalizations == []


def test_information_status_normalization_still_rejects_invalid_citations():
    field = MissingField(field="other", item_id=None, question="마감 시각을 확인해 주세요.")
    engine, _ = make_engine(
        [
            action(
                "finish",
                status="insufficient_evidence",
                missing_fields=[field],
                applied_policies=[AppliedPolicy(text="가짜 인용", evidence_ids=["invented"])],
                recommendation=Recommendation(text="확인 필요", evidence_ids=[]),
            ),
        ]
    )
    result = run(engine)
    assert result.status == "system_error"
    assert result.draft_reply is None
    assert engine.last_response_error["type"] == "ValidationError"
