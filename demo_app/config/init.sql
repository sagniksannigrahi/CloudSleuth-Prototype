-- Demo shop database
CREATE TABLE inventory (sku TEXT PRIMARY KEY, stock INT NOT NULL);
CREATE TABLE orders    (id SERIAL PRIMARY KEY, sku TEXT, amount NUMERIC, created_at TIMESTAMPTZ DEFAULT now());
CREATE TABLE payments  (id SERIAL PRIMARY KEY, order_id INT, amount NUMERIC, created_at TIMESTAMPTZ DEFAULT now());
CREATE TABLE jobs      (id SERIAL PRIMARY KEY, order_id INT, done BOOLEAN DEFAULT FALSE);
CREATE INDEX jobs_open ON jobs (id) WHERE NOT done;
INSERT INTO inventory SELECT 'sku-' || g, 1000000 FROM generate_series(1, 20) g;
