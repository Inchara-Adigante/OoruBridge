-- 002 Customers must live in the metro area they choose: their ZIP code has to start with one of its prefixes.

ALTER TABLE shop.destinations ADD COLUMN zip_prefixes text[] NOT NULL DEFAULT '{}';
COMMENT ON COLUMN shop.destinations.zip_prefixes IS 'First three digits of the ZIP codes we deliver to in this metro area';

CREATE FUNCTION shop.check_customer_zip() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    prefixes text[];
BEGIN
    SELECT zip_prefixes INTO prefixes FROM shop.destinations WHERE code = NEW.destination;
    IF NOT left(NEW.zip, 3) = ANY (prefixes) THEN
        RAISE EXCEPTION 'ZIP % is outside the % delivery area', NEW.zip, NEW.destination
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER customers_zip_check BEFORE INSERT OR UPDATE OF zip, destination ON shop.customers
    FOR EACH ROW EXECUTE FUNCTION shop.check_customer_zip();
