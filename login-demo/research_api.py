"""Tenant-owned optional web research with explicit citations."""

import json
import sys
from pathlib import Path
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import Field, SecretStr

from business_models import BusinessInput
from database import connection
from tenancy import TenantContext, require_tenant

router = APIRouter(prefix='/api', tags=['research'])


class ResearchSettings(BusinessInput):
    api_key: SecretStr | None = Field(None, max_length=1000)
    clear_key: bool = False


class SearchInput(BusinessInput):
    query: str = Field(min_length=2, max_length=2000, pattern=r'\S')
    customer_id: int | None = Field(None, gt=0)


class DeepTarget(BusinessInput):
    target: str = Field(min_length=2, max_length=500, pattern=r'\S')
    customer_id: int | None = Field(None, gt=0)


def context(request: Request, tenant: TenantContext = Depends(require_tenant)):
    return request.app.state.db_path, tenant


Context = Annotated[tuple, Depends(context)]


def _settings(path, wid):
    with connection(path) as conn:
        row = conn.execute('SELECT api_key_encrypted FROM research_settings WHERE workspace_id=?', (wid,)).fetchone()
    return row['api_key_encrypted'] if row else ''


def _report(path, wid, rid, company_id=None):
    with connection(path) as conn:
        row = conn.execute('''
            SELECT reports.*, customers.name AS customer_name
            FROM research_reports reports
            LEFT JOIN customers ON customers.id=reports.customer_id AND customers.workspace_id=reports.workspace_id
            WHERE reports.id=? AND reports.workspace_id=? AND (? IS NULL OR reports.company_id=?)
        ''', (rid, wid, company_id, company_id)).fetchone()
    if row is None:
        raise HTTPException(404, 'Research report not found')
    result = dict(row)
    result['sources'] = json.loads(result['sources'])
    result['details'] = json.loads(result.get('details') or '{}')
    return result


def _save_report(path, wid, company_id, payload, status, answer='', sources=None, error='', details=None):
    query = getattr(payload, 'query', None) or getattr(payload, 'target', '')
    with connection(path) as conn:
        if payload.customer_id is not None and conn.execute(
            'SELECT 1 FROM customers WHERE id=? AND workspace_id=?',
            (payload.customer_id, wid),
        ).fetchone() is None:
            raise HTTPException(404, 'Customer not found')
        cursor = conn.execute('''
            INSERT INTO research_reports(workspace_id,company_id,customer_id,query,status,answer,sources,details,error)
            VALUES (?,?,?,?,?,?,?,?,?)
        ''', (wid, company_id, payload.customer_id, query, status, answer, json.dumps(sources or [], ensure_ascii=False), json.dumps(details or {}, ensure_ascii=False), error))
    return _report(path, wid, cursor.lastrowid, company_id)


async def default_osint_runner(target: str) -> dict:
    """Run the original public-information orchestration without license gating."""
    repo_root = Path(__file__).resolve().parent.parent
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    from trade.osint.orchestrator import osint_full_check
    return await osint_full_check(target)


@router.get('/research/settings')
def settings(context: Context):
    path, tenant = context
    return {'has_key': bool(_settings(path, tenant.workspace_id))}


@router.put('/research/settings')
def update_settings(payload: ResearchSettings, request: Request, context: Context):
    path, tenant = context
    if payload.api_key and payload.clear_key:
        raise HTTPException(422, '不能同时填写和清除搜索密钥。')
    if payload.clear_key:
        encrypted = ''
    elif payload.api_key and payload.api_key.get_secret_value().strip():
        encrypted = request.app.state.secret_store.encrypt(tenant.workspace_id, payload.api_key.get_secret_value().strip())
    else:
        encrypted = _settings(path, tenant.workspace_id)
    with connection(path) as conn:
        conn.execute(
            'INSERT INTO research_settings(workspace_id,api_key_encrypted) VALUES (?,?) '
            'ON CONFLICT(workspace_id) DO UPDATE SET api_key_encrypted=excluded.api_key_encrypted',
            (tenant.workspace_id, encrypted),
        )
    return {'has_key': bool(encrypted)}


