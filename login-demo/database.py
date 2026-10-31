"""Standalone database and transactional, idempotent workspace migration."""

import sqlite3
from contextlib import contextmanager
from pathlib import Path

from operations_schema import TABLES
from platform_schema import TABLES as PLATFORM_TABLES


@contextmanager
def connection(path: Path):
    conn = sqlite3.connect(path, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def create_default_workspace(conn: sqlite3.Connection, user_id: int) -> None:
    cursor = conn.execute(
        "INSERT INTO workspaces(owner_user_id, name) VALUES (?, ?)",
        (user_id, "我的公司"),
    )
    conn.execute(
        "INSERT INTO companies(workspace_id, name) VALUES (?, ?)",
        (cursor.lastrowid, "我的公司"),
    )


def _ensure_multiple_companies(path: Path) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.execute('CREATE TABLE IF NOT EXISTS schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
        done = conn.execute("SELECT 1 FROM schema_meta WHERE key='multiple_companies_v1'").fetchone()
        companies = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='companies'").fetchone()
        if done or not companies:
            conn.commit()
            return
        conn.commit()
        conn.execute('PRAGMA foreign_keys=OFF')
        conn.execute('PRAGMA legacy_alter_table=ON')
        conn.execute('BEGIN IMMEDIATE')
        conn.execute("""
            CREATE TABLE companies_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                workspace_id INTEGER NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
                name TEXT NOT NULL,
                website TEXT NOT NULL DEFAULT '',
                contact_name TEXT NOT NULL DEFAULT '',
                contact_email TEXT NOT NULL DEFAULT '',
                address TEXT NOT NULL DEFAULT '',
                industry TEXT NOT NULL DEFAULT '',
                products TEXT NOT NULL DEFAULT '',
                target_region TEXT NOT NULL DEFAULT '',
                agent_identity_md TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
            )
        """)
        conn.execute("""
            INSERT INTO companies_new
            (id,workspace_id,name,website,contact_name,contact_email,address,industry,products,target_region,agent_identity_md,updated_at)
            SELECT id,workspace_id,name,website,contact_name,contact_email,address,industry,products,target_region,agent_identity_md,updated_at
            FROM companies
        """)
        conn.execute('DROP TABLE companies')
        conn.execute('ALTER TABLE companies_new RENAME TO companies')
        conn.execute('CREATE UNIQUE INDEX idx_company_workspace ON companies(id,workspace_id)')
        conn.execute("INSERT OR REPLACE INTO schema_meta(key,value) VALUES ('multiple_companies_v1','1')")
        conn.commit()
        conn.execute('PRAGMA foreign_keys=ON')
        violations = conn.execute('PRAGMA foreign_key_check').fetchall()
        if violations:
            raise RuntimeError(f'companies migration foreign key violations: {violations[:3]}')
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
def migrate(path: Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    _ensure_multiple_companies(path)
    with connection(path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT NOT NULL COLLATE NOCASE UNIQUE,
                salt TEXT NOT NULL,
                password_hash TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS workspaces (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                owner_user_id INTEGER NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
                name TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS companies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                workspace_id INTEGER NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
                name TEXT NOT NULL,
                website TEXT NOT NULL DEFAULT '',
                contact_name TEXT NOT NULL DEFAULT '',
                contact_email TEXT NOT NULL DEFAULT '',
                address TEXT NOT NULL DEFAULT '',
                industry TEXT NOT NULL DEFAULT '',
                products TEXT NOT NULL DEFAULT '',
                target_region TEXT NOT NULL DEFAULT '',
                agent_identity_md TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
            )
        """)
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_company_workspace ON companies(id, workspace_id)")
        conn.execute("INSERT OR REPLACE INTO schema_meta(key,value) VALUES ('multiple_companies_v1','1')")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS customers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                workspace_id INTEGER NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
                company_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                contact TEXT NOT NULL DEFAULT '',
                note TEXT NOT NULL DEFAULT '',
                country TEXT NOT NULL DEFAULT '',
                tier TEXT NOT NULL DEFAULT '' CHECK(tier IN ('', 'A', 'B', 'C')),
                linkedin_url TEXT NOT NULL DEFAULT '',
                company_website TEXT NOT NULL DEFAULT '',
                social_media TEXT NOT NULL DEFAULT '{}',
                title TEXT NOT NULL DEFAULT '',
                email TEXT NOT NULL DEFAULT '',
                backup_email TEXT NOT NULL DEFAULT '',
                phone TEXT NOT NULL DEFAULT '',
                whatsapp TEXT NOT NULL DEFAULT '',
                wechat TEXT NOT NULL DEFAULT '',
                source TEXT NOT NULL DEFAULT 'manual',
                buyer_type TEXT NOT NULL DEFAULT '',
                follow_up_note TEXT NOT NULL DEFAULT '',
                main_category TEXT NOT NULL DEFAULT '',
                match_score INTEGER NOT NULL DEFAULT 0 CHECK(match_score BETWEEN 0 AND 5),
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
                updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
                FOREIGN KEY(company_id, workspace_id) REFERENCES companies(id, workspace_id) ON DELETE CASCADE
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_customers_workspace ON customers(workspace_id, id)")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS model_settings (
                workspace_id INTEGER PRIMARY KEY REFERENCES workspaces(id) ON DELETE CASCADE,
                provider TEXT NOT NULL DEFAULT 'deepseek',
                model TEXT NOT NULL DEFAULT 'deepseek-chat',
                api_key_encrypted TEXT NOT NULL DEFAULT ''
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                workspace_id INTEGER NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
                company_id INTEGER NOT NULL,
                customer_id INTEGER REFERENCES customers(id) ON DELETE SET NULL,
                title TEXT NOT NULL DEFAULT '新对话',
                busy_token TEXT NOT NULL DEFAULT '',
                busy_until REAL NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
                updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
                UNIQUE(id, workspace_id)
            )
        """)
        conn.execute("""
            CREATE TRIGGER IF NOT EXISTS conversation_customer_workspace
            BEFORE INSERT ON conversations
            WHEN NEW.customer_id IS NOT NULL AND NOT EXISTS (
                SELECT 1 FROM customers WHERE id = NEW.customer_id AND workspace_id = NEW.workspace_id
            )
            BEGIN SELECT RAISE(ABORT, 'Customer belongs to another workspace'); END
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                workspace_id INTEGER NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
                conversation_id INTEGER NOT NULL,
                turn_token TEXT NOT NULL,
                role TEXT NOT NULL CHECK(role IN ('user','assistant')),
                content TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'complete' CHECK(status IN ('complete','streaming','error','cancelled')),
                skill_id TEXT NOT NULL DEFAULT 'general',
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
                FOREIGN KEY(conversation_id,workspace_id) REFERENCES conversations(id,workspace_id) ON DELETE CASCADE,
                UNIQUE(turn_token,role)
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_conversations_workspace ON conversations(workspace_id, updated_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages(workspace_id, conversation_id, id)")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS workspace_memory (
                workspace_id INTEGER PRIMARY KEY REFERENCES workspaces(id) ON DELETE CASCADE,
                content TEXT NOT NULL DEFAULT ''
            )
        """)
        for statement in TABLES:
            conn.execute(statement)
        for statement in PLATFORM_TABLES:
            conn.execute(statement)
        for table, column, declaration in [
            ('libraries', 'root_path', "TEXT NOT NULL DEFAULT ''"),
            ('documents', 'source_path', "TEXT NOT NULL DEFAULT ''"),
            ('research_reports', 'details', "TEXT NOT NULL DEFAULT '{}'"),
            ('libraries', 'company_id', 'INTEGER'),
            ('orders', 'company_id', 'INTEGER'),
            ('conversations', 'company_id', 'INTEGER'),
            ('research_reports', 'company_id', 'INTEGER'),
            ('automations', 'company_id', 'INTEGER'),
        ]:
            columns = {row['name'] for row in conn.execute(f'PRAGMA table_info({table})').fetchall()}
            if column not in columns:
                conn.execute(f'ALTER TABLE {table} ADD COLUMN {column} {declaration}')
        for row in conn.execute('SELECT id, workspace_id FROM companies ORDER BY id').fetchall():
            conn.execute(
                'UPDATE libraries SET company_id=? WHERE workspace_id=? AND company_id IS NULL',
                (row['id'], row['workspace_id']),
            )
            conn.execute(
                'UPDATE orders SET company_id=? WHERE workspace_id=? AND company_id IS NULL',
                (row['id'], row['workspace_id']),
            )
            conn.execute(
                'UPDATE conversations SET company_id=? WHERE workspace_id=? AND company_id IS NULL',
                (row['id'], row['workspace_id']),
            )
            conn.execute(
                'UPDATE research_reports SET company_id=? WHERE workspace_id=? AND company_id IS NULL',
                (row['id'], row['workspace_id']),
            )
            conn.execute(
                'UPDATE automations SET company_id=? WHERE workspace_id=? AND company_id IS NULL',
                (row['id'], row['workspace_id']),
            )
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_documents_source ON documents(workspace_id,library_id,source_path) WHERE source_path <> ''")
        for row in conn.execute("""
            SELECT id FROM users
            WHERE NOT EXISTS (SELECT 1 FROM workspaces WHERE owner_user_id = users.id)
        """).fetchall():
            create_default_workspace(conn, row["id"])

