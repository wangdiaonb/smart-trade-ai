import json
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app import create_app
from automation_runner import run_due_automations
from database import connection


def response_stream(text):
    return 'data: '+json.dumps({'choices':[{'delta':{'content':text}}]},ensure_ascii=False)+'\n\ndata: [DONE]\n\n'


@pytest.fixture
def app_and_clients(tmp_path):
    captured=[]
    def provider(request):
        if request.url.host=='api.deepseek.com':
            captured.append(json.loads(request.content))
            return httpx.Response(200,content=response_stream('已完成：'+request.url.host).encode())
        if request.url.host=='api.tavily.com':
            captured.append(json.loads(request.content))
            return httpx.Response(200,json={'answer':'公开信息摘要','results':[{'title':'Acme official site','url':'https://acme.example/about','content':'Acme buys pumps.','score':0.9}]})
        raise AssertionError(request.url)
    path=tmp_path/'platform.sqlite3'
    app=create_app(path,'test-secret',model_transport=httpx.MockTransport(provider),skill_dir=Path(__file__).resolve().parents[2]/'skills')
    first,second=TestClient(app),TestClient(app)
    for client,email in [(first,'platform-a@example.com'),(second,'platform-b@example.com')]:
        assert client.post('/api/register',json={'email':email,'password':'correct-horse-1'}).status_code==201
        client.put('/api/model-settings',json={'model':'deepseek-chat','api_key':'fake-key'})
    return app,first,second,path,captured


def test_skill_catalog_exposes_business_skills_without_injection_text(app_and_clients):
    _,first,second,_,_=app_and_clients
    skills=first.get('/api/chat/skills').json()
    ids={skill['id'] for skill in skills}
    assert 'general' in ids and 'b2b-linkedin-marketing' in ids and len(skills)>=35
    linkedin=next(skill for skill in skills if skill['id']=='b2b-linkedin-marketing')
    assert 'LinkedIn' in linkedin['name']
    assert 'injection_prompt' not in linkedin
    assert second.get('/api/chat/skills').status_code==200


def test_selected_catalog_skill_prompt_is_injected_within_space(app_and_clients):
    _,first,second,_,captured=app_and_clients
    cid=first.post('/api/conversations',json={'title':'LinkedIn'}).json()['id']
    result=first.post(f'/api/conversations/{cid}/stream',json={'content':'制定 LinkedIn 内容计划','skill_id':'b2b-linkedin-marketing'})
    assert 'event: done' in result.text
    system=captured[-1]['messages'][0]['content']
    assert 'LinkedIn' in system and '7 天 LinkedIn 主页打造计划' in system
    other=second.post('/api/conversations',json={'title':'nope'}).json()['id']
    assert second.post(f'/api/conversations/{other}/stream',json={'content':'test','skill_id':'../secrets'}).status_code==422


def test_research_requires_own_key_and_returns_cited_saved_report(app_and_clients):
    _,first,second,path,captured=app_and_clients
    before=len(captured)
    assert first.post('/api/research/search',json={'query':'Acme pumps buyer'}).status_code==409
    assert len(captured)==before
    saved=first.put('/api/research/settings',json={'api_key':'tavily-private-key'})
    assert saved.status_code==200 and saved.json()['has_key'] is True
    assert 'tavily-private-key' not in saved.text
    customer=first.post('/api/customers',json={'name':'Research Buyer'}).json()
    response=first.post('/api/research/search',json={'query':'Acme pumps buyer','customer_id':customer['id']})
    assert response.status_code==201,response.text
    report=response.json()
    assert report['answer']=='公开信息摘要'
    assert report['sources'][0]['url']=='https://acme.example/about'
    assert second.get('/api/research/reports').json()==[]
    assert second.get(f'/api/research/reports/{report["id"]}').status_code==404
    with connection(path) as conn:
        raw=conn.execute('SELECT api_key_encrypted FROM research_settings').fetchone()[0]
    assert 'tavily-private-key' not in raw


def test_chat_web_search_injects_sources_and_emits_source_event(app_and_clients):
    _,first,_,_,captured=app_and_clients
    first.put('/api/research/settings',json={'api_key':'tavily-private-key'})
    cid=first.post('/api/conversations',json={'title':'Market check'}).json()['id']
    response=first.post(
        f'/api/conversations/{cid}/stream',
        json={'content':'Acme pumps buyer','skill_id':'b2b-market-analysis','web_search':True},
    )
    assert response.status_code==200
    assert 'event: sources' in response.text
    assert 'https://acme.example/about' in response.text
    sent=json.dumps(captured[-1],ensure_ascii=False)
    assert '公开信息摘要' in sent and 'Acme official site' in sent


