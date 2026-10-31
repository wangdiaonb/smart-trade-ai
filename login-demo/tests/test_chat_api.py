import json
import sqlite3

import httpx
import pytest
from fastapi.testclient import TestClient

from app import create_app
from chat_store import ChatStore
from database import connection
from tenancy import TenantContext


@pytest.fixture
def setup(tmp_path):
    captured = []

    def provider(request):
        captured.append(json.loads(request.content))
        content = 'data: {"choices":[{"delta":{"content":"你好"}}]}\n\ndata: {"choices":[{"delta":{"content":"，客户"},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n'
        return httpx.Response(200, content=content.encode(), headers={"content-type": "text/event-stream"})

    path = tmp_path / "accounts.sqlite3"
    app = create_app(path, "test-secret", model_transport=httpx.MockTransport(provider))
    first, second = TestClient(app), TestClient(app)
    for client, email in [(first, "chat-a@example.com"), (second, "chat-b@example.com")]:
        assert client.post('/api/register', json={"email": email, "password": "correct-horse-1"}).status_code == 201
    return first, second, path, captured


def configure(client):
    response = client.put('/api/model-settings', json={"provider": "deepseek", "model": "deepseek-chat", "api_key": "fake-key-for-tests-only"})
    assert response.status_code == 200
    return response


def conversation(client, **extra):
    response = client.post('/api/conversations', json={"title": "测试对话", **extra})
    assert response.status_code == 201
    return response.json()["id"]


def test_model_settings_hide_and_encrypt_key_and_preserve_it_on_edit(setup):
    first, second, path, _ = setup
    configured = configure(first)
    assert configured.json()["has_key"] is True
    assert "fake-key-for-tests-only" not in configured.text
    assert "fake-key-for-tests-only" not in first.get('/api/model-settings').text
    assert second.get('/api/model-settings').json()["has_key"] is False
    assert first.put('/api/model-settings', json={"model": "another-model"}).json()["has_key"] is True
    with sqlite3.connect(path) as conn:
        raw = conn.execute("SELECT api_key_encrypted FROM model_settings").fetchone()[0]
        assert "fake-key-for-tests-only" not in raw


def test_invalid_model_key_is_not_echoed_in_validation_error(setup):
    first, _, _, _ = setup
    secret = 'private-marker-' + 'x' * 1001
    response = first.put('/api/model-settings', json={"api_key": secret})
    assert response.status_code == 422
    assert 'private-marker-' not in response.text


def test_thread_and_memory_are_scoped_to_workspace(setup):
    first, second, _, _ = setup
    cid = conversation(first)
    assert second.get('/api/conversations').json() == []
    assert second.get(f'/api/conversations/{cid}').status_code == 404
    assert second.delete(f'/api/conversations/{cid}').status_code == 404
    assert first.put('/api/memory', json={"content": "只在A空间的偏好"}).status_code == 200
    assert second.get('/api/memory').json()["content"] == ""
    assert first.get('/api/memory').json()["content"] == "只在A空间的偏好"


def test_stream_persists_messages_and_injects_only_current_context(setup):
    first, second, _, captured = setup
    configure(first)
    first.put('/api/company', json={"name": "甲公司", "products": "水泵"})
    second.put('/api/company', json={"name": "乙公司秘密", "products": "保密产品"})
    first.put('/api/memory', json={"content": "回复要简短"})
    buyer = first.post('/api/customers', json={"name": "Buyer A", "contact": "Alice"}).json()
    cid = conversation(first, customer_id=buyer["id"])
    response = first.post(f'/api/conversations/{cid}/stream', json={"content": "帮我写开发信", "skill_id": "outreach"})
    assert response.status_code == 200
    assert 'event: delta' in response.text
    assert 'event: done' in response.text
    assert 'event: error' not in response.text
    messages = first.get(f'/api/conversations/{cid}').json()["messages"]
    assert [m["role"] for m in messages] == ['user', 'assistant']
    assert messages[1]["content"] == "你好，客户"
    assert messages[1]["status"] == "complete"
    sent = json.dumps(captured[0], ensure_ascii=False)
    assert "甲公司" in sent and "Buyer A" in sent and "回复要简短" in sent
    assert "乙公司秘密" not in sent and "保密产品" not in sent


def test_missing_config_does_not_create_a_phantom_turn(setup):
    first, _, _, captured = setup
    cid = conversation(first)
    response = first.post(f'/api/conversations/{cid}/stream', json={"content": "你好"})
    assert response.status_code == 409
    assert first.get(f'/api/conversations/{cid}').json()["messages"] == []
    assert captured == []


def test_cross_workspace_chat_and_customer_binding_are_rejected(setup):
    first, second, _, _ = setup
    buyer = first.post('/api/customers', json={"name": "Private buyer"}).json()
    assert second.post('/api/conversations', json={"customer_id": buyer["id"]}).status_code == 404
    cid = conversation(first)
    assert second.post(f'/api/conversations/{cid}/stream', json={"content": "steal"}).status_code == 404


