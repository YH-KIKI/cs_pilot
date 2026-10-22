SELECT
    o.order_id, o.is_synthetic, o.store, o.purchase_country,
    o.ordered_at, o.payment_method, o.card_brand,
    i.item_id, i.product_name, i.product_type, i.quantity, i.status,
    i.shipped_at, i.estimated_delivery_date, i.delivered_at,
    i.tracking_number, i.last_tracking_event, i.snapshot_at,
    i.condition, i.components_complete, i.security_lock_disabled,
    i.return_requested_at
FROM orders AS o
LEFT JOIN order_items AS i ON i.order_id = o.order_id
WHERE o.order_id = ?
ORDER BY i.item_id;
