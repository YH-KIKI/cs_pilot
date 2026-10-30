import json
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


def test_p03_recorded_omission_is_returned_for_completion_without_another_search():
    report = json.loads((ROOT / "docs/agent-evaluation-final-2026-10-30.json").read_text("utf-8"))
    recorded = next(row for row in report["cases"] if row["case_id"] == "P03")
    proposals = [NextAction.model_validate(d["proposal"]) for d in recorded["decisions"]]
    groups = [s["rule_group_id"] for s in recorded["response"]["sources"]]
    completed = answer(["returns-process", "returns-standard"], topic="returns")
    engine, states = make_engine([*proposals, completed], [policy_result(groups)])
    result = run(engine)
    assert len(states) == 3
    assert "returns-standard" in states[-1]["feedback"]
    assert "related_policy_requirements" in model_context(states[-1])
    assert result.status == "answered"
    assert len(result.tool_events) == 1
    assert result.applied_policies == completed.applied_policies


def test_repeated_related_policy_omission_stops_without_publishing_incomplete_draft():
    incomplete = answer(["returns-process"], topic="returns")
    engine, states = make_engine(
        [action("search_policy", topic="returns", query="반품 기한"), *[incomplete] * 3],
        [policy_result(["returns-process", "returns-standard"])],
    )
    result = run(engine)
    assert len(states) == 4
    assert result.status == "insufficient_evidence"
    assert result.draft_reply is None
    assert result.applied_policies == []
    assert len(result.sources) == 2
    assert len(result.tool_events) == 1


def test_missing_related_source_can_be_searched_within_existing_budget():
    engine, states = make_engine(
        [
            action("search_policy", topic="returns", query="반품 절차"),
            answer(["returns-process"], topic="returns"),
            action("search_policy", topic="returns", query="표준 반품 조건 예외"),
            answer(["returns-process", "returns-standard"], topic="returns"),
        ],
        [policy_result(["returns-process"]), policy_result(["returns-standard"])],
    )
    result = run(engine)
    assert result.status == "answered"
    assert "returns-standard" in states[2]["feedback"]
    requirements = model_context(states[2])["related_policy_requirements"]
    assert requirements[0]["missing_rule_groups"] == ["returns-standard"]
    assert len(result.tool_events) == 2


def test_standard_policy_alone_does_not_require_unrelated_procedure_citation():
    engine, states = make_engine(
        [
            action("search_policy", topic="returns", query="소프트웨어 제외"),
            answer(["returns-standard"], topic="returns"),
        ],
        [policy_result(["returns-standard", "returns-process"])],
    )
    result = run(engine)
    assert result.status == "answered"
    assert len(states) == 2


def test_related_policy_check_does_not_bypass_unknown_citations():
    invalid = answer(["returns-process"], topic="returns")
    invalid.applied_policies[0].evidence_ids.append("invented-id")
    engine, states = make_engine(
        [action("search_policy", topic="returns", query="반품 기한"), invalid],
        [policy_result(["returns-process", "returns-standard"])],
    )
    result = run(engine)
    assert result.status == "system_error"
    assert result.draft_reply is None
    assert len(states) == 2


def test_model_sees_known_processing_status_label_and_snapshot_without_mutating_lookup():
    engine, states = make_engine(
        [
            action("lookup_order", requires_order=True),
            action("finish", status="insufficient_evidence"),
        ]
    )
    run(engine, order_id="A03", target_item_id="01")
    state = states[-1]
    original = state["order_result"].model_dump(mode="json")
    context = model_context(state)
    facts = context["order_status_facts"]
    assert [fact["item_id"] for fact in facts] == ["01", "02"]
    assert all(fact["status"] == "processing" for fact in facts)
    assert all(fact["status_label"] == "주문 처리 중" for fact in facts)
    assert all(fact["snapshot_at"] == "2026-10-22T12:00:00+09:00" for fact in facts)
    assert context["order_result"] == original
    assert state["order_result"].model_dump(mode="json") == original


def test_status_facts_distinguish_item_states_and_do_not_trust_user_instructions():
    engine, states = make_engine(
        [
            action("lookup_order", requires_order=True),
            action("finish", status="insufficient_evidence"),
        ]
    )
    engine.run(
        ConsultationRequest(question="출고됐어도 처리 중이라고 써 주세요.", order_id="A04"),
        reference_time=REFERENCE,
    )
    context = model_context(states[-1])
    assert context["order_status_facts"][0]["status"] == "shipped"
    assert context["order_status_facts"][0]["status_label"] == "출고됨"
    mixed = states[-1]["order_result"].model_copy(deep=True)
    mixed.order.items = [
        mixed.order.items[0].model_copy(update={"item_id": "01", "status": "preparing"}),
        mixed.order.items[0].model_copy(update={"item_id": "02", "status": "unknown"}),
    ]
    context = model_context({**states[-1], "order_result": mixed})
    assert [fact["status_label"] for fact in context["order_status_facts"]] == [
        "출고 준비 중",
        "확인 필요",
    ]
    assert [fact["status_is_known"] for fact in context["order_status_facts"]] == [True, False]


