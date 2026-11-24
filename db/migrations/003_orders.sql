-- 003 Checkout: an optional idempotency key per customer, so a retried "Place order" never creates a second order.

ALTER TABLE shop.orders ADD COLUMN idempotency_key text CHECK (length(idempotency_key) BETWEEN 8 AND 100);
ALTER TABLE shop.orders ADD CONSTRAINT orders_idempotency UNIQUE (customer_id, idempotency_key);
COMMENT ON COLUMN shop.orders.idempotency_key IS 'Client-generated key; the same key from the same customer returns the original order';

CREATE INDEX orders_customer ON shop.orders (customer_id, created_at DESC);
