"""Render one reviewed cancellation restriction, not a general semantic checker."""

from hashlib import sha256

from app.consultation_contract import (
    AppliedPolicy,
    ConsultationRequest,
    ConsultationResponse,
    PolicySource,
    Recommendation,
)

# Bound to the reviewed apple-kr-20261023-v1 snapshot. A policy update requires
# reviewing this interpretation and its tests, not silently reusing the rule.
CANCELLATION_CHUNK = "policy-2a0e84c031bb5f83f5d804c5"
CANCELLATION_TEXT_SHA256 = "28ac3bf0c3b39e8b24d9bef77160266821bfc2bcbae06ebcb7a9a400ec6a023d"
BLOCKED_STATUS_LABELS = {"preparing": "출고 준비 중", "shipped": "출고됨"}


def matches_reviewed_cancellation(source: PolicySource) -> bool:
    return (
        source.document_id == "apple-kr-orders"
        and source.rule_group_id == "order-cancellation"
        and source.chunk_id == CANCELLATION_CHUNK
        and str(source.source_url) == "https://www.apple.com/kr/shop/help/viewing_changing_orders"
        and sha256(source.excerpt.encode("utf-8")).hexdigest() == CANCELLATION_TEXT_SHA256
    )


def constrain_online_cancellation(
    response: ConsultationResponse, request: ConsultationRequest
) -> ConsultationResponse:
    """Replace free text only for a single blocked target and an applied cancel rule.

    General status/shipping questions, merely retrieved candidates, multi-item
    requests without an explicit target and other order statuses stay unchanged.
    """
    if response.status != "answered" or response.order_result.kind != "found":
        return response
    applied_ids = {key for policy in response.applied_policies for key in policy.evidence_ids}
    cancellation_sources = [
        source
        for source in response.sources
        if source.rule_group_id == "order-cancellation" and source.evidence_id in applied_ids
    ]
    if not cancellation_sources:
        return response
    items = [
        item
        for item in response.order_result.order.items
        if request.target_item_id is None or item.item_id == request.target_item_id
    ]
    if len(items) != 1 or items[0].status not in BLOCKED_STATUS_LABELS:
        return response
    source = next(
        (source for source in cancellation_sources if matches_reviewed_cancellation(source)), None
    )
    if source is None:
        updates = {
            "status": "insufficient_evidence",
            "applied_policies": [],
            "recommendation": Recommendation(
                text="적용한 취소 정책이 검수된 제한 규칙과 일치하지 않습니다. "
                "정책 원문을 수동 확인해 주세요.",
                evidence_ids=[],
            ),
            "draft_reply": None,
            "missing_fields": [],
        }
    else:
        item = items[0]
        fact = (
            f"조회 기록상 품목 {item.item_id}({item.product_name})은 "
            f"{item.snapshot_at.isoformat()} 기준 ‘{BLOCKED_STATUS_LABELS[item.status]}’입니다."
        )
        policy = (
            "이 상태의 제품은 공개된 주문 취소 정책에 따라 온라인으로 취소할 수 없습니다. "
            "이는 온라인 취소 제한 안내이며 다른 반품 가능 여부를 확정하지 않습니다."
        )
        direction = (
            "최신 상태는 주문 상태 페이지에서 확인해 주세요. 추가 지원은 "
            "Apple Online Store 고객 서비스(080-330-8877)에 문의해 주세요. "
            "실제 취소·환불을 실행한 것은 아닙니다."
        )
        ids = [source.evidence_id]
        updates = {
            "applied_policies": [AppliedPolicy(text=policy, evidence_ids=ids)],
            "recommendation": Recommendation(text=f"{fact} {policy} {direction}", evidence_ids=ids),
            "draft_reply": f"{fact}\n\n{policy}\n\n{direction}",
            "missing_fields": [],
        }
    # Revalidate the public contract; preserve canonical order, sources and trace.
    return ConsultationResponse.model_validate({**response.model_dump(), **updates})
