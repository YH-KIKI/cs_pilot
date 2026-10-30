"""Bounded real-provider smoke checks. Requires --allow-api; never edits .env."""

import argparse
import json
import os
from datetime import UTC, datetime

from app.agent.model import PROMPT_VERSION
from app.agent.service import get_consultation_engine
from app.config import ROOT, get_settings
from app.consultation_contract import ConsultationRequest
from app.rag.chunks import write_json


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-api", action="store_true")
    parser.add_argument("--case", action="append", dest="cases")
    args = parser.parse_args()
    if not args.allow_api:
        parser.error("--allow-api is required for real model/embedding calls")
    cases = args.cases or ["P01", "O03", "E01", "O08"]
    if len(cases) > 6 or len(set(cases)) != len(cases):
        parser.error("Use at most six distinct cases per smoke run")
    suite = json.loads((ROOT / "data/eval/cases.json").read_text("utf-8"))
    eligible = {case["id"]: case for case in suite["cases"] if case["mode"] == "integration"}
    if not set(cases).issubset(eligible):
        parser.error("Only defined integration case IDs are allowed")
    os.environ["AGENT_ALLOW_API"] = "true"
    os.environ["RAG_ALLOW_API"] = "true"
    get_settings.cache_clear()
    rows = []
    for case_id in cases:
        case = eligible[case_id]
        engine = get_consultation_engine()
        request = ConsultationRequest(
            **{key: case[key] for key in ("question", "order_id", "target_item_id")}
        )
        response = engine.run(
            request, reference_time=datetime.fromisoformat(suite["reference_time"])
        )
        expected = case["expected"]
        counts = {
            tool: sum(event.tool_name == tool for event in response.tool_events)
            for tool in ("lookup_order", "search_policy")
        }
        matched = (
            response.status in expected["statuses"]
            and counts["lookup_order"] == expected["tools"]["lookup_order"]
            and expected["tools"]["search_policy_min"]
            <= counts["search_policy"]
            <= expected["tools"]["search_policy_max"]
        )
        rows.append(
            {
                "case_id": case_id,
                "status_and_tool_counts_match": matched,
                "expected_statuses": expected["statuses"],
                "response": response.model_dump(mode="json"),
                "model_usage": engine.decider.usage,
                "model_error": engine.last_model_error,
                "semantic_review": "manual review pending; structural checks only",
            }
        )
        print(
            f"{case_id}: {response.status}, tools={counts}, structural_match={matched}", flush=True
        )
    report = {
        "executed_at": datetime.now(UTC).isoformat(),
        "reference_time": suite["reference_time"],
        "suite_version": suite["suite_version"],
        "corpus_version": suite["corpus_version"],
        "seed_version": suite["seed_version"],
        "model": get_settings().openai_model,
        "prompt_version": PROMPT_VERSION,
        "scope": "small real-provider smoke; not full 24-case agent evaluation",
        "cases": rows,
    }
    write_json(ROOT / "docs/day3-agent-smoke.json", report)


if __name__ == "__main__":
    main()
