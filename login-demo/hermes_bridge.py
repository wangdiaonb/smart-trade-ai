"""Run Hermes one-shot as an optional tool-enabled agent."""

import asyncio
import json
import os
import re
import shutil
import subprocess
from pathlib import Path


class HermesError(Exception):
    pass


_ANSI_ESCAPE = re.compile(r'\x1b(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
DEFAULT_HERMES_TIMEOUT = 360
DEFAULT_HERMES_MAX_TURNS = 24
TOOL_OUTPUT_PREVIEW_CHARS = 320

_TOOL_LABELS = (
    ('web_search', '网页搜索'),
    ('browser', '浏览器操作'),
    ('read_file', '读取文件'),
    ('write_file', '写入文件'),
    ('edit_file', '编辑文件'),
    ('list_dir', '浏览目录'),
    ('terminal', '运行终端命令'),
    ('shell', '运行终端命令'),
    ('import_customers', '写入客户库'),
    ('todo', '更新任务清单'),
    ('delegate', '委派子任务'),
    ('search', '搜索'),
    ('fetch', '读取网页'),
)


def tool_label(name: str) -> str:
    """Map a Hermes tool identifier to a concise, user-facing label."""
    normalized = str(name or 'unknown_tool').strip()
    lowered = normalized.lower()
    for marker, label in _TOOL_LABELS:
        if marker in lowered:
            return label
    return '调用工具'


def _preview(value, limit: int = TOOL_OUTPUT_PREVIEW_CHARS) -> str:
    if value is None:
        return ''
    if isinstance(value, str):
        text = value
    else:
        try:
            text = json.dumps(value, ensure_ascii=False)
        except (TypeError, ValueError):
            text = str(value)
    text = _ANSI_ESCAPE.sub('', text).replace('\r\n', '\n')
    text = re.sub(r'\s+', ' ', text).strip()
    return text if len(text) <= limit else text[:limit].rstrip() + '…'


def tool_input_detail(name: str, arguments) -> str:
    """Show the useful part of tool arguments without dumping the whole payload."""
    if not isinstance(arguments, dict):
        return _preview(arguments, 180)
    for key in ('query', 'q', 'url', 'path', 'command', 'pattern', 'description', 'prompt'):
        if arguments.get(key):
            return _preview(arguments[key], 180)
    return _preview(arguments, 180)


def parse_stream_event(line: str) -> dict | None:
    """Convert one Hermes stream-json record into a stable UI event."""
    raw = str(line or '').strip()
    if not raw:
        return None
    # Hermes prints session/status notices outside the JSONL contract on some
    # gateway-backed builds. They are informational, not stream failures.
    if not raw.startswith(('{', '[')):
        return None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HermesError('Hermes 返回了无法识别的流式事件。') from exc
    if not isinstance(payload, dict):
        raise HermesError('Hermes 返回了无效的流式事件。')
    event_type = payload.get('type')
    if event_type == 'text':
        content = payload.get('text')
        return {'type': 'content', 'content': content} if isinstance(content, str) and content else None
    if event_type == 'tool_use':
        name = str(payload.get('name') or 'unknown_tool')
        return {
            'type': 'tool_start',
            'id': str(payload.get('tool_call_id') or name),
            'name': name,
            'label': tool_label(name),
            'detail': tool_input_detail(name, payload.get('input')),
        }
    if event_type == 'tool_result':
        name = str(payload.get('name') or 'unknown_tool')
        output = payload.get('output')
        return {
            'type': 'tool_result',
            'id': str(payload.get('tool_call_id') or name),
            'name': name,
            'label': tool_label(name),
            'detail': _preview(output),
            'duration_ms': max(0, int(payload.get('duration_ms') or 0)),
            'is_error': bool(payload.get('is_error')),
        }
    if event_type == 'result':
        return {
            'type': 'result',
            'text': str(payload.get('text') or ''),
            'exit_code': int(payload.get('exit_code') or 0),
            'error': str(payload.get('error') or ''),
        }
    return None


async def _drain_stderr(stream) -> str:
    chunks = []
    total = 0
    while True:
        line = await stream.readline()
        if not line:
            break
        text = line.decode('utf-8', errors='replace') if isinstance(line, bytes) else str(line)
        if total < 12000:
            chunks.append(text)
            total += len(text)
    return ''.join(chunks).strip()


def stream_command(executable: str, prompt: str) -> list[str]:
    return [
        executable,
        'chat',
        '-q',
        prompt,
        '--max-turns',
        str(DEFAULT_HERMES_MAX_TURNS),
        '-Q',
        '--format',
        'stream-json',
        '--source',
        'tool',
    ]


async def stream_hermes(
    prompt: str,
    working_directory: Path,
    timeout: int = DEFAULT_HERMES_TIMEOUT,
):
    """Yield structured Hermes events as the tool-enabled agent executes."""
    executable = shutil.which('hermes')
    if not executable:
        raise HermesError('Hermes 命令不可用，请先安装并启动 Hermes。')
    working_directory.mkdir(parents=True, exist_ok=True)
    process = await asyncio.create_subprocess_exec(
        *stream_command(executable, prompt),
        cwd=working_directory,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env={**os.environ, 'NO_COLOR': '1'},
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0,
    )
    stderr_task = asyncio.create_task(_drain_stderr(process.stderr))
    saw_result = False
    try:
        async with asyncio.timeout(timeout):
            while True:
                line = await process.stdout.readline()
                if not line:
                    break
                text = line.decode('utf-8', errors='replace') if isinstance(line, bytes) else str(line)
                event = parse_stream_event(text)
                if event:
                    saw_result = saw_result or event['type'] == 'result'
                    yield event
            return_code = await process.wait()
        stderr = await stderr_task
        if return_code != 0 or not saw_result:
            detail = _clean_stdout(stderr)
            raise HermesError(detail[:1000] if detail else 'Hermes 工具执行失败。')
    except TimeoutError as exc:
        if process.returncode is None:
            process.kill()
            await process.wait()
        raise HermesError('Hermes 工具执行超时。') from exc
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()
        if not stderr_task.done():
            stderr_task.cancel()
        await asyncio.gather(stderr_task, return_exceptions=True)


def _clean_stdout(output: str) -> str:
    lines = []
    for line in _ANSI_ESCAPE.sub('', output).replace('\r\n', '\n').splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith(('│', '┃', '@@', '+++', '---', '… 省略')):
            continue
        if stripped.startswith('⚠️') and '模型' in line:
            continue
        lines.append(line)
    return '\n'.join(lines).strip()


async def run_hermes(
    prompt: str,
    working_directory: Path,
    timeout: int = DEFAULT_HERMES_TIMEOUT,
) -> str:
    executable = shutil.which('hermes')
    if not executable:
        raise HermesError('Hermes 命令不可用，请先安装并启动 Hermes。')
    working_directory.mkdir(parents=True, exist_ok=True)

    def invoke():
        return subprocess.run(
            [
                executable,
                'chat',
                '-q',
                prompt,
                '--max-turns',
                str(DEFAULT_HERMES_MAX_TURNS),
                '-Q',
            ],
            cwd=working_directory,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            timeout=timeout,
            env={**os.environ, 'NO_COLOR': '1'},
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0,
        )

    try:
        result = await asyncio.to_thread(invoke)
    except subprocess.TimeoutExpired as exc:
        raise HermesError('Hermes 工具执行超时。') from exc
    output = _clean_stdout(result.stdout)
    if result.returncode != 0:
        raise HermesError('Hermes 工具执行失败。')
    if not output:
        raise HermesError('Hermes 没有返回结果。')
    return output[:200000]
