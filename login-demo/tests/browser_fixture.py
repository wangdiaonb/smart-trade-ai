"""Disposable browser fixture. Run manually; never replaces the real demo DB."""

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

import httpx
import uvicorn

from app import create_app
from auth import register_user
from business import WorkspaceStore
from chat_store import ChatStore
from database import connection
from tenancy import TenantContext


class ReasoningStream(httpx.AsyncByteStream):
    async def __aiter__(self):
        deltas = [
            {'reasoning_content': '先确认用户关心的是产品资料和客户上下文。', 'content': None},
            {'reasoning_content': '再检查当前空间的数据边界。', 'content': None},
            {'content': '【隔离测试响应】产品资料和客户上下文已接收。', 'finish_reason': None},
            {'content': '这是本地模拟模型，仅用于验证流式界面。', 'finish_reason': 'stop'},
        ]
        for delta in deltas:
            yield ('data: ' + json.dumps({'choices': [{'delta': delta}]}, ensure_ascii=False) + '\n\n').encode()
            await asyncio.sleep(0.8)
        yield b'data: [DONE]\n\n'


def model(request):
    if request.url.host == 'api.tavily.com':
        return httpx.Response(200, json={
            'answer': '隔离测试搜索摘要：公开资料显示该客户采购工业水泵。',
            'results': [
                {
                    'title': 'Acme official site',
                    'url': 'https://acme.example/about',
                    'content': 'Public browser validation source for Acme pumps.',
                    'score': 0.9,
                }
            ],
        })
    return httpx.Response(200,stream=ReasoningStream(),headers={'content-type':'text/event-stream'})


async def hermes_streamer(prompt, working_directory):
    del prompt, working_directory
    yield {
        'type': 'tool_start',
        'id': 'fixture-search',
        'name': 'web_search',
        'label': '网页搜索',
        'detail': '工业水泵配件 德国采购商',
    }
    await asyncio.sleep(0.7)
    yield {
        'type': 'tool_result',
        'id': 'fixture-search',
        'name': 'web_search',
        'label': '网页搜索',
        'detail': '找到 4 条公开来源，正在核对采购商官网',
        'duration_ms': 700,
    }
    yield {
        'type': 'tool_start',
        'id': 'fixture-browser',
        'name': 'browser_navigate',
        'label': '浏览器操作',
        'detail': 'https://acme.example/about',
    }
    await asyncio.sleep(0.7)
    yield {
        'type': 'tool_result',
        'id': 'fixture-browser',
        'name': 'browser_navigate',
        'label': '浏览器操作',
        'detail': '已读取企业介绍和产品分类页面',
        'duration_ms': 700,
    }
    final = '已完成客户官网核验：该客户主营工业水泵，产品页覆盖维修配件和替换件，建议从备件采购需求切入。'
    yield {'type': 'content', 'content': final}
    yield {'type': 'result', 'text': final, 'exit_code': 0, 'error': ''}


if __name__=='__main__':
    with tempfile.TemporaryDirectory(prefix='workroom-browser-') as folder:
        path=Path(folder)/'accounts.sqlite3'
        app=create_app(
            path,
            'ui-fixture-secret',
            model_transport=httpx.MockTransport(model),
            hermes_streamer=hermes_streamer,
        )
        for index in [1,2]:
            user=register_user(path,f'ui-{index}@example.com','ui-fixture-password')
            with connection(path) as conn:
                wid=conn.execute('SELECT id FROM workspaces WHERE owner_user_id=?',(user['id'],)).fetchone()[0]
                company_id=conn.execute('SELECT id FROM companies WHERE workspace_id=?',(wid,)).fetchone()[0]
            tenant=TenantContext(user['id'],wid,user['email'],company_id)
            if index==1:
                store=WorkspaceStore(path,tenant)
                store.update_company({'name':'隔离浏览器测试公司','products':'水泵配件'})
                store.create_customer({
                    'name':'Browser Buyer',
                    'contact':'Alice',
                    'country':'德国',
                    'tier':'A',
                    'email':'alice@browser.example',
                    'backup_email':'sales@browser.example',
                })
                ChatStore(path,tenant).save_settings({'api_key_encrypted':app.state.secret_store.encrypt(wid,'fake-ui-key')})
        uvicorn.run(app,host='127.0.0.1',port=int(os.getenv('PORT','8018')),log_level='warning')
