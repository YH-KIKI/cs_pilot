"""Export OpenAPI and clearly labelled contract examples. Never invokes an agent."""

import json

from app.config import ROOT, get_settings
from app.consultation_contract import ConsultationRequest, ConsultationResponse
from app.main import app
from app.repositories.orders import fetch_order


def source(rule: dict, evidence_id: str) -> dict:
    return {
        "evidence_id": evidence_id,
        "document_id": rule["document_id"],
        "rule_group_id": rule["rule_group_id"],
        "chunk_id": None,
        "title": rule["title"],
        "heading": rule["heading"],
        "source_url": rule["source_url"],
        "collected_at": rule["collected_at"],
        "effective_date": rule["effective_date"],
        "excerpt": rule["text"].split("\n")[0],
    }


def main() -> None:
    rules = json.loads((ROOT / "data/policies/curated/rule_groups.json").read_text("utf-8"))
    rules = {rule["rule_group_id"]: rule for rule in rules["rule_groups"]}
    shipping = source(rules["shipping-options"], "src-1")
    reference = "2026-10-22T12:00:00+09:00"
    base = {
        "contract_version": "1.0",
        "request_id": "fixture-answered",
        "reference_time": reference,
        "status": "answered",
        "order_result": {"kind": "not_requested"},
        "sources": [shipping],
        "applied_policies": [{"text": "표준 배송 안내를 적용합니다.", "evidence_ids": ["src-1"]}],
        "recommendation": {
            "text": "표준 배송과 주문별 배송 옵션을 구분해 안내하세요.",
            "evidence_ids": ["src-1"],
        },
        "draft_reply": (
            "표준 배송은 무료이며, "
            "이용 가능한 배송 옵션은 주문 조건에 따라 확인해 주세요."
        ),
        "missing_fields": [],
        "tool_events": [
            {
                "sequence": 1,
                "tool_name": "search_policy",
                "duration_ms": 0,
                "status": "success",
                "input": {"query": "표준 배송비", "topic": "shipping"},
                "result_summary": "계약 예시: 표준 배송 정책 근거",
                "evidence_ids": ["src-1"],
            }
        ],
    }
    examples = [base]
    lookup_event = {
        "sequence": 1,
        "tool_name": "lookup_order",
        "duration_ms": 0,
        "status": "success",
        "input": {"order_id": "A05"},
        "result_summary": "계약 예시: 수령일 미확인",
    }
    empty = {
        **base,
        "sources": [],
        "applied_policies": [],
        "draft_reply": None,
        "recommendation": {"text": "추가 확인 후 안내하세요.", "evidence_ids": []},
        "tool_events": [],
    }
    examples.append(
        {
            **empty,
            "request_id": "fixture-needs-info",
            "status": "needs_information",
            "order_result": fetch_order("A05", get_settings().db_path).model_dump(mode="json"),
            "missing_fields": [
                {"field": "delivered_at", "item_id": "01", "question": "실제 수령일이 언제인가요?"}
            ],
            "tool_events": [lookup_event],
        }
    )
    examples.append(
        {
            **empty,
            "request_id": "fixture-not-found",
            "status": "order_not_found",
            "order_result": {"kind": "not_found", "order_id": "A999"},
            "tool_events": [
                {
                    **lookup_event,
                    "input": {"order_id": "A999"},
                    "result_summary": "계약 예시: 주문 없음",
                }
            ],
        }
    )
    search = {
        "sequence": 1,
        "tool_name": "search_policy",
        "duration_ms": 0,
        "status": "success",
        "input": {"query": "배송 지연 정액 보상", "topic": "shipping"},
        "result_summary": "계약 예시: 적용 근거 부족",
        "evidence_ids": [],
    }
    examples.append(
        {
            **empty,
            "request_id": "fixture-no-evidence",
            "status": "insufficient_evidence",
            "tool_events": [search, {**search, "sequence": 2}],
        }
    )
    examples.append(
        {
            **empty,
            "request_id": "fixture-limit",
            "status": "limit_reached",
            "order_result": fetch_order("A04", get_settings().db_path).model_dump(mode="json"),
            "tool_events": [
                {
                    **lookup_event,
                    "input": {"order_id": "A04"},
                    "result_summary": "계약 예시: 출고됨",
                },
                {**search, "sequence": 2},
                {**search, "sequence": 3},
            ],
        }
    )
    examples.append(
        {
            **empty,
            "request_id": "fixture-system-error",
            "status": "system_error",
            "order_result": {"kind": "error", "message": "계약 예시: DB 조회 오류"},
            "tool_events": [
                {**lookup_event, "status": "error", "result_summary": "계약 예시: DB 오류"}
            ],
        }
    )
    requests = [
        {"question": "표준 배송비를 알려주세요.", "order_id": None, "target_item_id": None},
        {"question": "반품할 수 있나요?", "order_id": "A05", "target_item_id": "01"},
    ]
    target = ROOT / "data/contracts"
    target.mkdir(parents=True, exist_ok=True)
    (target / "examples.json").write_text(
        json.dumps(
            {
                "fixture_only": True,
                "note": "계약 검증 예시이며 실제 AI 실행 결과가 아닙니다.",
                "requests": [
                    ConsultationRequest.model_validate(item).model_dump(mode="json")
                    for item in requests
                ],
                "responses": [
                    ConsultationResponse.model_validate(item).model_dump(mode="json")
                    for item in examples
                ],
                "not_implemented": {
                    "code": "not_implemented",
                    "message": "상담 실행은 아직 연결되지 않았습니다.",
                },
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (ROOT / "docs/api-contract.openapi.json").write_text(
        json.dumps(app.openapi(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print("Exported OpenAPI + 6 response contract fixtures (not live AI outputs)")


if __name__ == "__main__":
    main()
