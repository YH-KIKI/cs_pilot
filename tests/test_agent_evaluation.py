import json

from app.agent.evaluation import check_case
from app.config import ROOT
from scripts.evaluate_agent import evaluate_one
from scripts.smoke_agent import main as smoke_main


def test_scripted_limit_case_uses_real_controller_and_never_calls_llm():
    from datetime import datetime

    suite = json.loads((ROOT / "data/eval/cases.json").read_text("utf-8"))
    case = next(c for c in suite["cases"] if c["id"] == "L01")
    row = evaluate_one(case, datetime.fromisoformat(suite["reference_time"]))
    assert row["evaluation"]["structural_pass"] is True
    assert row["response"]["status"] == "limit_reached"
    assert row["evaluation"]["actual_tool_counts"] == {"lookup_order": 1, "search_policy": 2}
    assert len(row["decisions"]) == 4
    assert row["execution"]["model"] == "scripted_limit_request"
    assert row["model_usage"] == []


def test_checker_reports_actual_mismatches_without_changing_responses():
    from datetime import datetime

    from app.consultation_contract import ConsultationResponse

    smoke = json.loads((ROOT / "docs/day3-agent-smoke.json").read_text("utf-8"))
    suite = json.loads((ROOT / "data/eval/cases.json").read_text("utf-8"))
    case = next(c for c in suite["cases"] if c["id"] == "P01")
    response = ConsultationResponse.model_validate(smoke["cases"][0]["response"])
    before = response.model_dump_json()
    reference = datetime.fromisoformat(suite["reference_time"])
    assert check_case(case, response, reference)["structural_pass"] is True
    case["expected"]["statuses"] = ["needs_information"]
    result = check_case(case, response, reference)
    assert result["structural_pass"] is False
    assert "status" in result["failed_checks"]
    assert result["semantic_checklist"]["review_status"] == "pending_manual_review"
    assert response.model_dump_json() == before


def test_paid_smoke_still_requires_explicit_flag(monkeypatch):
    import pytest

    monkeypatch.setattr("sys.argv", ["smoke_agent"])
    with pytest.raises(SystemExit) as error:
        smoke_main()
    assert error.value.code == 2
