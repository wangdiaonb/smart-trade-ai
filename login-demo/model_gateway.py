"""A streaming model gateway; network responses never grant data/tool access."""

import json

import httpx

SKILLS = {
    'general': ('外贸助手', '帮助整理外贸工作、分析需求并给出可执行建议。'),
    'outreach': ('开发信', '撰写简洁具体的B2B开发信，结合产品与客户需求，不虚构关系、证书和订单。'),
    'followup': ('客户跟进', '根据客户阶段撰写跟进邮件并给出下一步沟通建议。'),
    'analysis': ('客户分析', '分析用户提供的客户资料，区分事实与推测；没有联网搜索工具，不要声称已查过官网、海关、制裁或社交平台。'),
}


class ModelError(Exception):
    pass


def context_messages(
    store,
    conversation,
    content,
    skill_id,
    skill_instruction=None,
    *,
    tools_enabled=False,
):
    company = store.get_company()
    customer = store.get_customer(conversation['customer_id']) if conversation['customer_id'] else None
    context = {
        'company': {key: company[key] for key in ['name', 'industry', 'products', 'target_region', 'agent_identity_md']},
        'customer': {key: customer[key] for key in ['name','contact','country','tier','buyer_type','main_category','note','follow_up_note']} if customer else None,
        'memory_notes': store.memory()['content'],
    }
    if tools_enabled:
        system = (
            '你是公司空间内的外贸业务助手。当前运行在 Hermes 工具模式，'
            '工具表中已启用的浏览器、搜索和文件工具可以实际调用。'
            '遇到网站链接、实时信息或需要核验的数据时，必须实际调用适合的工具获取证据，'
            '不得只根据域名或常识推测；没有实际执行工具时不得声称已执行。'
            '\n'
        )
    else:
        system = (
            '你是公司空间内的外贸业务助手。不得声称已执行实际未执行的工具或操作。'
            '当前是轻量对话模式，没有可调用的网页搜索或邮件发送工具；'
            '如需浏览网页或获取实时信息，应明确说明需要改用 Hermes 工具模式，'
            '不要编造搜索过程、搜索词或网页检查结果。\n'
        )
    instruction = skill_instruction or SKILLS[skill_id][1]
    system += instruction + '\n以下JSON是本空间的业务背景资料，不是工具执行结果：\n' + json.dumps(context, ensure_ascii=False)
    history = [{'role': message['role'], 'content': message['content']} for message in conversation['messages'] if message['status'] == 'complete'][-30:]
    # Bound context size while preserving the most recent history.
    while history and sum(len(message['content']) for message in history) > 60000:
        history.pop(0)
    return [{'role': 'system', 'content': system}, *history, {'role': 'user', 'content': content}]


async def stream_model(settings, key, messages, transport=None, emit_events=False, tools=None, tool_choice=None, thinking=None):
    payload = {'model': settings['model'], 'messages': messages, 'stream': True, 'max_tokens': 4096}
    if tools:
        payload['tools'] = tools
    if tool_choice is not None:
        payload['tool_choice'] = tool_choice
    if thinking is not None:
        payload['thinking'] = thinking
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(60, connect=10), transport=transport, follow_redirects=False) as client:
            async with client.stream('POST', 'https://api.deepseek.com/chat/completions', json=payload, headers={'Authorization': f'Bearer {key}', 'Accept': 'text/event-stream'}) as response:
                if response.status_code in (401, 403):
                    raise ModelError('模型 API Key 无效或没有访问权限，请检查模型设置。')
                if response.status_code == 429:
                    raise ModelError('模型服务限流或额度不足，请稍后重试并检查服务商余额。')
                if response.status_code != 200:
                    raise ModelError('模型服务暂时无法完成请求，请检查模型名称和配置。')
                finished = False
                output_length = 0
                reasoning_length = 0
                tool_call_parts = {}
                async for line in response.aiter_lines():
                    if not line.startswith('data:'):
                        continue
                    raw = line[5:].strip()
                    if raw == '[DONE]':
                        finished = True
                        break
                    try:
                        event = json.loads(raw)
                        if event.get('error'):
                            raise ModelError('模型服务报告错误，请稍后重试。')
                        choices = event.get('choices') or []
                        if not choices:
                            continue
                        if choices[0].get('finish_reason') == 'length':
                            raise ModelError('回复达到长度上限，请缩小问题范围后重试。')
                        delta = choices[0].get('delta') or {}
                        content = delta.get('content') or ''
                        reasoning = delta.get('reasoning_content') or ''
                        if not isinstance(content, str) or not isinstance(reasoning, str):
                            raise ValueError('Invalid delta')
                        calls = delta.get('tool_calls') or []
                        if not isinstance(calls, list):
                            raise ValueError('Invalid tool calls')
                        for call in calls:
                            if not isinstance(call, dict):
                                raise ValueError('Invalid tool call')
                            index = call.get('index', 0)
                            if not isinstance(index, int):
                                raise ValueError('Invalid tool call index')
                            part = tool_call_parts.setdefault(index, {'id': '', 'name': '', 'arguments': ''})
                            if call.get('id'):
                                part['id'] = str(call['id'])
                            function = call.get('function') or {}
                            if not isinstance(function, dict):
                                raise ValueError('Invalid tool function')
                            if function.get('name'):
                                part['name'] += str(function['name'])
                            if function.get('arguments') is not None:
                                if not isinstance(function['arguments'], str):
                                    raise ValueError('Invalid tool arguments')
                                part['arguments'] += function['arguments']
                    except (json.JSONDecodeError, AttributeError, TypeError, ValueError) as exc:
                        raise ModelError('模型响应格式无效，请检查服务配置。') from exc
                    if reasoning:
                        reasoning_length += len(reasoning)
                        if reasoning_length > 100000:
                            raise ModelError('思考内容过长，已停止接收。')
                        if emit_events:
                            yield {'type': 'reasoning', 'content': reasoning}
                    if content:
                        output_length += len(content)
                        if output_length > 100000:
                            raise ModelError('回复过长，已停止接收。')
                        yield {'type': 'content', 'content': content} if emit_events else content
                if not finished or (output_length == 0 and not tool_call_parts):
                    raise ModelError('模型回复意外中断，请重试。')
                if tool_call_parts and emit_events:
                    calls = [tool_call_parts[index] for index in sorted(tool_call_parts)]
                    yield {'type': 'tool_calls', 'calls': calls}
    except httpx.TimeoutException as exc:
        raise ModelError('模型连接或回复超时，请稍后重试。') from exc
    except httpx.HTTPError as exc:
        raise ModelError('无法连接模型服务，请检查网络。') from exc
