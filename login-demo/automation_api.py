"""Workspace-scoped local automations and their run history."""

from datetime import datetime, timezone
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator

from automation_runner import next_run_for, run_automation_now, run_due_automations
from business_models import Name
from database import connection
from model_gateway import SKILLS
from tenancy import TenantContext, require_tenant

router = APIRouter(prefix='/api', tags=['automations'])


class AutomationInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: Name
    prompt: str = Field(min_length=1, max_length=20000, pattern=r'\S')
    skill_id: str = Field(pattern=r'^(general|outreach|followup|analysis|b2b-[a-z0-9][a-z0-9-]{0,100})$')
    frequency: Literal['daily', 'weekdays', 'weekly'] = 'daily'
    time_of_day: str = Field('09:00', pattern=r'^(?:[01]\d|2[0-3]):[0-5]\d$')
    weekday: int = Field(0, ge=0, le=6, strict=True)
    enabled: bool = True


class AutomationUpdate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: Name | None = None
    prompt: str | None = Field(None, min_length=1, max_length=20000, pattern=r'\S')
    skill_id: str | None = Field(None, pattern=r'^(general|outreach|followup|analysis|b2b-[a-z0-9][a-z0-9-]{0,100})$')
    frequency: Literal['daily', 'weekdays', 'weekly'] | None = None
    time_of_day: str | None = Field(None, pattern=r'^(?:[01]\d|2[0-3]):[0-5]\d$')
    weekday: int | None = Field(None, ge=0, le=6, strict=True)
    enabled: bool | None = None


def context(request: Request, tenant: TenantContext = Depends(require_tenant)):
    return request, tenant


Context = Annotated[tuple, Depends(context)]


def _public(row):
    result = dict(row)
    result['enabled'] = bool(result['enabled'])
    for key in ('lease_token', 'lease_until'):
        result.pop(key, None)
    return result


def _task(path, wid, company_id, task_id):
    with connection(path) as conn:
        row = conn.execute('SELECT * FROM automations WHERE id=? AND workspace_id=? AND company_id=?', (task_id, wid, company_id)).fetchone()
    if row is None:
        raise HTTPException(404, 'Automation not found')
    return _public(row)


def _validate_skill(request, skill_id):
    if skill_id not in SKILLS and not request.app.state.skill_catalog.has(skill_id):
        raise HTTPException(422, '未知或不可用的业务技能。')


@router.get('/automations')
def list_automations(context: Context):
    request, tenant = context
    with connection(request.app.state.db_path) as conn:
        rows = conn.execute('SELECT * FROM automations WHERE workspace_id=? AND company_id=? ORDER BY id DESC', (tenant.workspace_id, tenant.company_id)).fetchall()
    return [_public(row) for row in rows]


@router.post('/automations', status_code=201)
def create_automation(payload: AutomationInput, context: Context):
    request, tenant = context
    _validate_skill(request, payload.skill_id)
    next_run = next_run_for(payload.frequency, payload.time_of_day, payload.weekday)
    with connection(request.app.state.db_path) as conn:
        cursor = conn.execute('''
            INSERT INTO automations(workspace_id,company_id,name,prompt,skill_id,frequency,time_of_day,weekday,enabled,next_run_at)
            VALUES (?,?,?,?,?,?,?,?,?,?)
        ''', (tenant.workspace_id, tenant.company_id, payload.name, payload.prompt, payload.skill_id, payload.frequency, payload.time_of_day, payload.weekday, int(payload.enabled), next_run))
    return _task(request.app.state.db_path, tenant.workspace_id, tenant.company_id, cursor.lastrowid)


@router.get('/automations/{task_id}')
def get_automation(task_id: int, context: Context):
    request, tenant = context
    return _task(request.app.state.db_path, tenant.workspace_id, tenant.company_id, task_id)


@router.put('/automations/{task_id}')
def update_automation(task_id: int, payload: AutomationUpdate, context: Context):
    request, tenant = context
    current = _task(request.app.state.db_path, tenant.workspace_id, tenant.company_id, task_id)
    values = payload.model_dump(exclude_unset=True, exclude_none=True)
    if 'skill_id' in values:
        _validate_skill(request, values['skill_id'])
    merged = {**current, **values}
    values['next_run_at'] = next_run_for(merged['frequency'], merged['time_of_day'], merged['weekday'])
    values['enabled'] = int(values.get('enabled', current['enabled']))
    assignments = ','.join(f'{field}=?' for field in values)
    with connection(request.app.state.db_path) as conn:
        conn.execute(
            f"UPDATE automations SET {assignments},updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=? AND workspace_id=? AND company_id=?",
            (*values.values(), task_id, tenant.workspace_id, tenant.company_id),
        )
    return _task(request.app.state.db_path, tenant.workspace_id, tenant.company_id, task_id)


@router.delete('/automations/{task_id}')
def delete_automation(task_id: int, context: Context):
    request, tenant = context
    _task(request.app.state.db_path, tenant.workspace_id, tenant.company_id, task_id)
    with connection(request.app.state.db_path) as conn:
        conn.execute('DELETE FROM automations WHERE id=? AND workspace_id=? AND company_id=?', (task_id, tenant.workspace_id, tenant.company_id))
    return {'ok': True}


@router.post('/automations/{task_id}/run')
def run_automation(task_id: int, context: Context):
    request, tenant = context
    _task(request.app.state.db_path, tenant.workspace_id, tenant.company_id, task_id)
    result = run_automation_now(request.app, tenant.workspace_id, task_id, company_id=tenant.company_id)
    if result is None:
        raise HTTPException(404, 'Automation not found')
    if result.get('busy'):
        raise HTTPException(409, '这个任务正在运行，请稍后再试。')
    if result['status'] == 'error' and not result['output']:
        # Run history remains available for diagnosis; the API still completes.
        return result
    return result


@router.get('/automation-runs')
def list_runs(context: Context):
    request, tenant = context
    with connection(request.app.state.db_path) as conn:
        rows = conn.execute('''
            SELECT runs.*,automations.name AS automation_name
            FROM automation_runs runs JOIN automations ON automations.id=runs.automation_id AND automations.workspace_id=runs.workspace_id
            WHERE runs.workspace_id=? AND automations.company_id=? ORDER BY runs.id DESC LIMIT 100
        ''', (tenant.workspace_id,tenant.company_id)).fetchall()
    return [dict(row) for row in rows]


async def scheduler_loop(app):
    import asyncio
    while True:
        await asyncio.sleep(30)
        try:
            await asyncio.to_thread(run_due_automations, app)
        except Exception:
            pass
