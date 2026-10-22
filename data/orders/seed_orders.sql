INSERT INTO orders
    (order_id, is_synthetic, store, purchase_country, ordered_at,
     payment_method, card_brand)
VALUES
    ('A01', 1, 'Apple KR Online Store (demo)', 'KR', '2026-10-21T09:00:00+09:00', 'card', 'Visa'),
    ('A02', 1, 'Apple KR Online Store (demo)', 'KR', '2026-10-20T09:00:00+09:00', 'card', 'Visa'),
    ('A03', 1, 'Apple KR Online Store (demo)', 'KR', '2026-10-21T09:00:00+09:00', 'card', 'Visa'),
    ('A04', 1, 'Apple KR Online Store (demo)', 'KR', '2026-10-20T09:00:00+09:00', 'card', 'MasterCard'),
    ('A05', 1, 'Apple KR Online Store (demo)', 'KR', '2026-10-01T09:00:00+09:00', 'card', 'Visa'),
    ('A06', 1, 'Apple KR Online Store (demo)', 'KR', '2026-10-15T09:00:00+09:00', 'card', 'Visa'),
    ('A07', 1, 'Apple KR Online Store (demo)', 'KR', '2026-10-05T09:00:00+09:00', 'bank_transfer', NULL),
    ('A08', 1, 'Apple KR Online Store (demo)', 'KR', '2026-10-01T09:00:00+09:00', 'card', 'Visa'),
    ('A09', 1, 'Apple KR Online Store (demo)', 'KR', '2026-10-01T09:00:00+09:00', 'card', 'Visa'),
    ('A10', 1, 'Apple KR Online Store (demo)', 'KR', '2026-10-21T09:00:00+09:00', 'other', NULL),
    ('A11', 1, 'Apple KR Online Store (demo)', 'KR', '2026-10-01T09:00:00+09:00', 'card', 'Visa'),
    ('A12', 1, 'Apple KR Online Store (demo)', 'KR', '2026-10-21T09:00:00+09:00', 'unknown', NULL);

INSERT INTO order_items
    (order_id, item_id, product_name, product_type, quantity, status,
     snapshot_at, delivered_at, condition, components_complete,
     security_lock_disabled)
VALUES
    ('A01', '01', 'iPhone (demo)', 'hardware', 1, 'processing', '2026-10-22T12:00:00+09:00', NULL, 'unknown', NULL, NULL),
    ('A02', '01', 'iPad (demo)', 'hardware', 1, 'preparing', '2026-10-22T12:00:00+09:00', NULL, 'unknown', NULL, NULL),
    ('A03', '01', 'iPhone (demo)', 'hardware', 1, 'processing', '2026-10-22T12:00:00+09:00', NULL, 'unknown', NULL, NULL),
    ('A03', '02', 'Case (demo)', 'accessory', 1, 'processing', '2026-10-22T12:00:00+09:00', NULL, 'unknown', NULL, NULL),
    ('A04', '01', 'Mac (demo)', 'hardware', 1, 'shipped', '2026-10-22T12:00:00+09:00', NULL, 'unknown', NULL, NULL),
    ('A05', '01', 'iPhone (demo)', 'hardware', 1, 'delivered', '2026-10-22T12:00:00+09:00', NULL, 'unknown', NULL, NULL),
    ('A06', '01', 'iPhone (demo)', 'hardware', 1, 'delivered', '2026-10-22T12:00:00+09:00', '2026-10-18T12:00:00+09:00', 'original', 1, 1),
    ('A06', '02', 'Case (demo)', 'accessory', 1, 'shipped', '2026-10-22T12:00:00+09:00', NULL, 'unknown', NULL, NULL),
    ('A07', '01', 'iPad (demo)', 'hardware', 1, 'delivered', '2026-10-22T12:00:00+09:00', '2026-10-12T12:00:00+09:00', 'original', 1, 1),
    ('A08', '01', 'iPad (demo)', 'hardware', 1, 'delivered', '2026-10-22T12:00:00+09:00', '2026-10-08T12:00:00+09:00', 'original', 1, 1),
    ('A09', '01', 'iPad (demo)', 'hardware', 1, 'delivered', '2026-10-22T12:00:00+09:00', '2026-10-07T12:00:00+09:00', 'original', 1, 1),
    ('A10', '01', 'AirPods (demo)', 'hardware', 1, 'received', '2026-10-22T12:00:00+09:00', NULL, 'unknown', NULL, NULL),
    ('A11', '01', 'Downloaded software (demo)', 'download', 1, 'delivered', '2026-10-22T12:00:00+09:00', '2026-10-20T12:00:00+09:00', 'unknown', NULL, NULL),
    ('A12', '01', 'iPhone (demo)', 'hardware', 1, 'unknown', '2026-10-22T12:00:00+09:00', NULL, 'unknown', NULL, NULL);

UPDATE order_items
SET shipped_at = '2026-10-21T10:00:00+09:00',
    estimated_delivery_date = '2026-10-23',
    tracking_number = 'DEMO-A04-01',
    last_tracking_event = '가상 기록: 운송 중'
WHERE order_id = 'A04' AND item_id = '01';

UPDATE order_items
SET shipped_at = '2026-10-21T11:00:00+09:00',
    estimated_delivery_date = '2026-10-23',
    tracking_number = 'DEMO-A06-02',
    last_tracking_event = '가상 기록: 운송 중'
WHERE order_id = 'A06' AND item_id = '02';
