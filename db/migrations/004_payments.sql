-- 004 Payments reported by the payment provider's webhook.
-- The provider may send the same event more than once; provider_ref is unique, so it's recorded only once.

CREATE TYPE shop.payment_status AS ENUM ('succeeded', 'failed');

CREATE TABLE shop.payments (
    payment_id    bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    order_id      bigint              NOT NULL REFERENCES shop.orders,
    provider_ref  text                NOT NULL UNIQUE,
    amount_usd    numeric(10,2)       NOT NULL CHECK (amount_usd >= 0),
    status        shop.payment_status NOT NULL,
    needs_refund  boolean             NOT NULL DEFAULT false,
    received_at   timestamptz         NOT NULL DEFAULT now()
);
COMMENT ON TABLE  shop.payments IS 'One row per payment event from the provider (duplicates are ignored by provider_ref)';
COMMENT ON COLUMN shop.payments.needs_refund IS 'Money arrived for an order that was cancelled or already paid; finance must return it';
CREATE INDEX payments_order ON shop.payments (order_id);

-- At most one successful payment counts towards an order.
CREATE UNIQUE INDEX payments_one_success ON shop.payments (order_id) WHERE status = 'succeeded' AND NOT needs_refund;
