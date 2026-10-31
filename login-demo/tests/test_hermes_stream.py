import json

from fastapi.testclient import TestClient

from app import create_app
from hermes_bridge import parse_stream_event, stream_command, tool_label


def events(body):
    parsed = []
    for block in body.split('\n\n'):
        lines = block.splitlines()
        event = next((line[6:].strip() for line in lines if line.startswith('event:')), '')
        raw = '\n'.join(line[5:].strip() for line in lines if line.startswith('data:'))
        if event and raw:
            parsed.append((event, json.loads(raw)))
    return parsed


def test_hermes_stream_json_tool_events_keep_real_names_and_summaries():
    start = parse_stream_event(json.dumps({
        'type': 'tool_use',
        'name': 'web_search',
        'tool_call_id': 'call-1',
        'input': {'query': 'industrial pump buyers Germany'},
    }))
    result = parse_stream_event(json.dumps({
        'type': 'tool_result',
        'name': 'web_search',
        'tool_call_id': 'call-1',
        'duration_ms': 2750,
        'output': 'Found 4 public sources',
    }))

    assert start == {
        'type': 'tool_start',
        'id': 'call-1',
        'name': 'web_search',
        'label': '网页搜索',
        'detail': 'industrial pump buyers Germany',
    }
    assert result['type'] == 'tool_result'
    assert result['name'] == 'web_search'
    assert result['duration_ms'] == 2750
    assert result['detail'] == 'Found 4 public sources'
    assert tool_label('browser_navigate') == '浏览器操作'
    assert tool_label('custom_tool') == '调用工具'


def test_hermes_stream_ignores_plain_session_status_lines():
    assert parse_stream_event('Session: local-10096ef36ef7ed38761aa7ad74d3830638d569273eb6b1096daa6c9ce92dddc7') is None


def test_hermes_stream_command_omits_gateway_unsupported_run_budget():
    command = stream_command('hermes', '你好')

    assert '--run-budget' not in command
    assert command[command.index('--format') + 1] == 'stream-json'
    assert command[command.index('--max-turns') + 1] == '24'


def test_hermes_route_streams_tool_timeline_and_final_reply(tmp_path):
    async def fake_streamer(prompt, working_directory):
        yield {
            'type': 'tool_start',
            'id': 'call-search',
            'name': 'web_search',
            'label': '网页搜索',
            'detail': 'Acme official website',
        }
        yield {
            'type': 'tool_result',
            'id': 'call-search',
            'name': 'web_search',
            'label': '网页搜索',
            'detail': '找到官网和产品页',
            'duration_ms': 1200,
        }
        yield {'type': 'content', 'content': '已完成网站资料核验。'}
        yield {
            'type': 'result',
            'text': '已完成网站资料核验。',
            'exit_code': 0,
            'error': '',
        }

    app = create_app(
        tmp_path / 'hermes-stream.sqlite3',
        'test-secret',
        hermes_streamer=fake_streamer,
    )
    client = TestClient(app)
    client.post('/api/register', json={
        'email': 'hermes-stream@example.com',
        'password': 'correct-horse-1',
    })
    conversation_id = client.post('/api/conversations', json={'title': '网站核验'}).json()['id']

    response = client.post(
        f'/api/conversations/{conversation_id}/hermes',
        json={'content': '核验客户官网', 'skill_id': 'b2b-platform', 'web_search': True},
    )

    assert response.status_code == 200
    received = events(response.text)
    tool_start = next(data for event, data in received if event == 'tool_start')
    tool_result = next(data for event, data in received if event == 'tool_result')
    assert tool_start['name'] == 'web_search'
    assert tool_start['detail'] == 'Acme official website'
    assert tool_result['duration_ms'] == 1200
    assert any(event == 'done' for event, _ in received)
    assert client.get(f'/api/conversations/{conversation_id}').json()['messages'][-1]['content'] == '已完成网站资料核验。'
