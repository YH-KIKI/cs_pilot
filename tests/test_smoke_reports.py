import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.config import ROOT
from app.consultation_contract import ConsultationResponse
from scripts import smoke_agent


@pytest.fixture
def smoke_files(tmp_path, monkeypatch):
    suite = ROOT / "data/eval/cases.json"
    baseline = (ROOT / "docs/day3-agent-smoke.json").read_bytes()
    (tmp_path / "data/eval").mkdir(parents=True)
    (tmp_path / "data/eval/cases.json").write_bytes(suite.read_bytes())
    (tmp_path / "docs").mkdir()
    target = tmp_path / "docs/day3-agent-smoke.json"
    target.write_bytes(baseline)
    row = next(c for c in json.loads(baseline)["cases"] if c["case_id"] == "O08")
    engine = SimpleNamespace(
        run=Mock(return_value=ConsultationResponse.model_validate(row["response"])),
        decider=SimpleNamespace(usage=[]),
        last_model_error=None,
    )
    factory = Mock(return_value=engine)
    monkeypatch.setattr(smoke_agent, "ROOT", tmp_path)
    monkeypatch.setattr(smoke_agent, "get_consultation_engine", factory)
    monkeypatch.setattr(
        smoke_agent, "get_settings", Mock(return_value=SimpleNamespace(openai_model="test-model"))
    )
    monkeypatch.setenv("AGENT_ALLOW_API", "false")
    monkeypatch.setenv("RAG_ALLOW_API", "false")
    return tmp_path, target, baseline, factory, engine


def run_smoke(monkeypatch, *extra):
    monkeypatch.setattr(
        "sys.argv", ["smoke_agent", "--allow-api", "--case", "O08", *map(str, extra)]
    )
    smoke_agent.main()


def test_default_existing_baseline_is_rejected_before_model_call(smoke_files, monkeypatch):
    _, baseline, original, factory, _ = smoke_files
    with pytest.raises(SystemExit) as error:
        run_smoke(monkeypatch)
    assert error.value.code == 2
    factory.assert_not_called()
    assert baseline.read_bytes() == original


def test_fresh_output_keeps_baseline_and_can_be_loaded(smoke_files, monkeypatch):
    root, baseline, original, factory, _ = smoke_files
    output = root / "docs/new-smoke.json"
    run_smoke(monkeypatch, "--output", output)
    report = json.loads(output.read_text("utf-8"))
    assert report["cases"][0]["case_id"] == "O08"
    assert ConsultationResponse.model_validate(report["cases"][0]["response"]).status == (
        "needs_information"
    )
    factory.assert_called_once()
    assert baseline.read_bytes() == original


def test_existing_custom_output_is_rejected_before_model_call(smoke_files, monkeypatch):
    root, baseline, original, factory, _ = smoke_files
    output = root / "docs/new-smoke.json"
    output.write_text("existing result", encoding="utf-8")
    with pytest.raises(SystemExit) as error:
        run_smoke(monkeypatch, "--output", output)
    assert error.value.code == 2
    assert output.read_text("utf-8") == "existing result"
    assert baseline.read_bytes() == original
    factory.assert_not_called()


@pytest.mark.parametrize("relative", ["outside.json", "docs/wrong.txt"])
def test_invalid_output_is_rejected_before_model_call(smoke_files, monkeypatch, relative):
    root, _, _, factory, _ = smoke_files
    output = root / relative
    with pytest.raises(SystemExit) as error:
        run_smoke(monkeypatch, "--output", output)
    assert error.value.code == 2
    assert not output.exists()
    factory.assert_not_called()


def test_file_created_during_run_is_not_overwritten(smoke_files, monkeypatch):
    root, baseline, original, _, engine = smoke_files
    output = root / "docs/new-smoke.json"
    response = engine.run.return_value

    def another_writer(*args, **kwargs):
        output.write_text("another writer's result", encoding="utf-8")
        return response

    engine.run.side_effect = another_writer
    with pytest.raises(SystemExit) as error:
        run_smoke(monkeypatch, "--output", output)
    assert error.value.code == 2
    assert output.read_text("utf-8") == "another writer's result"
    assert baseline.read_bytes() == original
