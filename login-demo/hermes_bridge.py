"""Run Hermes one-shot as an optional tool-enabled agent."""

import asyncio
import os
import re
import shutil
import subprocess
from pathlib import Path


class HermesError(Exception):
    pass


_ANSI_ESCAPE = re.compile(r'\x1b(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
DEFAULT_HERMES_TIMEOUT = 360
DEFAULT_HERMES_RUN_BUDGET = 240
DEFAULT_HERMES_MAX_TURNS = 24


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
                '--run-budget',
                str(DEFAULT_HERMES_RUN_BUDGET),
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