@router.post('/research/search', status_code=201)
async def search(payload: SearchInput, request: Request, context: Context):
    path, tenant = context
    encrypted = _settings(path, tenant.workspace_id)
    if not encrypted:
        raise HTTPException(409, '请先在客户情报页面保存 Tavily API Key。')
    try:
        key = request.app.state.secret_store.decrypt(tenant.workspace_id, encrypted)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    body = {
        'query': payload.query,
        'search_depth': 'basic',
        'max_results': 5,
        'include_answer': True,
        'include_raw_content': False,
    }
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(30, connect=10),
            transport=request.app.state.model_transport,
            follow_redirects=False,
        ) as client:
            response = await client.post(
                'https://api.tavily.com/search',
                json=body,
                headers={'Authorization': f'Bearer {key}', 'Accept': 'application/json'},
            )
    except httpx.HTTPError:
        report = _save_report(path, tenant.workspace_id, tenant.company_id, payload, 'error', error='无法连接搜索服务。')
        raise HTTPException(502, '无法连接客户情报搜索服务，请检查网络后重试。') from None
    if response.status_code in (401, 403):
        _save_report(path, tenant.workspace_id, tenant.company_id, payload, 'error', error='搜索 API Key 无效。')
        raise HTTPException(502, 'Tavily API Key 无效，请重新配置。')
    if response.status_code == 429:
        _save_report(path, tenant.workspace_id, tenant.company_id, payload, 'error', error='搜索额度或频率受限。')
        raise HTTPException(502, '搜索服务额度或频率受限，请稍后重试。')
    if response.status_code != 200:
        _save_report(path, tenant.workspace_id, tenant.company_id, payload, 'error', error='搜索服务返回错误。')
        raise HTTPException(502, '客户情报搜索暂时不可用。')
    try:
        data = response.json()
        sources = []
        for item in (data.get('results') or [])[:5]:
            url = str(item.get('url') or '')
            if not url.startswith(('https://', 'http://')):
                continue
            sources.append({
                'title': str(item.get('title') or '')[:500],
                'url': url[:2000],
                'content': str(item.get('content') or '')[:4000],
                'score': float(item.get('score') or 0),
            })
        answer = str(data.get('answer') or '')[:12000]
        if not sources:
            raise ValueError('No cited results')
    except (ValueError, TypeError):
        _save_report(path, tenant.workspace_id, tenant.company_id, payload, 'error', error='搜索结果格式无效。')
        raise HTTPException(502, '搜索服务没有返回可用的来源。')
    return _save_report(path, tenant.workspace_id, tenant.company_id, payload, 'success', answer=answer, sources=sources)


@router.post('/research/deep', status_code=201)
async def deep_research(payload: DeepTarget, request: Request, context: Context):
    path, tenant = context
    try:
        details = await request.app.state.osint_runner(payload.target.strip())
    except Exception:
        report = _save_report(
            path, tenant.workspace_id, tenant.company_id, payload, 'error',
            error='深度背调未能完成，请检查网络和本地依赖后重试。',
        )
        return report
    rating = str(details.get('overall_rating') or 'unknown')
    score = details.get('overall_score')
    answer = f"综合评级：{rating}；风险评分：{score if score is not None else '未知'}。"
    return _save_report(
        path, tenant.workspace_id, tenant.company_id, payload, 'success',
        answer=answer, details=details,
    )


@router.get('/research/reports')
def reports(context: Context):
    path, tenant = context
    with connection(path) as conn:
        rows = conn.execute('''
            SELECT reports.id,reports.query,reports.status,reports.answer,reports.error,
                   reports.created_at,reports.customer_id,customers.name AS customer_name,
                   (SELECT count(*) FROM json_each(reports.sources)) AS source_count,
                   CASE WHEN json_extract(reports.details, '$') <> '{}' THEN 'deep' ELSE 'search' END AS report_type
            FROM research_reports reports
            LEFT JOIN customers ON customers.id=reports.customer_id AND customers.workspace_id=reports.workspace_id
            WHERE reports.workspace_id=? AND reports.company_id=? ORDER BY reports.id DESC LIMIT 100
        ''', (tenant.workspace_id,tenant.company_id)).fetchall()
    return [dict(row) for row in rows]


@router.get('/research/reports/{rid}')
def report(rid: int, context: Context):
    path, tenant = context
    return _report(path, tenant.workspace_id, rid, tenant.company_id)


@router.delete('/research/reports/{rid}')
def delete_report(rid: int, context: Context):
    path, tenant = context
    _report(path, tenant.workspace_id, rid, tenant.company_id)
    with connection(path) as conn:
        conn.execute('DELETE FROM research_reports WHERE id=? AND workspace_id=?', (rid, tenant.workspace_id))
    return {'ok': True}
