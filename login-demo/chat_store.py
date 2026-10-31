"""Tenant-bound conversations, model configuration, memory, and turn leases."""

import time
import uuid

from fastapi import HTTPException

from business import WorkspaceStore
from database import connection


class ChatStore(WorkspaceStore):
    def model_settings(self):
        with connection(self.path) as conn:
            row = conn.execute("SELECT * FROM model_settings WHERE workspace_id = ?", (self.workspace_id,)).fetchone()
        return dict(row) if row else {"provider": "deepseek", "model": "deepseek-chat", "api_key_encrypted": ""}

    def save_settings(self, values):
        current = self.model_settings()
        current.update(values)
        with connection(self.path) as conn:
            conn.execute("""
                INSERT INTO model_settings(workspace_id,provider,model,api_key_encrypted) VALUES (?,?,?,?)
                ON CONFLICT(workspace_id) DO UPDATE SET provider=excluded.provider,model=excluded.model,api_key_encrypted=excluded.api_key_encrypted
            """, (self.workspace_id, current['provider'], current['model'], current['api_key_encrypted']))
        return current

    def memory(self):
        with connection(self.path) as conn:
            row = conn.execute("SELECT content FROM workspace_memory WHERE workspace_id = ?", (self.workspace_id,)).fetchone()
        return {"content": row['content'] if row else ''}

    def save_memory(self, content):
        with connection(self.path) as conn:
            conn.execute("INSERT INTO workspace_memory(workspace_id,content) VALUES (?,?) ON CONFLICT(workspace_id) DO UPDATE SET content=excluded.content", (self.workspace_id, content))
        return {"content": content}

    def conversations(self):
        with connection(self.path) as conn:
            rows = conn.execute("SELECT id, title, customer_id, created_at, updated_at FROM conversations WHERE workspace_id = ? AND company_id = ? ORDER BY updated_at DESC, id DESC LIMIT 100", (self.workspace_id, self.company_id)).fetchall()
        return [dict(row) for row in rows]

    def create_conversation(self, title, customer_id=None):
        with connection(self.path) as conn:
            if customer_id is not None and conn.execute("SELECT 1 FROM customers WHERE id=? AND workspace_id=? AND company_id=?", (customer_id, self.workspace_id, self.company_id)).fetchone() is None:
                raise HTTPException(404, 'Customer not found')
            cursor = conn.execute("INSERT INTO conversations(workspace_id, company_id, title, customer_id) VALUES (?,?,?,?)", (self.workspace_id, self.company_id, title, customer_id))
            cid = cursor.lastrowid
        return self.conversation(cid)

    def conversation(self, cid):
        with connection(self.path) as conn:
            row = conn.execute("SELECT id,title,customer_id,created_at,updated_at FROM conversations WHERE id=? AND workspace_id=? AND company_id=?", (cid, self.workspace_id, self.company_id)).fetchone()
            if row is None:
                raise HTTPException(404, 'Conversation not found')
            messages = conn.execute("SELECT id,role,content,status,skill_id,created_at FROM messages WHERE conversation_id=? AND workspace_id=? ORDER BY id", (cid, self.workspace_id)).fetchall()
        return {**dict(row), "messages": [dict(message) for message in messages]}

    def delete_conversation(self, cid):
        with connection(self.path) as conn:
            conn.execute('BEGIN IMMEDIATE')
            row = conn.execute("SELECT busy_until FROM conversations WHERE id=? AND workspace_id=? AND company_id=?", (cid, self.workspace_id, self.company_id)).fetchone()
            if row is None:
                raise HTTPException(404, 'Conversation not found')
            if row['busy_until'] > time.time():
                raise HTTPException(409, '请先停止当前回复，再删除对话。')
            conn.execute("DELETE FROM conversations WHERE id=? AND workspace_id=? AND company_id=?", (cid, self.workspace_id, self.company_id))

    def claim_turn(self, cid, content, skill_id):
        token = uuid.uuid4().hex
        with connection(self.path) as conn:
            conn.execute('BEGIN IMMEDIATE')
            row = conn.execute("SELECT busy_until,title FROM conversations WHERE id=? AND workspace_id=? AND company_id=?", (cid, self.workspace_id, self.company_id)).fetchone()
            if row is None:
                raise HTTPException(404, 'Conversation not found')
            if row['busy_until'] > time.time():
                raise HTTPException(409, '这段对话正在生成回复，请稍候或停止后重试。')
            conn.execute("UPDATE messages SET status='error' WHERE conversation_id=? AND workspace_id=? AND status='streaming'", (cid, self.workspace_id))
            title = content[:40] if row['title'] == '新对话' else row['title']
            conn.execute("UPDATE conversations SET busy_token=?,busy_until=?,title=?,updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=? AND workspace_id=? AND company_id=?", (token, time.time()+240, title, cid, self.workspace_id, self.company_id))
            conn.execute("INSERT INTO messages(workspace_id,conversation_id,turn_token,role,content,skill_id) VALUES (?,?,?,'user',?,?)", (self.workspace_id, cid, token, content, skill_id))
            cursor = conn.execute("INSERT INTO messages(workspace_id,conversation_id,turn_token,role,status,skill_id) VALUES (?,?,?,'assistant','streaming',?)", (self.workspace_id, cid, token, skill_id))
        return token, cursor.lastrowid

    def finish_turn(self, cid, token, message_id, content, status):
        with connection(self.path) as conn:
            conn.execute("UPDATE messages SET content=?,status=CASE WHEN status='cancelled' THEN 'cancelled' ELSE ? END WHERE id=? AND workspace_id=? AND conversation_id=? AND turn_token=? AND status IN ('streaming','cancelled')", (content, status, message_id, self.workspace_id, cid, token))
            conn.execute("UPDATE conversations SET busy_token='',busy_until=0,updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=? AND workspace_id=? AND company_id=? AND busy_token=?", (cid, self.workspace_id, self.company_id, token))

    def cancel_turn(self, cid):
        self.conversation(cid)
        with connection(self.path) as conn:
            conn.execute("UPDATE messages SET status='cancelled' WHERE conversation_id=? AND workspace_id=? AND status='streaming'", (cid, self.workspace_id))
            conn.execute("UPDATE conversations SET busy_until=0,busy_token='' WHERE id=? AND workspace_id=? AND company_id=?", (cid, self.workspace_id, self.company_id))

    def turn_active(self, cid, token):
        with connection(self.path) as conn:
            return conn.execute("SELECT 1 FROM conversations WHERE id=? AND workspace_id=? AND company_id=? AND busy_token=?", (cid, self.workspace_id, self.company_id, token)).fetchone() is not None

