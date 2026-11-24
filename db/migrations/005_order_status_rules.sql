-- 005 An order moves forward one step at a time; it can only be cancelled before it's packed.
-- Enforced in the database so no client (API, admin script, courier integration) can skip or reverse a step.

CREATE FUNCTION shop.check_order_status() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.status = OLD.status THEN
        RETURN NEW;
    END IF;
    IF (OLD.status, NEW.status) IN (('placed', 'paid'), ('paid', 'packed'), ('packed', 'shipped_from_blr'),
                                    ('shipped_from_blr', 'in_us_customs'), ('in_us_customs', 'out_for_delivery'),
                                    ('out_for_delivery', 'delivered'), ('placed', 'cancelled'), ('paid', 'cancelled')) THEN
        RETURN NEW;
    END IF;
    RAISE EXCEPTION 'order % cannot go from % to %', OLD.order_id, OLD.status, NEW.status
        USING ERRCODE = 'check_violation';
END $$;

CREATE TRIGGER orders_status_check BEFORE UPDATE OF status ON shop.orders
    FOR EACH ROW EXECUTE FUNCTION shop.check_order_status();
