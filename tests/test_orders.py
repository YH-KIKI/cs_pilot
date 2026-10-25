import sqlite3
from contextlib import closing

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.repositories.orders import connect_readonly, fetch_order
from app.schemas import OrderError, OrderFound, OrderNotFound
from app.tools.orders import lookup_order
from scripts.init_orders_db import build_database, initialize, manifest, verify_database


@pytest.fixture
def demo_db(tmp_path):
    target = tmp_path / "orders.sqlite3"
    build_database(target)
    return target


def test_initialization_is_repeatable_and_deterministic(demo_db, tmp_path):
    original = demo_db.read_bytes()
    digest = build_database(demo_db)
    assert demo_db.read_bytes() == original
    assert build_database(tmp_path / "another.sqlite3") == digest


def test_seed_counts_and_parent_child_mapping(demo_db):
    with closing(connect_readonly(demo_db)) as connection:
        assert connection.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 12
        assert connection.execute("SELECT COUNT(*) FROM order_items").fetchone()[0] == 14
    result = fetch_order("A06", demo_db)
    assert isinstance(result, OrderFound)
    assert [item.status for item in result.order.items] == ["delivered", "shipped"]
    assert result.order.items[0].delivered_at is not None
    assert result.order.items[1].delivered_at is None


def test_not_found_is_distinct_from_database_error(demo_db, tmp_path):
    assert isinstance(fetch_order("A999", demo_db), OrderNotFound)
    missing = tmp_path / "missing.sqlite3"
    assert isinstance(fetch_order("A01", missing), OrderError)
    assert not missing.exists()


def test_bound_parameter_cannot_change_query(demo_db):
    assert isinstance(fetch_order("A01' OR 1=1 --", demo_db), OrderNotFound)


def test_unknown_delivery_date_is_preserved(demo_db):
    result = fetch_order("A05", demo_db)
    assert isinstance(result, OrderFound)
    assert result.order.items[0].status == "delivered"
    assert result.order.items[0].delivered_at is None


def test_runtime_connection_rejects_writes(demo_db):
    with closing(connect_readonly(demo_db)) as connection:
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            connection.execute("DELETE FROM order_items")


@pytest.mark.parametrize(
    "statement",
    [
        "INSERT INTO order_items (order_id,item_id,product_name,product_type,quantity,status,"
        "snapshot_at) VALUES ('ABSENT','01','demo','hardware',1,'unknown','2026-10-22')",
        "INSERT INTO orders SELECT * FROM orders WHERE order_id='A01'",
        "UPDATE order_items SET quantity=0 WHERE order_id='A01'",
    ],
)
def test_database_constraints(statement):
    with closing(sqlite3.connect(":memory:")) as connection:
        initialize(connection, manifest()["schema_version"])
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(statement)


def test_modified_database_is_not_silently_reseeded(demo_db):
    with closing(sqlite3.connect(demo_db)) as connection:
        connection.execute("UPDATE orders SET card_brand='Other' WHERE order_id='A01'")
        connection.commit()
    with pytest.raises(ValueError, match="Seed data mismatch"):
        verify_database(demo_db)
    with closing(sqlite3.connect(demo_db)) as connection:
        assert (
            connection.execute("SELECT card_brand FROM orders WHERE order_id='A01'").fetchone()[0]
            == "Other"
        )


def test_routes_tool_and_openapi_contract(demo_db, monkeypatch):
    from app.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("ORDERS_DB_PATH", str(demo_db))
    try:
        with TestClient(app) as client:
            assert client.get("/api/health").json()["ai_enabled"] is False
            assert client.get("/api/orders/A06").json()["kind"] == "found"
            assert client.get("/api/orders/A999").json()["kind"] == "not_found"
            assert client.get("/api/orders/invalid").status_code == 422
            assert client.get("/api/unknown").status_code == 404
            assert "openapi" in client.get("/openapi.json").json()
            assert lookup_order.invoke({"order_id": "A01"})["kind"] == "found"
    finally:
        get_settings.cache_clear()
