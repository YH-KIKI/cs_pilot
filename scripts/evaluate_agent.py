"""Run the unchanged 24-case suite once, with explicit real/mock provenance."""

import argparse
import json
import os
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from app.agent.evaluation import LimitRequestDecider, check_case, fixture_search
from app.agent.model import PROMPT_VERSION, model_context
from app.agent.service import get_consultation_engine
from app.config import ROOT, get_settings
from app.consultation_contract import ConsultationRequest
from app.rag.chunks import digest, write_json
from app.rag.retrieval import PolicySearchResult
from app.schemas import OrderError

REPORT = ROOT / "docs/agent-evaluation-2026-10-30.json"


def evaluate_one(case, reference):
    engine = get_consultation_engine()
    if case.get("mock_behavior"):
        engine.decider = LimitRequestDecider()
    base_decider = engine.decider
    traces = []

    def trace_decision(state):
        proposal = base_decider(state)
        traces.append(
            {
                "action": proposal.action,
                "requires_order": proposal.requires_order,
                "topic": proposal.topic,
                "query": proposal.query,
                "status": proposal.status,
                "date_facts": model_context(state)["date_facts"],
                "proposal": proposal.model_dump(mode="json"),
            }
        )
        return proposal

    engine.decider = trace_decision
    if case.get("mock_error") == "lookup_order":
        engine.lookup = lambda _: OrderError(message="평가에 주입한 DB 오류")
    elif case.get("mock_error") == "search_policy":
        engine.search = lambda query, topic: PolicySearchResult(
            kind="error", query=query, embedding_provider="mocked_error", message="평가 검색 오류"
        )
    elif "mock_search_results" in case:
        fixture_iterator = iter(case["mock_search_results"])
        engine.search = lambda query, topic: fixture_search(next(fixture_iterator, []), query)
    request = ConsultationRequest(
        **{key: case[key] for key in ("question", "order_id", "target_item_id")}
    )
    response = engine.run(request, reference_time=reference)
    return {
        "case_id": case["id"],
        "execution": {
            "model": "scripted_limit_request" if case.get("mock_behavior") else "real_openai",
            "tools": case["mode"],
            "mock_error": case.get("mock_error"),
            "lookup": "mocked_error" if case.get("mock_error") == "lookup_order" else "real_sqlite",
            "search": "real_chroma" if case["mode"] == "integration" else "mocked",
        },
        "question": case["question"],
        "expected_statuses": case["expected"]["statuses"],
        "evaluation": check_case(case, response, reference),
        "response": response.model_dump(mode="json"),
        "decisions": traces,
        "model_usage": base_decider.usage,
        "model_error": engine.last_model_error,
        "response_error": engine.last_response_error,
        "response_normalizations": engine.response_normalizations,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-api", action="store_true")
    parser.add_argument("--output", type=Path, default=REPORT)
    parser.add_argument("--case", action="append", dest="cases")
    args = parser.parse_args()
    if not args.allow_api:
        parser.error("--allow-api is required for this real-provider evaluation")
    output = args.output.resolve()
    if not output.is_relative_to((ROOT / "docs").resolve()):
        parser.error("--output must stay under docs")
    if output.exists():
        parser.error("Report already exists; preserve it before intentionally starting a new run")
    os.environ["AGENT_ALLOW_API"] = "true"
    os.environ["RAG_ALLOW_API"] = "true"
    get_settings.cache_clear()
    suite_bytes = (ROOT / "data/eval/cases.json").read_bytes()
    suite = json.loads(suite_bytes)
    if len(suite["cases"]) != 24:
        parser.error("Expected the fixed 24-case suite")
    selected = suite["cases"]
    if args.cases:
        by_id = {case["id"]: case for case in selected}
        if len(set(args.cases)) != len(args.cases) or not set(args.cases).issubset(by_id):
            parser.error("Use distinct case IDs from the fixed suite")
        selected = [by_id[name] for name in args.cases]
    code_paths = sorted((ROOT / "app/agent").glob("*.py"))
    report = {
        "started_at": datetime.now(UTC).isoformat(),
        "reference_time": suite["reference_time"],
        "suite_version": suite["suite_version"],
        "suite_sha256": digest(suite_bytes),
        "corpus_version": suite["corpus_version"],
        "seed_version": suite["seed_version"],
        "model": get_settings().openai_model,
        "prompt_version": PROMPT_VERSION,
        "agent_code_sha256": {str(p.relative_to(ROOT)): digest(p.read_bytes()) for p in code_paths},
        "status": "running",
        "cases": [],
        "note": "Structural checks are not semantic answer accuracy; L01 uses a scripted model.",
    }
    reference = datetime.fromisoformat(suite["reference_time"])
    write_json(output, report)
    for index, case in enumerate(selected, start=1):
        row = evaluate_one(case, reference)
        report["cases"].append(row)
        write_json(output, report)
        evaluation = row["evaluation"]
        print(
            f"{index}/{len(selected)} {case['id']}: {row['response']['status']}; "
            f"failed={evaluation['failed_checks']}; model={row['execution']['model']}",
            flush=True,
        )
    report["status"] = "completed"
    report["completed_at"] = datetime.now(UTC).isoformat()
    report["summary"] = {
        "cases": len(report["cases"]),
        "structural_pass": sum(r["evaluation"]["structural_pass"] for r in report["cases"]),
        "failed_case_ids": [
            r["case_id"] for r in report["cases"] if not r["evaluation"]["structural_pass"]
        ],
        "model_modes": dict(Counter(r["execution"]["model"] for r in report["cases"])),
        "real_model_calls": sum(len(r["model_usage"]) for r in report["cases"]),
        "model_tokens": {
            key: sum(u.get(key, 0) for r in report["cases"] for u in r["model_usage"])
            for key in ("input_tokens", "output_tokens", "total_tokens")
        },
        "semantic_review": "pending_manual_review",
        "actual_cost_and_embedding_tokens": "not_collected",
    }
    write_json(output, report)
    print(json.dumps(report["summary"], ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
