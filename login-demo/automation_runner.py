"""Local schedule runner. Every execution carries an explicit workspace ID."""

import asyncio
import json
import os
import time
import uuid
from datetime import datetime, time as clock_time, timedelta, timezone
from zoneinfo import ZoneInfo

from chat_store import ChatStore
from database import connection
from model_gateway import SKILLS, ModelError, stream_model
from tenancy import TenantContext
from tavily_service import tavily_lookup


def local_timezone():
    try:
        return ZoneInfo(os.getenv('WORKROOM_TIMEZONE', 'America/Mazatlan'))
    except Exception:
        return datetime.now().astimezone().tzinfo


def next_run_for(frequency: str, time_of_day: str, weekday: int, after: datetime | None = None) -> str:
    after = after or datetime.now(timezone.utc)
    if after.tzinfo is None:
        after = after.replace(tzinfo=timezone.utc)
    zone = local_timezone()
    local = after.astimezone(zone)
    hour, minute = map(int, time_of_day.split(':'))
    candidate = datetime.combine(local.date(), clock_time(hour, minute), tzinfo=zone)
    if candidate <= local:
        candidate += timedelta(days=1)
    if frequency == 'weekdays':
        while candidate.weekday() >= 5:
            candidate += timedelta(days=1)
    elif frequency == 'weekly':
        while candidate.weekday() != weekday:
            candidate += timedelta(days=1)
    return candidate.astimezone(timezone.utc).isoformat(timespec='seconds')


def _workspace_context(path, wid, company_id):
    with connection(path) as conn:
        company = conn.execute('SELECT name,industry,products,target_region FROM companies WHERE workspace_id=? AND id=?', (wid,company_id)).fetchone()
        customers = conn.execute('SELECT name,contact,country,tier,buyer_type,main_category FROM customers WHERE workspace_id=? AND company_id=? ORDER BY updated_at DESC LIMIT 30', (wid,company_id)).fetchall()
        memory = conn.execute('SELECT content FROM workspace_memory WHERE workspace_id=?', (wid,)).fetchone()
        orders = conn.execute("SELECT status,count(*) AS count FROM orders WHERE workspace_id=? AND company_id=? GROUP BY status", (wid,company_id)).fetchall()
    return {
        'company': dict(company) if company else {},
        'customers': [dict(row) for row in customers],
        'memory_notes': memory['content'] if memory else '',
        'order_summary': [dict(row) for row in orders],
    }


def _execute(app, wid, company_id, automation_id):
    path = app.state.db_path
    with connection(path) as conn:
        automation = conn.execute('SELECT * FROM automations WHERE id=? AND workspace_id=? AND company_id=?', (automation_id, wid, company_id)).fetchone()
        settings = conn.execute('SELECT * FROM model_settings WHERE workspace_id=?', (wid,)).fetchone()
    if automation is None:
        return {'status': 'error', 'output': '', 'error': '任务不存在。'}
    automation = dict(automation)
    if settings is None or not settings['api_key_encrypted']:
        return {'status': 'error', 'output': '', 'error': '尚未配置模型 API Key。'}
    try:
        key = app.state.secret_store.decrypt(wid, settings['api_key_encrypted'])
        instruction = SKILLS[automation['skill_id']][1] if automation['skill_id'] in SKILLS else app.state.skill_catalog.instruction(automation['skill_id'])
    except (ValueError, KeyError) as exc:
        return {'status': 'error', 'output': '', 'error': str(exc)}
    context = _workspace_context(path, wid, company_id)
    system = '你在执行公司空间内已安排的文本任务。不得声称执行了未执行的工具、发送或联网检查。\n'
    system += instruction + '\n以下业务背景只属于当前公司空间：\n' + json.dumps(context, ensure_ascii=False)

    async def collect():
        research = await tavily_lookup(app, wid, automation['prompt'])
        if research['sources']:
            system_with_research = system + '\n本轮联网搜索资料及来源：\n' + json.dumps(research, ensure_ascii=False)
        else:
            system_with_research = system + '\n本轮未取得联网搜索结果（' + research['error'] + '）；不得声称已经查询最新网页。'
        chunks = []
        async for chunk in stream_model(settings, key, [
            {'role': 'system', 'content': system_with_research},
            {'role': 'user', 'content': automation['prompt']},
        ], app.state.model_transport):
            chunks.append(chunk)
        return ''.join(chunks)
    try:
        output = asyncio.run(collect())
        return {'status': 'success', 'output': output, 'error': ''}
    except (ModelError, OSError) as exc:
        return {'status': 'error', 'output': '', 'error': str(exc)}
    except Exception:
        return {'status': 'error', 'output': '', 'error': '自动任务暂时无法完成。'}


def _record_result(path, wid, company_id, automation_id, started, result):
    finished = datetime.now(timezone.utc).isoformat(timespec='seconds')
    with connection(path) as conn:
        conn.execute('BEGIN IMMEDIATE')
        cursor = conn.execute('''
            INSERT INTO automation_runs(workspace_id,automation_id,status,output,error,started_at,finished_at)
            VALUES (?,?,?,?,?,?,?)
        ''', (wid, automation_id, result['status'], result['output'], result['error'], started, finished))
        conn.execute('UPDATE automations SET last_run_at=?,lease_token=\'\',lease_until=0,updated_at=? WHERE id=? AND workspace_id=? AND company_id=?', (finished, finished, automation_id, wid, company_id))
        row = conn.execute('SELECT * FROM automation_runs WHERE id=? AND workspace_id=?', (cursor.lastrowid, wid)).fetchone()
    return dict(row)


def run_due_automations(app, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    now_iso = now.astimezone(timezone.utc).isoformat(timespec='seconds')
    path = app.state.db_path
    claimed = []
    with connection(path) as conn:
        conn.execute('BEGIN IMMEDIATE')
        rows = conn.execute('SELECT * FROM automations WHERE enabled=1 AND next_run_at<=? AND lease_until<?', (now_iso, time.time())).fetchall()
        for row in rows:
            token = uuid.uuid4().hex
            next_run = next_run_for(row['frequency'], row['time_of_day'], row['weekday'], now)
            conn.execute('UPDATE automations SET lease_token=?,lease_until=?,next_run_at=? WHERE id=? AND workspace_id=?', (token, time.time() + 300, next_run, row['id'], row['workspace_id']))
            claimed.append(dict(row))
    for task in claimed:
        started = now.isoformat(timespec='seconds')
        _record_result(path, task['workspace_id'], task['company_id'], task['id'], started, _execute(app, task['workspace_id'], task['company_id'], task['id']))
    return {'started': len(claimed)}


def run_automation_now(app, wid, automation_id, company_id=None):
    path = app.state.db_path
    token = uuid.uuid4().hex
    with connection(path) as conn:
        conn.execute('BEGIN IMMEDIATE')
        if company_id is None:
            row = conn.execute('SELECT * FROM automations WHERE id=? AND workspace_id=?', (automation_id, wid)).fetchone()
        else:
            row = conn.execute('SELECT * FROM automations WHERE id=? AND workspace_id=? AND company_id=?', (automation_id, wid, company_id)).fetchone()
        if row is None:
            return None
        if row['lease_until'] > time.time():
            return {'busy': True}
        active_company = row['company_id']
        conn.execute('UPDATE automations SET lease_token=?,lease_until=? WHERE id=? AND workspace_id=? AND company_id=?', (token, time.time() + 300, automation_id, wid, active_company))
    started = datetime.now(timezone.utc).isoformat(timespec='seconds')
    return _record_result(path, wid, active_company, automation_id, started, _execute(app, wid, active_company, automation_id))

