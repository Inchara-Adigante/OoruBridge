-- 001 Core schema: Bengaluru sellers and products, US destinations, rate cards, and the order lifecycle.

CREATE EXTENSION IF NOT EXISTS citext;
CREATE SCHEMA IF NOT EXISTS shop;
COMMENT ON SCHEMA shop IS 'OoruBridge marketplace: Bengaluru sellers shipping to US customers';

-- ---------------------------------------------------------------- catalog
CREATE TABLE shop.duty_categories (
    category   text PRIMARY KEY,
    duty_rate  numeric(5,4) NOT NULL CHECK (duty_rate BETWEEN 0 AND 1),
    notes      text NOT NULL DEFAULT ''
);
COMMENT ON TABLE shop.duty_categories IS 'Product categories with an estimated US import duty rate (illustrative, not customs advice)';

CREATE TABLE shop.sellers (
    seller_id  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name       text    NOT NULL UNIQUE,
    area       text    NOT NULL,                       -- Bengaluru locality, e.g. Malleshwaram
    specialty  text    NOT NULL,
    verified   boolean NOT NULL DEFAULT false,
    rating     numeric(2,1) CHECK (rating BETWEEN 1 AND 5),
    joined_at  timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE shop.sellers IS 'Shops in Bengaluru that sell through OoruBridge';

CREATE TABLE shop.products (
    product_id       bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    seller_id        bigint        NOT NULL REFERENCES shop.sellers,
    name             text          NOT NULL,
    category         text          NOT NULL REFERENCES shop.duty_categories,
    description      text          NOT NULL DEFAULT '',
    price_inr        numeric(10,2) NOT NULL CHECK (price_inr > 0),
    weight_g         integer       NOT NULL CHECK (weight_g > 0),
    shelf_life_days  integer       CHECK (shelf_life_days > 0),   -- NULL = doesn't expire
    stock            integer       NOT NULL DEFAULT 0 CHECK (stock >= 0),
    active           boolean       NOT NULL DEFAULT true,
    UNIQUE (seller_id, name)
);
COMMENT ON TABLE  shop.products IS 'What sellers offer; prices are in rupees and converted to dollars at quote time';
COMMENT ON COLUMN shop.products.shelf_life_days IS 'Perishable items must outlast the delivery time; quotes warn otherwise';
CREATE INDEX products_seller ON shop.products (seller_id);
CREATE INDEX products_category ON shop.products (category) WHERE active;

-- ---------------------------------------------------------------- destinations and shipping
CREATE TABLE shop.destinations (
    code          text PRIMARY KEY CHECK (code ~ '^[A-Z]{3}$'),
    city          text    NOT NULL,
    state         char(2) NOT NULL,
    min_days      integer NOT NULL CHECK (min_days > 0),
    max_days      integer NOT NULL,
    surcharge_pct numeric(5,2) NOT NULL DEFAULT 0,
    CHECK (max_days >= min_days)
);
COMMENT ON TABLE shop.destinations IS 'US metro areas OoruBridge delivers to (launch: San Jose and Denver)';

CREATE TABLE shop.shipping_rates (
    max_weight_g  integer       PRIMARY KEY CHECK (max_weight_g > 0),
    price_usd     numeric(8,2)  NOT NULL CHECK (price_usd > 0)
);
COMMENT ON TABLE shop.shipping_rates IS 'Air courier rate card Bengaluru -> US by parcel weight; destinations add a surcharge';

-- ---------------------------------------------------------------- orders
CREATE TYPE shop.order_status AS ENUM
    ('placed', 'paid', 'packed', 'shipped_from_blr', 'in_us_customs', 'out_for_delivery', 'delivered', 'cancelled');

CREATE TABLE shop.customers (
    customer_id  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    email        citext NOT NULL UNIQUE,
    full_name    text   NOT NULL,
    destination  text   NOT NULL REFERENCES shop.destinations,
    zip          text   NOT NULL CHECK (zip ~ '^[0-9]{5}$'),
    created_at   timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE shop.orders (
    order_id        bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    customer_id     bigint            NOT NULL REFERENCES shop.customers,
    destination     text              NOT NULL REFERENCES shop.destinations,
    status          shop.order_status NOT NULL DEFAULT 'placed',
    fx_inr_per_usd  numeric(8,4)      NOT NULL CHECK (fx_inr_per_usd > 0),   -- rate frozen at checkout
    subtotal_usd    numeric(10,2)     NOT NULL,
    shipping_usd    numeric(10,2)     NOT NULL,
    duty_usd        numeric(10,2)     NOT NULL,
    service_fee_usd numeric(10,2)     NOT NULL,
    total_usd       numeric(10,2)     NOT NULL,
    created_at      timestamptz       NOT NULL DEFAULT now(),
    CHECK (total_usd = subtotal_usd + shipping_usd + duty_usd + service_fee_usd)
);

CREATE TABLE shop.order_items (
    order_id    bigint        NOT NULL REFERENCES shop.orders ON DELETE CASCADE,
    product_id  bigint        NOT NULL REFERENCES shop.products,
    quantity    integer       NOT NULL CHECK (quantity BETWEEN 1 AND 20),
    price_inr   numeric(10,2) NOT NULL,                -- frozen at checkout
    PRIMARY KEY (order_id, product_id)
);

CREATE TABLE shop.shipment_events (
    order_id     bigint            NOT NULL REFERENCES shop.orders ON DELETE CASCADE,
    status       shop.order_status NOT NULL,
    location     text              NOT NULL,
    happened_at  timestamptz       NOT NULL DEFAULT now(),
    PRIMARY KEY (order_id, status)
);
COMMENT ON TABLE shop.shipment_events IS 'Tracking timeline: Bengaluru shop -> courier hub -> US customs -> doorstep';
