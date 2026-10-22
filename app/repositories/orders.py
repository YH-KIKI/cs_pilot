import sqlite3
from pathlib import Path

from app.config import ROOT
from app.schemas import Order, OrderError, OrderFound, OrderLookupResult, OrderNotFound

LOOKUP_SQL = (ROOT / "data/orders/lookup_order.sql").read_text(encoding="utf-8")


def connect_readonly(db_path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(db_path.resolve().as_uri() + "?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def fetch_order(order_id: str, db_path: Path) -> OrderLookupResult:
    connection = None
    try:
        connection = connect_readonly(db_path)
        rows = connection.execute(LOOKUP_SQL, (order_id,)).fetchall()
        if not rows:
            return OrderNotFound(order_id=order_id)
        if any(row["item_id"] is None for row in rows):
            raise ValueError("Order has no items")
        order_fields = (
            "order_id",
            "is_synthetic",
            "store",
            "purchase_country",
            "ordered_at",
            "payment_method",
            "card_brand",
        )
        header = {key: rows[0][key] for key in order_fields}
        header["is_synthetic"] = bool(header["is_synthetic"])
        header["items"] = [
            {key: row[key] for key in row.keys() if key not in order_fields} for row in rows
        ]
        order = Order.model_validate(header)
        return OrderFound(order=order, snapshot_at=min(item.snapshot_at for item in order.items))
    except (sqlite3.Error, ValueError):
        return OrderError(message="가상 주문 DB를 조회할 수 없습니다. 서버 상태를 확인해 주세요.")
    finally:
        if connection is not None:
            connection.close()
