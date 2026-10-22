"""Build a deterministic demo DB, or verify an existing one without modifying it."""

import argparse
import hashlib
import json
import os
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path

from app.config import ROOT
from app.repositories.orders import connect_readonly, fetch_order
from app.schemas import OrderFound

SOURCE = ROOT / "data/orders"


def manifest() -> dict:
    value = json.loads((SOURCE / "manifest.json").read_text(encoding="utf-8"))
    for name, expected in value["files"].items():
        if hashlib.sha256((SOURCE / name).read_bytes()).hexdigest() != expected:
            raise ValueError(f"Seed source checksum mismatch: {name}")
    return value


def initialize(connection: sqlite3.Connection, version: int) -> None:
    connection.execute("PRAGMA foreign_keys = ON")
    if connection.execute("PRAGMA foreign_keys").fetchone()[0] != 1:
        raise ValueError("Foreign key enforcement unavailable")
    script = "BEGIN;\n" + (SOURCE / "schema.sql").read_text(encoding="utf-8")
    script += "\n" + (SOURCE / "seed_orders.sql").read_text(encoding="utf-8")
    try:
        connection.executescript(script)
        connection.execute(f"PRAGMA user_version = {int(version)}")
        validate_integrity(connection)
        connection.commit()
    except Exception:
        connection.rollback()
        raise


def validate_integrity(connection: sqlite3.Connection) -> None:
    if connection.execute("PRAGMA foreign_key_check").fetchall():
        raise ValueError("Foreign key check failed")
    if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
        raise ValueError("Integrity check failed")
    missing = connection.execute(
        "SELECT o.order_id FROM orders o LEFT JOIN order_items i "
        "ON o.order_id=i.order_id WHERE i.item_id IS NULL"
    ).fetchall()
    if missing:
        raise ValueError("Order without items")


def logical_digest(connection: sqlite3.Connection) -> str:
    tables = {
        "orders": [
            tuple(row) for row in connection.execute("SELECT * FROM orders ORDER BY order_id")
        ],
        "order_items": [
            tuple(row)
            for row in connection.execute("SELECT * FROM order_items ORDER BY order_id, item_id")
        ],
        "schema": [
            tuple(row)
            for row in connection.execute(
                "SELECT name, sql FROM sqlite_master WHERE type='table' ORDER BY name"
            )
        ],
    }
    return hashlib.sha256(json.dumps(tables, ensure_ascii=False).encode("utf-8")).hexdigest()


def verify_database(db_path: Path) -> str:
    expected = manifest()
    with closing(sqlite3.connect(":memory:")) as reference:
        initialize(reference, expected["schema_version"])
        expected_digest = logical_digest(reference)
    with closing(connect_readonly(db_path)) as connection:
        validate_integrity(connection)
        if connection.execute("PRAGMA user_version").fetchone()[0] != expected["schema_version"]:
            raise ValueError("Schema version mismatch")
        for table, count in expected["counts"].items():
            if table not in ("orders", "order_items"):
                raise ValueError("Unexpected table in manifest")
            if connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] != count:
                raise ValueError(f"Row count mismatch: {table}")
        actual_digest = logical_digest(connection)
        if actual_digest != expected_digest:
            raise ValueError("Seed data mismatch; existing DB was not overwritten")
        order_ids = [row[0] for row in connection.execute("SELECT order_id FROM orders")]
    # Pydantic checks dates, status values, nullable flags and the API mapping.
    for order_id in order_ids:
        if not isinstance(fetch_order(order_id, db_path), OrderFound):
            raise ValueError(f"Invalid order fixture: {order_id}")
    return actual_digest


def build_database(db_path: Path, *, verify_only: bool = False) -> str:
    db_path = db_path.resolve()
    if db_path.exists() or verify_only:
        return verify_database(db_path)
    # Only create new generated data under this checkout or the OS temp directory.
    allowed_roots = (ROOT / "data/runtime", Path(tempfile.gettempdir()).resolve())
    if not any(db_path.is_relative_to(base) for base in allowed_roots):
        raise ValueError("New DB must be under data/runtime or the OS temporary directory")
    expected = manifest()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    handle, temp_name = tempfile.mkstemp(suffix=".sqlite3.tmp", dir=db_path.parent)
    os.close(handle)
    temporary = Path(temp_name)
    try:
        with closing(sqlite3.connect(temporary)) as connection:
            initialize(connection, expected["schema_version"])
        digest = verify_database(temporary)
        # The initializer runs once before workers. Never replace an existing DB.
        if db_path.exists():
            raise FileExistsError(db_path)
        temporary.rename(db_path)
        return digest
    finally:
        temporary.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=ROOT / "data/runtime/orders.sqlite3")
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    digest = build_database(args.db, verify_only=args.verify_only)
    print(f"Demo DB ready: 12 orders / 14 items; logical SHA256={digest}")


if __name__ == "__main__":
    main()