def test_second_turn_includes_history(setup):
    first, _, _, captured = setup
    configure(first)
    cid = conversation(first)
    first.post(f'/api/conversations/{cid}/stream', json={"content": "第一轮"})
    first.post(f'/api/conversations/{cid}/stream', json={"content": "第二轮"})
    messages = captured[1]["messages"]
    assert [m["role"] for m in messages] == ['system', 'user', 'assistant', 'user']
    assert messages[-1]["content"] == "第二轮"


@pytest.mark.parametrize('status,body', [(401, 'fake-key-for-tests-only'), (200, 'data: {"choices":[{"delta":{"content":"partial"}}]}\n\n')])
def test_upstream_error_or_truncated_stream_is_not_reported_as_success(tmp_path, status, body):
    app = create_app(tmp_path / "db.sqlite3", "test-secret", model_transport=httpx.MockTransport(lambda request: httpx.Response(status, content=body)))
    client = TestClient(app)
    client.post('/api/register', json={"email":"a@example.com", "password":"correct-horse-1"})
    configure(client)
    cid = conversation(client)
    response = client.post(f'/api/conversations/{cid}/stream', json={"content": "test"})
    assert 'event: error' in response.text
    assert 'event: done' not in response.text
    assert 'fake-key-for-tests-only' not in response.text
    messages = client.get(f'/api/conversations/{cid}').json()["messages"]
    assert messages[-1]["status"] == 'error'
    assert client.delete(f'/api/conversations/{cid}').status_code == 200


def test_owner_fields_and_unknown_skills_are_rejected(setup):
    first, _, _, _ = setup
    assert first.put('/api/model-settings', json={"workspace_id": 999}).status_code == 422
    assert first.post('/api/conversations', json={"workspace_id": 999}).status_code == 422
    cid = conversation(first)
    assert first.post(f'/api/conversations/{cid}/stream', json={"content": "test", "skill_id": "unknown"}).status_code == 422


def test_busy_conversation_rejects_parallel_turn_and_stale_cancel_cannot_unlock_next_turn(setup):
    first, _, path, _ = setup
    configure(first)
    user = first.get('/api/me').json()
    workspace = first.get('/api/workspace').json()
    store = ChatStore(path, TenantContext(user['id'], workspace['id'], user['email']))
    cid = conversation(first)
    old_token, old_message = store.claim_turn(cid, 'first', 'general')
    assert first.post(f'/api/conversations/{cid}/stream', json={"content":"parallel"}).status_code == 409
    assert first.delete(f'/api/conversations/{cid}').status_code == 409
    assert first.post(f'/api/conversations/{cid}/cancel').status_code == 200
    new_token, _ = store.claim_turn(cid, 'next', 'general')
    store.finish_turn(cid, old_token, old_message, 'partial', 'cancelled')
    assert store.turn_active(cid, new_token)
    messages = first.get(f'/api/conversations/{cid}').json()['messages']
    assert messages[1]['status'] == 'cancelled'
    assert messages[1]['content'] == 'partial'


def test_encrypted_key_remains_usable_after_app_restart(setup):
    first, _, path, _ = setup
    configure(first)
    sent = []
    def provider(request):
        sent.append(request.headers['Authorization'])
        return httpx.Response(200, content='data: {"choices":[{"delta":{"content":"ok"}}]}\n\ndata: [DONE]\n\n')
    client = TestClient(create_app(path, 'test-secret', model_transport=httpx.MockTransport(provider)))
    assert client.post('/api/login', json={"email":"chat-a@example.com", "password":"correct-horse-1"}).status_code == 200
    cid = conversation(client)
    assert 'event: done' in client.post(f'/api/conversations/{cid}/stream', json={"content":"after restart"}).text
    assert sent == ['Bearer fake-key-for-tests-only']


def test_other_tenant_ciphertext_cannot_be_reused(setup):
    first, second, path, _ = setup
    configure(first)
    a = first.get('/api/workspace').json()['id']
    b = second.get('/api/workspace').json()['id']
    with connection(path) as conn:
        cipher = conn.execute('SELECT api_key_encrypted FROM model_settings WHERE workspace_id=?',(a,)).fetchone()[0]
        conn.execute('INSERT INTO model_settings(workspace_id,api_key_encrypted) VALUES (?,?)',(b,cipher))
    cid = conversation(second)
    assert second.post(f'/api/conversations/{cid}/stream',json={"content":"steal key"}).status_code == 409


@pytest.mark.parametrize('path', ['/api/conversations', '/api/model-settings', '/api/memory', '/api/chat/skills'])
def test_chat_endpoints_require_login(tmp_path, path):
    client = TestClient(create_app(tmp_path / "db.sqlite3", "test-secret"))
    assert client.get(path).status_code == 401
