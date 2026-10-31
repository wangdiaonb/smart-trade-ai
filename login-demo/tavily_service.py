"""Reusable Tavily search through a workspace-owned encrypted key."""

import httpx

from database import connection


async def tavily_lookup(app, workspace_id: int, query: str) -> dict:
    with connection(app.state.db_path) as conn:
        row = conn.execute(
            'SELECT api_key_encrypted FROM research_settings WHERE workspace_id=?',
            (workspace_id,),
        ).fetchone()
    if row is None or not row['api_key_encrypted']:
        return {'configured': False, 'answer': '', 'sources': [], 'error': '尚未配置 Tavily 搜索。'}
    try:
        key = app.state.secret_store.decrypt(workspace_id, row['api_key_encrypted'])
    except ValueError as exc:
        return {'configured': True, 'answer': '', 'sources': [], 'error': str(exc)}
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(30, connect=10),
            transport=app.state.model_transport,
            follow_redirects=False,
        ) as client:
            response = await client.post(
                'https://api.tavily.com/search',
                json={
                    'query': query,
                    'search_depth': 'basic',
                    'max_results': 5,
                    'include_answer': True,
                    'include_raw_content': False,
                },
                headers={'Authorization': f'Bearer {key}', 'Accept': 'application/json'},
            )
    except httpx.HTTPError:
        return {'configured': True, 'answer': '', 'sources': [], 'error': '联网搜索暂时不可用。'}
    if response.status_code != 200:
        return {'configured': True, 'answer': '', 'sources': [], 'error': '联网搜索失败，请检查 Key 或额度。'}
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
        if not sources:
            raise ValueError('No sources')
        return {
            'configured': True,
            'answer': str(data.get('answer') or '')[:12000],
            'sources': sources,
            'error': '',
        }
    except (ValueError, TypeError):
        return {'configured': True, 'answer': '', 'sources': [], 'error': '搜索服务没有返回可用来源。'}