def test_hermes_tool_mode_uses_business_context_and_persists_reply(tmp_path):
    prompts=[]
    async def fake_hermes(prompt,working_directory):
        prompts.append((prompt,working_directory))
        return 'Hermes 工具执行完成'
    app=create_app(
        tmp_path/'hermes.sqlite3','test-secret',
        skill_dir=Path(__file__).resolve().parents[2]/'skills',
        hermes_runner=fake_hermes,
    )
    client=TestClient(app)
    client.post('/api/register',json={'email':'hermes@example.com','password':'correct-horse-1'})
    client.put('/api/company',json={'name':'Hermes Company','products':'Industrial pumps'})
    customer=client.post('/api/customers',json={'name':'Hermes Buyer'}).json()
    cid=client.post('/api/conversations',json={'title':'Hermes tool','customer_id':customer['id']}).json()['id']
    response=client.post(f'/api/conversations/{cid}/hermes',json={
        'content':'查一下客户官网并总结','skill_id':'b2b-platform','web_search':False,
    })
    assert response.status_code==200
    assert response.json()['content']=='Hermes 工具执行完成'
    assert 'Hermes Company' in prompts[0][0]
    assert 'Hermes Buyer' in prompts[0][0]
    assert str(prompts[0][1]).endswith('0') is False
    assert client.get(f'/api/conversations/{cid}').json()['messages'][-1]['content']=='Hermes 工具执行完成'


def test_research_provider_error_is_saved_as_failure_without_fake_answer(tmp_path):
    def search_fail(request):
        return httpx.Response(401,json={'detail':'bad key'})
    app=create_app(tmp_path/'r.sqlite3','test-secret',model_transport=httpx.MockTransport(search_fail),skill_dir=Path(__file__).resolve().parents[2]/'skills')
    client=TestClient(app)
    client.post('/api/register',json={'email':'research@example.com','password':'correct-horse-1'})
    client.put('/api/research/settings',json={'api_key':'bad-key'})
    response=client.post('/api/research/search',json={'query':'Acme pumps'})
    assert response.status_code==502
    assert 'answer' not in response.text
    reports=client.get('/api/research/reports').json()
    assert reports[0]['status']=='error'
    assert reports[0]['answer']==''


def test_deep_osint_runs_orchestrator_and_preserves_layers_per_workspace(tmp_path):
    async def fake_osint(target):
        return {
            'target':target,
            'target_type':'domain',
            'overall_rating':'low',
            'overall_score':90,
            'flags':[],
            'layers':{'domain_intel':{'registered':True},'sanctions':{'is_sanctioned':False}},
            'recommendations':['继续核实采购需求'],
        }
    app=create_app(tmp_path/'deep.sqlite3','test-secret',osint_runner=fake_osint)
    first,second=TestClient(app),TestClient(app)
    for client,email in [(first,'deep-a@example.com'),(second,'deep-b@example.com')]:
        client.post('/api/register',json={'email':email,'password':'correct-horse-1'})
    result=first.post('/api/research/deep',json={'target':'acme.example'})
    assert result.status_code==201
    assert result.json()['details']['overall_score']==90
    assert result.json()['answer'].startswith('综合评级：low')
    assert second.get('/api/research/reports').json()==[]
    assert second.get(f'/api/research/reports/{result.json()["id"]}').status_code==404


def test_automation_crud_is_scoped_and_manual_run_saves_result(app_and_clients):
    _,first,second,_,captured=app_and_clients
    payload={'name':'每日跟进建议','prompt':'根据当前公司资料，列出今天应跟进的客户。','skill_id':'b2b-daily-automation','frequency':'daily','time_of_day':'09:00'}
    created=first.post('/api/automations',json=payload)
    assert created.status_code==201,created.text
    task=created.json()
    assert task['frequency']=='daily' and task['time_of_day']=='09:00'
    assert second.get('/api/automations').json()==[]
    assert second.post(f'/api/automations/{task["id"]}/run').status_code==404
    run=first.post(f'/api/automations/{task["id"]}/run')
    assert run.status_code==200
    assert run.json()['status']=='success'
    assert run.json()['output'].startswith('已完成：api.deepseek.com')
    assert second.get('/api/automation-runs').json()==[]
    for value in ['25:00','09:60','*/5 * * * *']:
        bad={**payload,'time_of_day':value}
        assert first.post('/api/automations',json=bad).status_code==422
    assert first.delete(f'/api/automations/{task["id"]}').status_code==200


def test_due_automation_runs_once_and_records_failure(app_and_clients):
    app,first,second,path,captured=app_and_clients
    task=first.post('/api/automations',json={'name':'到期任务','prompt':'生成简报','skill_id':'b2b-daily-automation','frequency':'daily','time_of_day':'09:00'}).json()
    due='2000-01-01T00:00:00+00:00'
    with connection(path) as conn:
        conn.execute('UPDATE automations SET next_run_at=? WHERE id=?',(due,task['id']))
    result=run_due_automations(app,now=datetime(2026,1,1,tzinfo=timezone.utc))
    assert result['started']==1
    with connection(path) as conn:
        row=conn.execute('SELECT next_run_at FROM automations WHERE id=?',(task['id'],)).fetchone()
        assert row['next_run_at']>due
        assert conn.execute('SELECT count(*) FROM automation_runs WHERE automation_id=?',(task['id'],)).fetchone()[0]==1
    result=run_due_automations(app,now=datetime(2026,1,1,tzinfo=timezone.utc))
    assert result['started']==0


@pytest.mark.parametrize('path',['/api/research/reports','/api/research/settings','/api/automations','/api/automation-runs'])
def test_platform_endpoints_require_login(tmp_path,path):
    client=TestClient(create_app(tmp_path/'auth.sqlite3','test-secret'))
    assert client.get(path).status_code==401
