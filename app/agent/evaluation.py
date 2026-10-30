"""Evaluation fixtures and independent structural checks; never change agent behavior."""

from datetime import datetime
from zoneinfo import ZoneInfo

from app.agent.models import NextAction
from app.config import ROOT
from app.consultation_contract import ConsultationResponse, PolicySource
from app.rag.chunks import PolicyChunk, load_chunks
from app.rag.retrieval import PolicyHit, PolicySearchResult
from app.repositories.orders import fetch_order


def source_from_chunk(chunk: PolicyChunk) -> PolicySource:
    return PolicySource(
        evidence_id="evidence-" + chunk.chunk_id,
        document_id=chunk.document_id,
        rule_group_id=chunk.rule_group_id,
        chunk_id=chunk.chunk_id,
        title=chunk.title,
        heading=chunk.heading,
        source_url=chunk.source_url,
        collected_at=chunk.collected_at,
        effective_date=chunk.effective_date,
        excerpt=chunk.text,
    )


def fixture_search(groups: list[str], query: str) -> PolicySearchResult:
    chunks, _ = load_chunks()
    by_group = {chunk.rule_group_id: chunk for chunk in chunks}
    return PolicySearchResult(
        kind="candidates",
        query=query,
        embedding_provider="mocked_frozen_policy",
        seed_rule_groups=groups,
        hits=[
            PolicyHit(source=source_from_chunk(by_group[group]), distance=None, reason="retrieved")
            for group in groups
        ],
        message="Evaluation fixture, not a real vector search",
    )


class LimitRequestDecider:
    """L01 must demand a third search; this case does not call a real LLM."""

    usage: list[dict]

    def __init__(self):
        self.usage = []

    def __call__(self, state) -> NextAction:
        return NextAction(
            action="lookup_order"
            if state["order_result"].kind == "not_requested"
            else "search_policy",
            requires_order=True,
            topic="shipping",
            query="배송 지연 정액 보상",
            status=None,
            applied_policies=[],
            recommendation=None,
            draft_reply=None,
            missing_fields=[],
        )


def check_case(case: dict, response: ConsultationResponse, reference: datetime) -> dict:
    expected = case["expected"]
    counts = {
        name: sum(event.tool_name == name for event in response.tool_events)
        for name in ("lookup_order", "search_policy")
    }
    chunks, _ = load_chunks()
    by_group = {chunk.rule_group_id: chunk for chunk in chunks}
    ids = {source.evidence_id: source.rule_group_id for source in response.sources}
    applied_groups = {
        ids[evidence_id]
        for policy in response.applied_policies
        for evidence_id in policy.evidence_ids
        if evidence_id in ids
    }
    references = set(expected["rule_groups"])
    retrieved_groups = set(ids.values())
    if references:
        groups_match = (
            bool(references.intersection(retrieved_groups))
            if expected.get("rule_group_match", "all") == "any"
            else references.issubset(retrieved_groups)
        )
    else:
        groups_match = True
    checks = {
        "status": response.status in expected["statuses"],
        "lookup_count": counts["lookup_order"] == expected["tools"]["lookup_order"],
        "search_count": expected["tools"]["search_policy_min"]
        <= counts["search_policy"]
        <= expected["tools"]["search_policy_max"],
        "missing_fields": set(expected["missing_fields"]).issubset(
            field.field for field in response.missing_fields
        ),
        "expected_rule_groups_retrieved": groups_match,
        "reference_time": response.reference_time == reference,
        "source_provenance": all(
            source.rule_group_id in by_group
            and source == source_from_chunk(by_group[source.rule_group_id])
            for source in response.sources
        ),
        "tool_limits": len(response.tool_events) <= 3
        and counts["lookup_order"] <= 1
        and counts["search_policy"] <= 2,
    }
    if references and response.status == "answered":
        checks["answer_applies_expected_groups"] = (
            bool(references.intersection(applied_groups))
            if expected.get("rule_group_match", "all") == "any"
            else references.issubset(applied_groups)
        )
    if counts["lookup_order"]:
        if case.get("mock_error") == "lookup_order":
            checks["order_facts"] = response.order_result.kind == "error"
        else:
            actual = fetch_order(case["order_id"], ROOT / "data/runtime/orders.sqlite3")
            checks["order_facts"] = response.order_result == actual
    else:
        checks["order_facts"] = response.order_result.kind == "not_requested"
    date_check = expected.get("date_check")
    elapsed = None
    if date_check:
        result = response.order_result
        if result.kind == "found":
            item = next((i for i in result.order.items if i.item_id == date_check["item_id"]), None)
            if item and item.delivered_at:
                zone = ZoneInfo("Asia/Seoul")
                elapsed = (
                    reference.astimezone(zone).date() - item.delivered_at.astimezone(zone).date()
                ).days
        checks["date_facts"] = elapsed == date_check["elapsed_days"]
    # Re-validate the public response, including ordered events and citation references.
    try:
        ConsultationResponse.model_validate(response.model_dump(mode="json"))
        checks["response_contract"] = True
    except ValueError:
        checks["response_contract"] = False
    return {
        "checks": checks,
        "structural_pass": all(checks.values()),
        "failed_checks": [name for name, passed in checks.items() if not passed],
        "actual_tool_counts": counts,
        "actual_applied_groups": sorted(applied_groups),
        "actual_elapsed_days": elapsed,
        "semantic_checklist": {
            "must_include": expected["must_include"],
            "must_not_include": expected["must_not_include"],
            "review_status": "pending_manual_review",
        },
    }
