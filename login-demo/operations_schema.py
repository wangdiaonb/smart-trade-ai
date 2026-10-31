TABLES = [
    """CREATE TABLE IF NOT EXISTS orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        workspace_id INTEGER NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
        customer_id INTEGER NOT NULL REFERENCES customers(id),
        order_no TEXT NOT NULL DEFAULT '', currency TEXT NOT NULL DEFAULT 'USD',
        status TEXT NOT NULL DEFAULT '报价中', delivery_date TEXT NOT NULL DEFAULT '',
        payment_terms TEXT NOT NULL DEFAULT '', notes TEXT NOT NULL DEFAULT '',
        total_amount TEXT,
        created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
        updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
        UNIQUE(id,workspace_id)
    )""",
    """CREATE TABLE IF NOT EXISTS order_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        workspace_id INTEGER NOT NULL, order_id INTEGER NOT NULL, position INTEGER NOT NULL,
        product_name TEXT NOT NULL, quantity TEXT, unit TEXT NOT NULL DEFAULT '',
        unit_price TEXT, total_amount TEXT,
        FOREIGN KEY(order_id,workspace_id) REFERENCES orders(id,workspace_id) ON DELETE CASCADE
    )""",
    """CREATE TRIGGER IF NOT EXISTS order_customer_workspace BEFORE INSERT ON orders
        WHEN NOT EXISTS (SELECT 1 FROM customers WHERE id=NEW.customer_id AND workspace_id=NEW.workspace_id)
        BEGIN SELECT RAISE(ABORT,'Customer belongs to another workspace'); END""",
    """CREATE TABLE IF NOT EXISTS libraries (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        workspace_id INTEGER NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
        name TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
        UNIQUE(id,workspace_id)
    )""",
    """CREATE TABLE IF NOT EXISTS documents (
        id INTEGER PRIMARY KEY AUTOINCREMENT, workspace_id INTEGER NOT NULL,
        library_id INTEGER NOT NULL, filename TEXT NOT NULL, storage_name TEXT NOT NULL,
        size INTEGER NOT NULL, extracted_text TEXT NOT NULL DEFAULT '',
        extraction_note TEXT NOT NULL DEFAULT '', deleted INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
        FOREIGN KEY(library_id,workspace_id) REFERENCES libraries(id,workspace_id) ON DELETE CASCADE
    )""",
    """CREATE TABLE IF NOT EXISTS templates (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        workspace_id INTEGER NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
        name TEXT NOT NULL, content TEXT NOT NULL,
        updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
    )""",
    "CREATE INDEX IF NOT EXISTS idx_orders_workspace ON orders(workspace_id,id)",
    "CREATE INDEX IF NOT EXISTS idx_documents_workspace ON documents(workspace_id,library_id,deleted)",
    """CREATE TABLE IF NOT EXISTS customer_libraries (
        workspace_id INTEGER NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
        customer_id INTEGER NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
        library_id INTEGER NOT NULL REFERENCES libraries(id) ON DELETE CASCADE,
        PRIMARY KEY(customer_id,library_id)
    )""",
    "CREATE INDEX IF NOT EXISTS idx_customer_libraries_workspace ON customer_libraries(workspace_id,customer_id)",
]
