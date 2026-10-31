TABLES = [
    """CREATE TABLE IF NOT EXISTS research_settings (
        workspace_id INTEGER PRIMARY KEY REFERENCES workspaces(id) ON DELETE CASCADE,
        api_key_encrypted TEXT NOT NULL DEFAULT ''
    )""",
    """CREATE TABLE IF NOT EXISTS research_reports (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        workspace_id INTEGER NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
        customer_id INTEGER REFERENCES customers(id) ON DELETE SET NULL,
        query TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'success' CHECK(status IN ('success','error')),
        answer TEXT NOT NULL DEFAULT '',
        sources TEXT NOT NULL DEFAULT '[]',
        error TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
        UNIQUE(id,workspace_id)
    )""",
    """CREATE TABLE IF NOT EXISTS automations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        workspace_id INTEGER NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
        name TEXT NOT NULL,
        prompt TEXT NOT NULL,
        skill_id TEXT NOT NULL,
        frequency TEXT NOT NULL CHECK(frequency IN ('daily','weekdays','weekly')),
        time_of_day TEXT NOT NULL,
        weekday INTEGER NOT NULL DEFAULT 0 CHECK(weekday BETWEEN 0 AND 6),
        enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0,1)),
        next_run_at TEXT NOT NULL,
        last_run_at TEXT NOT NULL DEFAULT '',
        lease_token TEXT NOT NULL DEFAULT '',
        lease_until REAL NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
        updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
        UNIQUE(id,workspace_id)
    )""",
    """CREATE TABLE IF NOT EXISTS automation_runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        workspace_id INTEGER NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
        automation_id INTEGER NOT NULL,
        status TEXT NOT NULL CHECK(status IN ('success','error')),
        output TEXT NOT NULL DEFAULT '',
        error TEXT NOT NULL DEFAULT '',
        started_at TEXT NOT NULL,
        finished_at TEXT NOT NULL,
        FOREIGN KEY(automation_id,workspace_id) REFERENCES automations(id,workspace_id) ON DELETE CASCADE
    )""",
    "CREATE INDEX IF NOT EXISTS idx_research_workspace ON research_reports(workspace_id,id)",
    "CREATE INDEX IF NOT EXISTS idx_automation_due ON automations(enabled,next_run_at)",
    "CREATE INDEX IF NOT EXISTS idx_automation_runs_workspace ON automation_runs(workspace_id,id)",
]
