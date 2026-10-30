import copy
import json

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.config import ROOT
from app.consultation_contract import ConsultationRequest, ConsultationResponse
from app.main import app
from scripts.validate_day1 import validate


def examples():
    return json.loads((ROOT / "data/contracts/examples.json").read_text("utf-8"))


def test_policy_provenance_rules_and_evaluation_definitions():
    assert validate()["evaluation_cases"] == 24


def test_all_response_statuses_and_requests_validate():
    fixtures = examples()
    assert fixtures["fixture_only"] is True
    for request in fixtures["requests"]:
        ConsultationRequest.model_validate(request)
    statuses = {ConsultationResponse.model_validate(item).status for item in fixtures["responses"]}
    assert len(statuses) == 6


@pytest.mark.parametrize(
    "payload",
    [
        {"question": "   "},
        {"question": "x" * 2001},
        {"question": "hello", "order_id": 123},
        {"question": "hello", "target_item_id": "01"},
        {"question": "hello", "reference_time": "2026-10-22"},
    ],
)
def test_invalid_requests_are_rejected(payload):
    with pytest.raises(ValidationError):
        ConsultationRequest.model_validate(payload)


def test_fake_citations_and_ungrounded_answer_are_rejected():
    answered = examples()["responses"][0]
    invalid = copy.deepcopy(answered)
    invalid["applied_policies"][0]["evidence_ids"] = ["does-not-exist"]
    with pytest.raises(ValidationError, match="Unknown evidence"):
        ConsultationResponse.model_validate(invalid)
    invalid = copy.deepcopy(answered)
    invalid["sources"] = []
    with pytest.raises(ValidationError):
        ConsultationResponse.model_validate(invalid)


def test_information_and_tool_limits_are_enforced():
    invalid = examples()["responses"][1]
    invalid["missing_fields"] = []
    with pytest.raises(ValidationError, match="Missing information"):
        ConsultationResponse.model_validate(invalid)
    invalid = examples()["responses"][4]
    invalid["tool_events"].append(copy.deepcopy(invalid["tool_events"][-1]))
    with pytest.raises(ValidationError):
        ConsultationResponse.model_validate(invalid)


def test_consultation_api_disabled_without_explicit_opt_in(monkeypatch):
    from app.config import Settings

    monkeypatch.setattr(
        "app.agent.model.get_settings", lambda: Settings(_env_file=None, agent_allow_api=False)
    )
    with TestClient(app) as client:
        response = client.post("/api/consultations", json={"question": "표준 배송비?"})
        assert response.status_code == 200
        assert response.json()["status"] == "system_error"
        assert response.json()["tool_events"] == []
        assert client.post("/api/consultations", json={"question": " "}).status_code == 422
    schema = app.openapi()
    assert "200" in schema["paths"]["/api/consultations"]["post"]["responses"]
    assert "501" not in schema["paths"]["/api/consultations"]["post"]["responses"]
    frozen = json.loads((ROOT / "docs/api-contract.openapi.json").read_text("utf-8"))
    assert frozen == schema
