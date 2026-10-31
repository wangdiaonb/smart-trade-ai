"""Standalone database and transactional, idempotent workspace migration."""

import sqlite3
from contextlib import contextmanager
from pathlib import Path


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


def migrate(path: Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
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
                workspace_id INTEGER NOT NULL UNIQUE REFERENCES workspaces(id) ON DELETE CASCADE,
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
        for row in conn.execute("""
            SELECT id FROM users
            WHERE NOT EXISTS (SELECT 1 FROM workspaces WHERE owner_user_id = users.id)
        """).fetchall():
            create_default_workspace(conn, row["id"])

