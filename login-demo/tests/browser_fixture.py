"""Disposable browser fixture. Run manually; never replaces the real demo DB."""

import json
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
    response='【隔离测试响应】产品资料和客户上下文已接收。这是本地模拟模型，仅用于验证流式界面。'
    events=''.join('data: '+json.dumps({'choices':[{'delta':{'content':part}}]},ensure_ascii=False)+'\n\n' for part in [response[:20],response[20:]])
    return httpx.Response(200,content=(events+'data: [DONE]\n\n').encode())


if __name__=='__main__':
    with tempfile.TemporaryDirectory(prefix='workroom-browser-') as folder:
        path=Path(folder)/'accounts.sqlite3'
        app=create_app(path,'ui-fixture-secret',model_transport=httpx.MockTransport(model))
        for index in [1,2]:
            user=register_user(path,f'ui-{index}@example.com','ui-fixture-password')
            with connection(path) as conn:
                wid=conn.execute('SELECT id FROM workspaces WHERE owner_user_id=?',(user['id'],)).fetchone()[0]
            tenant=TenantContext(user['id'],wid,user['email'])
            if index==1:
                store=WorkspaceStore(path,tenant)
                store.update_company({'name':'隔离浏览器测试公司','products':'水泵配件'})
                store.create_customer({'name':'Browser Buyer','contact':'Alice','country':'德国','tier':'A'})
                ChatStore(path,tenant).save_settings({'api_key_encrypted':app.state.secret_store.encrypt(wid,'fake-ui-key')})
        uvicorn.run(app,host='127.0.0.1',port=8018,log_level='warning')