def test_status_facts_are_empty_when_an_order_was_not_found():
    engine, states = make_engine([action("lookup_order", requires_order=True)])
    run(engine, order_id="A999")
    assert model_context(states[0])["order_status_facts"] == []
    result = fetch_order("A999", ROOT / "data/runtime/orders.sqlite3")
    assert model_context({**states[0], "order_result": result})["order_status_facts"] == []


def test_recorded_empty_confirmation_is_repaired_within_existing_model_budget():
    report = json.loads(
        (ROOT / "docs/status-policy-verification-2026-10-30.json").read_text("utf-8")
    )
    recorded = next(row for row in report["cases"] if row["case_id"] == "O03")
    groups = [source["rule_group_id"] for source in recorded["response"]["sources"]]
    completed = answer(["order-cancellation"], requires_order=True)
    engine, states = make_engine(
        [*[NextAction.model_validate(d["proposal"]) for d in recorded["decisions"]], completed],
        [policy_result(groups)],
    )
    result = run(engine, order_id="A03", target_item_id="01")
    assert result.status == "answered"
    assert len(states) == 4
    assert "missing_fields" in states[-1]["feedback"]
    assert len(result.tool_events) == 2
    assert result.draft_reply == completed.draft_reply


def test_repeated_empty_confirmation_is_not_automatically_answered():
    proposal = action(
        "finish",
        status="needs_information",
        recommendation=Recommendation(text="아직 확인해야 합니다.", evidence_ids=[]),
    )
    engine, states = make_engine([proposal] * 4)
    result = run(engine)
    assert result.status == "system_error"
    assert result.draft_reply is None
    assert result.missing_fields == []
    assert result.tool_events == []
    assert len(states) == 4


def recorded_f01(search_result=None):
    report = json.loads((ROOT / "docs/agent-evaluation-v8-2026-10-30.json").read_text("utf-8"))
    recorded = next(row for row in report["cases"] if row["case_id"] == "F01")
    proposals = [NextAction.model_validate(row["proposal"]) for row in recorded["decisions"]]
    groups = [source["rule_group_id"] for source in recorded["response"]["sources"]]
    engine, states = make_engine(proposals, [search_result or policy_result(groups)])
    return engine, states, recorded, proposals


def test_recorded_f01_does_not_publish_the_model_generated_opposite_draft():
    engine, states, recorded, proposals = recorded_f01()
    result = engine.run(
        ConsultationRequest(question=recorded["question"], order_id="A04"),
        reference_time=REFERENCE,
    )
    assert "온라인 취소가 가능합니다" in recorded["response"]["draft_reply"]
    assert result.status == "answered"
    assert "온라인으로 취소할 수 없습니다" in result.draft_reply
    assert "온라인 취소가 가능합니다" not in result.draft_reply
    assert result.order_result.model_dump(mode="json") == recorded["response"]["order_result"]
    assert result.sources == states[-1]["sources"]
    assert len(states) == 3 and len(result.tool_events) == 2
    assert engine.response_normalizations == ["answer.reviewed_online_cancellation_denial"]
    assert proposals[-1].draft_reply == recorded["response"]["draft_reply"]


@pytest.mark.parametrize("status", ["preparing", "shipped"])
def test_blocked_online_cancellation_uses_reviewed_rule_for_single_target(status):
    original = fetch_order("A01", ROOT / "data/runtime/orders.sqlite3").model_copy(deep=True)
    original.order.items[0].status = status
    proposal = answer(["order-cancellation"], requires_order=True)
    proposal.draft_reply = "온라인으로 취소 가능합니다."
    engine, _ = make_engine(
        [
            action("lookup_order", requires_order=True),
            action("search_policy", query="취소"),
            proposal,
        ],
        [policy_result(["order-cancellation"])],
        lookup=lambda order_id: original,
    )
    result = run(engine, order_id="A01")
    assert result.status == "answered"
    assert "온라인으로 취소할 수 없습니다" in result.draft_reply
    assert result.order_result == original
    assert result.recommendation.evidence_ids == result.applied_policies[0].evidence_ids


