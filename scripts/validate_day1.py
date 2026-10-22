"""Validate policy provenance and evaluation definitions offline, not agent accuracy."""

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import get_args
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from app.config import ROOT, get_settings
from app.consultation_contract import ConsultationRequest, ConsultationStatus, MissingFieldName
from app.repositories.orders import fetch_order
from app.schemas import OrderFound, OrderNotFound
from scripts.curate_policies import extract


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def validate() -> dict:
    base = ROOT / "data/policies"
    manifest = load(base / "manifest.json")
    corpus = load(base / manifest["curated_path"])
    selection = load(base / "selection.json")
    cases = load(ROOT / "data/eval/cases.json")
    seed = load(ROOT / "data/orders/manifest.json")
    assert cases["corpus_version"] == manifest["corpus_version"] == corpus["corpus_version"]
    assert cases["seed_version"] == seed["seed_version"]
    assert cases["reference_time"] == seed["reference_time"]
    assert manifest["stage"] == "reviewed_not_embedded"
    assert len(manifest["documents"]) == 3
    assert (
        hashlib.sha256((base / manifest["curated_path"]).read_bytes()).hexdigest()
        == (manifest["curated_sha256"])
    )
    documents = {doc["document_id"]: doc for doc in manifest["documents"]}
    for doc in documents.values():
        assert doc["effective_date"] is None
        assert datetime.fromisoformat(doc["collected_at"]).tzinfo is not None
        assert (
            hashlib.sha256((base / doc["raw_path"]).read_bytes()).hexdigest() == (doc["raw_sha256"])
        )
    rules = {rule["rule_group_id"]: rule for rule in corpus["rule_groups"]}
    assert len(rules) == manifest["rule_group_count"] == 11
    for selected in selection["rules"]:
        rule = rules[selected["rule_group_id"]]
        doc = documents[rule["document_id"]]
        soup = BeautifulSoup((base / doc["raw_path"]).read_bytes(), "html.parser")
        actual, anchor = extract(soup, rule["heading"], rule["mode"])
        assert actual == rule["text"] and anchor == rule["source_anchor"]
        assert rule["source_url"] == doc["source_url"]
        assert rule["collected_at"] == doc["collected_at"]
        assert rule["effective_date"] is None
        assert hashlib.sha256(rule["text"].encode("utf-8")).hexdigest() == rule["text_sha256"]
        assert all(group in rules for group in rule["related_rule_groups"])
        assert "쇼핑 및 알아보기" not in rule["text"]
    # Regressions that would separate a rule from its exception or timeline.
    cancellation = rules["order-cancellation"]["text"]
    assert all(
        word in cancellation for word in ["출고 준비 중", "출고됨", "Visa", "MasterCard", "Diners"]
    )
    assert "단일 품목" in cancellation
    assert "반품을 신청하고 14일" in rules["returns-process"]["text"]
    standard = rules["returns-standard"]["text"]
    assert all(
        word in standard for word in ["14일", "영수증", "액세서리", "국가", "다운로드", "보안"]
    )
    ids = [case["id"] for case in cases["cases"]]
    assert len(ids) == len(set(ids)) == 24
    reference = datetime.fromisoformat(cases["reference_time"]).astimezone(ZoneInfo("Asia/Seoul"))
    for case in cases["cases"]:
        ConsultationRequest.model_validate(
            {key: case[key] for key in ("question", "order_id", "target_item_id")}
        )
        expected = case["expected"]
        assert set(expected["statuses"]).issubset(get_args(ConsultationStatus))
        assert set(expected["missing_fields"]).issubset(get_args(MissingFieldName))
        assert set(expected["rule_groups"]).issubset(rules)
        tools = expected["tools"]
        assert 0 <= tools["search_policy_min"] <= tools["search_policy_max"] <= 2
        assert tools["lookup_order"] in (0, 1)
        assert tools["lookup_order"] + tools["search_policy_max"] <= 3
        for search in case.get("mock_search_results", []):
            assert set(search).issubset(rules)
        if case["order_id"] is not None:
            result = fetch_order(case["order_id"], get_settings().db_path)
            if case["category"] == "order_not_found":
                assert isinstance(result, OrderNotFound)
            else:
                assert isinstance(result, OrderFound)
                if case["target_item_id"] is not None:
                    assert any(
                        item.item_id == case["target_item_id"] for item in result.order.items
                    )
                if date_check := expected.get("date_check"):
                    item = next(
                        item for item in result.order.items if item.item_id == date_check["item_id"]
                    )
                    assert item.delivered_at is not None
                    received = item.delivered_at.astimezone(ZoneInfo("Asia/Seoul"))
                    assert (reference.date() - received.date()).days == date_check["elapsed_days"]
    return {
        "checked_at": datetime.now(UTC).isoformat(),
        "documents": 3,
        "rule_groups": 11,
        "evaluation_cases": 24,
        "reference_time": cases["reference_time"],
        "corpus_version": cases["corpus_version"],
        "seed_version": cases["seed_version"],
        "policy_provenance_and_dataset_consistency": "passed",
        "retrieval_accuracy": "not_run_day2",
        "agent_behavior": "not_run_not_implemented",
        "paid_api_calls": 0,
    }


def main() -> None:
    report = validate()
    (ROOT / "docs/day1-validation.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    print("Day 1 checks: 3 sources / 11 rule groups / 24 evaluation definitions verified")
    print("Retrieval and agent accuracy have NOT been evaluated")


if __name__ == "__main__":
    main()
