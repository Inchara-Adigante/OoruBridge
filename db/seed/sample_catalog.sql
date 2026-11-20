-- Sample data for development. Shop names, prices, rates and duty percentages are illustrative.

INSERT INTO shop.duty_categories (category, duty_rate, notes) VALUES
    ('sweets_snacks', 0.10, 'Packaged sweets, savouries and namkeen'),
    ('spices',        0.05, 'Spice powders and masala blends'),
    ('coffee_tea',    0.04, 'Filter coffee powder, tea'),
    ('textiles',      0.12, 'Silk sarees, cotton wear'),
    ('handicrafts',   0.04, 'Wooden toys, sandalwood and brass items'),
    ('books',         0.00, 'Printed books');

INSERT INTO shop.destinations (code, city, state, min_days, max_days, surcharge_pct) VALUES
    ('SJC', 'San Jose', 'CA', 6, 9, 0),
    ('DEN', 'Denver',   'CO', 7, 10, 8);

INSERT INTO shop.shipping_rates (max_weight_g, price_usd) VALUES
    (500, 18.00), (1000, 28.00), (2000, 42.00), (5000, 78.00), (10000, 135.00), (20000, 240.00);

INSERT INTO shop.sellers (name, area, specialty, verified, rating) VALUES
    ('Malleshwaram Sweet House',  'Malleshwaram',   'Mysore pak, chiroti and festival sweets', true, 4.7),
    ('Basavanagudi Masala Mane',  'Basavanagudi',   'Stone-ground spice powders',              true, 4.6),
    ('Chickpet Silk Centre',      'Chickpet',       'Mysore silk and Kanchipuram sarees',      true, 4.5),
    ('Gandhi Bazaar Coffee Works','Gandhi Bazaar',  'Fresh filter coffee blends',              true, 4.8),
    ('Channapatna Toy Studio',    'Jayanagar',      'Lacquered wooden toys',                   false, 4.4),
    ('Avenue Road Book Depot',    'Avenue Road',    'Kannada literature and children''s books', true, 4.3);

INSERT INTO shop.products (seller_id, name, category, description, price_inr, weight_g, shelf_life_days, stock) VALUES
    (1, 'Mysore Pak (500 g)',              'sweets_snacks', 'Ghee Mysore pak, vacuum packed',       420,  550, 30,  120),
    (1, 'Chiroti (12 pieces)',             'sweets_snacks', 'Flaky layered chiroti',                380,  400,  7,   40),
    (1, 'Kodubale (400 g)',                'sweets_snacks', 'Crispy rice-flour ring snack',          220,  420, 45,  200),
    (2, 'Bisi Bele Bath Powder (200 g)',   'spices',        'Stone-ground, no preservatives',        160,  220, 180, 300),
    (2, 'Sambar Powder (500 g)',           'spices',        'Home-style Udupi sambar blend',         240,  520, 180, 250),
    (2, 'Rasam Powder (200 g)',            'spices',        'Pepper-cumin rasam powder',             140,  220, 180, 300),
    (3, 'Mysore Silk Saree',               'textiles',      'Pure crepe silk with zari border',    14500,  700, NULL, 12),
    (3, 'Cotton Ilkal Saree',              'textiles',      'Handloom Ilkal with tope teni pallu',  3200,  600, NULL, 25),
    (4, 'Filter Coffee 80:20 (500 g)',     'coffee_tea',    '80% coffee, 20% chicory, fresh roast',  380,  520, 90,  180),
    (4, 'Steel Coffee Filter Set',         'handicrafts',   'Traditional stainless-steel decoction filter', 650, 450, NULL, 60),
    (5, 'Channapatna Train Set',           'handicrafts',   'Lacquered wooden train, safe colours',  950,  800, NULL, 35),
    (6, 'Karvalo by K. P. Poornachandra Tejaswi', 'books',  'Kannada novel, paperback',              195,  300, NULL, 40);