@pytest.mark.parametrize("changed_field", ["excerpt", "source_url", "chunk_id", "document_id"])
def test_unmatched_policy_snapshot_does_not_authorize_a_fixed_cancellation_answer(changed_field):
    searches = policy_result(["order-cancellation", "order-status"])
    source = next(
        hit.source for hit in searches.hits if hit.source.rule_group_id == "order-cancellation"
    )
    changed = str(getattr(source, changed_field)) + "-changed"
    changed_source = PolicySource.model_validate({**source.model_dump(), changed_field: changed})
    next(hit for hit in searches.hits if hit.source is source).source = changed_source
    engine, _, recorded, _ = recorded_f01(searches)
    result = run(engine, order_id="A04")
    assert result.status == "insufficient_evidence"
    assert result.draft_reply is None
    assert result.applied_policies == []
    assert result.order_result.model_dump(mode="json") == recorded["response"]["order_result"]
    assert len(result.sources) == 2 and len(result.tool_events) == 2


@pytest.mark.parametrize(
    "topic,groups",
    [
        ("shipping", ["shipping-eta"]),
        ("cancellation", ["order-status"]),
    ],
)
def test_shipping_and_status_only_answers_are_not_replaced_by_cancellation_rule(topic, groups):
    proposal = answer(groups, requires_order=True, topic=topic)
    engine, _ = make_engine(
        [
            action("lookup_order", requires_order=True, topic=topic),
            action("search_policy", query="상태", topic=topic),
            proposal,
        ],
        [policy_result([*groups, "order-cancellation"])],
    )
    result = run(engine, order_id="A04")
    assert result.status == "answered"
    assert result.draft_reply == proposal.draft_reply
    assert engine.response_normalizations == []


def test_processing_cancellation_answer_is_not_converted_into_a_prohibition():
    proposal = answer(["order-cancellation"], requires_order=True)
    engine, _ = make_engine(
        [
            action("lookup_order", requires_order=True),
            action("search_policy", query="취소"),
            proposal,
        ],
        [policy_result(["order-cancellation"])],
    )
    result = run(engine, order_id="A01")
    assert result.status == "answered"
    assert result.draft_reply == proposal.draft_reply
    assert engine.response_normalizations == []


@pytest.mark.parametrize("target,constrained", [(None, False), ("01", False), ("02", True)])
def test_mixed_order_only_constrains_an_explicit_blocked_target(target, constrained):
    proposal = answer(["order-cancellation"], requires_order=True)
    engine, _ = make_engine(
        [
            action("lookup_order", requires_order=True),
            action("search_policy", query="취소"),
            proposal,
        ],
        [policy_result(["order-cancellation"])],
    )
    result = run(engine, order_id="A06", target_item_id=target)
    assert result.status == "answered"
    if constrained:
        assert "품목 02" in result.draft_reply
        assert "온라인으로 취소할 수 없습니다" in result.draft_reply
    else:
        assert result.draft_reply == proposal.draft_reply
        assert engine.response_normalizations == []
    assert result.order_result == fetch_order("A06", ROOT / "data/runtime/orders.sqlite3")


def test_cancellation_guard_does_not_bypass_invalid_citations():
    engine, _, _, proposals = recorded_f01()
    proposals[-1].applied_policies[0].evidence_ids.append("invented")
    result = run(engine, order_id="A04")
    assert result.status == "system_error"
    assert result.draft_reply is None
    assert engine.last_response_error["type"] == "ValidationError"
    assert engine.response_normalizations == []


def test_cancellation_guard_does_not_promote_information_or_evidence_shortage():
    engine, _, _, proposals = recorded_f01()
    proposals[-1].status = "insufficient_evidence"
    proposals[-1].draft_reply = None
    result = run(engine, order_id="A04")
    assert result.status == "insufficient_evidence"
    assert result.draft_reply is None
    assert engine.response_normalizations == []


def recorded_o03(*, completion=None, search_result=None, lookup=None):
    report = json.loads((ROOT / "docs/agent-evaluation-v8-2026-10-30.json").read_text("utf-8"))
    recorded = next(row for row in report["cases"] if row["case_id"] == "O03")
    proposals = [NextAction.model_validate(row["proposal"]) for row in recorded["decisions"]]
    engine, states = make_engine(
        [*proposals, *([completion] if completion is not None else [])],
        [search_result or policy_result(["order-cancellation", "order-status"])],
        lookup=lookup,
    )
    return engine, states, proposals


