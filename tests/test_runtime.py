import json
import shutil
import sqlite3
from contextlib import closing
from unittest.mock import Mock

import pytest

from app.config import Settings
from app.rag.chunks import ARTIFACTS
from app.repositories.orders import connect_readonly, fetch_order
from app.runtime import prepare_runtime
from scripts import start


@pytest.fixture
def runtime_settings(tmp_path, monkeypatch):
    def forbidden_backend(*args, **kwargs):
        raise AssertionError("Startup must not construct an embedding backend")

    monkeypatch.setattr("app.runtime.openai_backend", forbidden_backend)
    return Settings(
        _env_file=None,
        orders_db_path=tmp_path / "orders.sqlite3",
        agent_allow_api=True,
        rag_allow_api=True,
        openai_api_key="unused-test-key",
    )


def test_prepare_runtime_restores_fixed_data_without_api_and_reuses_it(runtime_settings, tmp_path):
    directory = tmp_path / "chroma"
    first = prepare_runtime(runtime_settings, index_directory=directory)
    before = runtime_settings.db_path.read_bytes()
    second = prepare_runtime(runtime_settings, index_directory=directory)
    frozen = json.loads((ARTIFACTS / "index_manifest.json").read_text("utf-8"))
    assert first["policy_chunks"] == first["restored_chunks"] == 11
    assert second["restored_chunks"] == 0
    assert first["embedding_backend_batches"] == second["embedding_backend_batches"] == 0
    assert first["database_sha256"] == second["database_sha256"]
    assert first["policy_fingerprint"] == second["policy_fingerprint"] == frozen["fingerprint"]
    assert runtime_settings.db_path.read_bytes() == before
    assert len(fetch_order("A06", runtime_settings.db_path).order.items) == 2
    with closing(connect_readonly(runtime_settings.db_path)) as connection:
        assert connection.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 12
        assert connection.execute("SELECT COUNT(*) FROM order_items").fetchone()[0] == 14
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            connection.execute("DELETE FROM orders")


def test_startup_rejects_modified_orders_instead_of_overwriting(runtime_settings, tmp_path):
    directory = tmp_path / "chroma"
    prepare_runtime(runtime_settings, index_directory=directory)
    with sqlite3.connect(runtime_settings.db_path) as connection:
        connection.execute("UPDATE orders SET card_brand='modified' WHERE order_id='A01'")
    before = runtime_settings.db_path.read_bytes()
    with pytest.raises(ValueError, match="Seed data mismatch"):
        prepare_runtime(runtime_settings, index_directory=directory)
    assert runtime_settings.db_path.read_bytes() == before


@pytest.mark.parametrize("damage", ["vectors", "model"])
def test_startup_rejects_invalid_policy_bundle(runtime_settings, tmp_path, damage):
    source = tmp_path / "artifacts"
    shutil.copytree(ARTIFACTS, source)
    if damage == "vectors":
        with (source / "embeddings.jsonl").open("ab") as stream:
            stream.write(b" ")
    else:
        runtime_settings.openai_embedding_model = "wrong-model"
    directory = tmp_path / "chroma"
    with pytest.raises(ValueError, match="Frozen vector"):
        prepare_runtime(runtime_settings, index_directory=directory, artifact_directory=source)
    assert not (directory / "index_manifest.json").exists()


@pytest.fixture
def server_entry(tmp_path, monkeypatch):
    static = tmp_path / "static"
    (static / "assets").mkdir(parents=True)
    (static / "index.html").write_text("<html>built UI</html>", encoding="utf-8")
    monkeypatch.setattr(start, "STATIC_DIR", static)
    monkeypatch.setattr(start, "FRONTEND_DIST", tmp_path / "missing-frontend")
    monkeypatch.setattr("sys.argv", ["start"])
    monkeypatch.setenv("PORT", "8123")
    return static


def test_entrypoint_prepares_before_serving_and_honors_port(server_entry, monkeypatch):
    calls = []
    monkeypatch.setattr(start, "prepare_runtime", lambda _: calls.append("ready") or {})
    monkeypatch.setattr(start.os, "execv", lambda executable, args: calls.append(args))
    start.main()
    assert calls[0] == "ready"
    assert calls[1][1:] == [
        "-m",
        "uvicorn",
        "app.main:app",
        "--host",
        "0.0.0.0",
        "--port",
        "8123",
        "--workers",
        "1",
    ]


def test_invalid_data_never_starts_http_server(server_entry, monkeypatch):
    execute = Mock()
    monkeypatch.setattr(start.os, "execv", execute)
    monkeypatch.setattr(start, "prepare_runtime", Mock(side_effect=ValueError("Invalid data")))
    with pytest.raises(ValueError, match="Invalid data"):
        start.main()
    execute.assert_not_called()


@pytest.mark.parametrize("port", ["invalid", "0", "65536"])
def test_invalid_port_does_not_prepare_or_serve(server_entry, monkeypatch, port):
    prepare = Mock()
    execute = Mock()
    monkeypatch.setenv("PORT", port)
    monkeypatch.setattr(start, "prepare_runtime", prepare)
    monkeypatch.setattr(start.os, "execv", execute)
    with pytest.raises(SystemExit) as error:
        start.main()
    assert error.value.code == 2
    prepare.assert_not_called()
    execute.assert_not_called()


def test_missing_ui_does_not_prepare_or_serve(server_entry, monkeypatch):
    (server_entry / "index.html").unlink()
    prepare = Mock()
    execute = Mock()
    monkeypatch.setattr(start, "prepare_runtime", prepare)
    monkeypatch.setattr(start.os, "execv", execute)
    with pytest.raises(SystemExit) as error:
        start.main()
    assert error.value.code == 2
    prepare.assert_not_called()
    execute.assert_not_called()


def test_build_can_prepare_without_static_ui(server_entry, monkeypatch, capsys):
    (server_entry / "index.html").unlink()
    prepare = Mock(return_value={"policy_chunks": 11, "embedding_backend_batches": 0})
    execute = Mock()
    monkeypatch.setattr("sys.argv", ["start", "--prepare-only"])
    monkeypatch.setattr(start, "prepare_runtime", prepare)
    monkeypatch.setattr(start.os, "execv", execute)
    start.main()
    prepare.assert_called_once()
    execute.assert_not_called()
    assert "Runtime ready:" in capsys.readouterr().out
