-- 트랜잭션을 시작하기 전에 연결에서 실행한다.
PRAGMA foreign_keys = ON;

CREATE TABLE orders (
    order_id TEXT NOT NULL PRIMARY KEY,
    is_synthetic INTEGER NOT NULL DEFAULT 1 CHECK (is_synthetic = 1),
    store TEXT NOT NULL,
    purchase_country TEXT NOT NULL,
    ordered_at TEXT NOT NULL,
    payment_method TEXT NOT NULL
        CHECK (payment_method IN ('card', 'bank_transfer', 'other', 'unknown')),
    card_brand TEXT,
    CHECK (payment_method = 'card' OR card_brand IS NULL)
);

CREATE TABLE order_items (
    order_id TEXT NOT NULL,
    item_id TEXT NOT NULL,
    product_name TEXT NOT NULL,
    product_type TEXT NOT NULL,
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    status TEXT NOT NULL CHECK (status IN (
        'received', 'processing', 'preparing', 'shipped',
        'delivered', 'cancelled', 'unknown'
    )),
    shipped_at TEXT,
    estimated_delivery_date TEXT,
    delivered_at TEXT,
    tracking_number TEXT,
    last_tracking_event TEXT,
    snapshot_at TEXT NOT NULL,
    condition TEXT NOT NULL DEFAULT 'unknown'
        CHECK (condition IN ('original', 'damaged', 'other', 'unknown')),
    components_complete INTEGER CHECK (components_complete IN (0, 1)),
    security_lock_disabled INTEGER CHECK (security_lock_disabled IN (0, 1)),
    return_requested_at TEXT,
    PRIMARY KEY (order_id, item_id),
    FOREIGN KEY (order_id) REFERENCES orders(order_id)
        ON DELETE RESTRICT ON UPDATE RESTRICT
);