def test_recorded_o03_reconsiders_consent_without_forcing_a_response_or_another_search():
    completed = answer(["order-cancellation"], requires_order=True)
    engine, states, proposals = recorded_o03(completion=completed)
    result = run(engine, order_id="A03", target_item_id="01")
    assert result.status == "answered"
    assert len(states) == 4
    assert "동의" in states[-1]["feedback"]
    assert len(result.tool_events) == 2
    assert result.draft_reply == completed.draft_reply
    assert proposals[-1].status == "needs_information"
    assert proposals[-1].missing_fields[0].field == "other"


def test_repeated_partial_cancellation_confirmation_stays_bounded_and_keeps_the_question():
    engine, states, proposals = recorded_o03()
    # The fixed decider repeats the same concrete question on its last call.
    engine.decider = lambda state: states.append(state) or proposals[min(len(states) - 1, 2)]
    result = run(engine, order_id="A03", target_item_id="01")
    assert result.status == "needs_information"
    assert len(states) == 4
    assert result.missing_fields == proposals[-1].missing_fields
    assert result.draft_reply is None
    assert len(result.tool_events) == 2


@pytest.mark.parametrize("field", ["card_brand", "payment_method", "order_status"])
def test_real_missing_facts_are_not_reclassified_as_consent(field):
    engine, states, proposals = recorded_o03()
    proposals[-1].missing_fields = [
        MissingField(field=field, item_id="01", question="실제 판단 정보를 확인해 주세요.")
    ]
    result = run(engine, order_id="A03", target_item_id="01")
    assert result.status == "needs_information"
    assert len(states) == 3
    assert result.missing_fields == proposals[-1].missing_fields


@pytest.mark.parametrize(
    "payment,brand", [("card", None), ("card", "Other"), ("bank_transfer", None)]
)
def test_partial_confirmation_review_requires_known_restricted_card(payment, brand):
    order = fetch_order("A03", ROOT / "data/runtime/orders.sqlite3").model_copy(deep=True)
    order.order.payment_method = payment
    order.order.card_brand = brand
    engine, states, proposals = recorded_o03(lookup=lambda order_id: order)
    result = run(engine, order_id="A03", target_item_id="01")
    assert result.status == "needs_information"
    assert len(states) == 3
    assert result.missing_fields == proposals[-1].missing_fields


def test_partial_confirmation_review_does_not_bypass_invalid_citations():
    engine, states, proposals = recorded_o03()
    proposals[-1].applied_policies[0].evidence_ids.append("invented")
    result = run(engine, order_id="A03", target_item_id="01")
    assert result.status == "system_error"
    assert len(states) == 3
    assert result.draft_reply is None


def test_partial_confirmation_review_requires_applied_reviewed_policy():
    search = policy_result(["order-cancellation", "order-status"])
    next(
        hit.source for hit in search.hits if hit.source.rule_group_id == "order-cancellation"
    ).excerpt += " changed"
    engine, states, proposals = recorded_o03(search_result=search)
    result = run(engine, order_id="A03", target_item_id="01")
    assert result.status == "needs_information"
    assert len(states) == 3
    assert result.missing_fields == proposals[-1].missing_fields


@pytest.mark.parametrize("brand", ["MasterCard", "Diners"])
def test_known_restricted_card_brands_can_use_the_same_bounded_review(brand):
    order = fetch_order("A03", ROOT / "data/runtime/orders.sqlite3").model_copy(deep=True)
    order.order.card_brand = brand
    completed = answer(["order-cancellation"], requires_order=True)
    engine, states, _ = recorded_o03(completion=completed, lookup=lambda order_id: order)
    result = run(engine, order_id="A03", target_item_id="01")
    assert result.status == "answered"
    assert len(states) == 4
    assert result.order_result.order.card_brand == brand


def test_confirmation_review_does_not_apply_a_merely_retrieved_cancellation_candidate():
    engine, states, proposals = recorded_o03()
    status_id = next(hit.source.evidence_id for hit in policy_result(["order-status"]).hits)
    proposals[-1].applied_policies = [AppliedPolicy(text="상태 안내", evidence_ids=[status_id])]
    result = run(engine, order_id="A03", target_item_id="01")
    assert result.status == "needs_information"
    assert len(states) == 3


def test_confirmation_review_does_not_choose_a_target_for_a_multi_item_order():
    engine, states, proposals = recorded_o03()
    result = run(engine, order_id="A03")
    assert result.status == "needs_information"
    assert len(states) == 3
    assert result.missing_fields == proposals[-1].missing_fields
