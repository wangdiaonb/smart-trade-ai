export function thinkingStage(elapsedMs) {
  if (elapsedMs < 1500) return '正在理解你的问题';
  if (elapsedMs < 3500) return '正在整理业务上下文';
  return '正在组织回答';
}

export function elapsedLabel(elapsedMs) {
  if (elapsedMs < 1000) return '不足 1 秒';
  return `${Math.max(1, Math.round(elapsedMs / 1000))} 秒`;
}

export function thinkingLabel(message, now = Date.now()) {
  if (message.active) {
    return message.statusText || thinkingStage(Math.max(0, now - message.startedAt));
  }
  const elapsedMs = message.durationMs ?? Math.max(0, now - message.startedAt);
  const toolCount = Array.isArray(message.tools) ? message.tools.length : 0;
  const toolSummary = toolCount ? ` · ${toolCount} 个工具` : '';
  return message.state === 'failed'
    ? `处理未完成${toolSummary}`
    : `已完成思考${toolSummary} · ${elapsedLabel(elapsedMs)}`;
}

export function thinkingText(message) {
  if (message.thinking) return message.thinking;
  if (message.active) return message.statusText || '正在准备回复…';
  return message.state === 'failed' ? '本轮处理未完成。' : '处理完成。';
}

const TOOL_LABELS = [
  ['web_search', '网页搜索'],
  ['browser', '浏览器操作'],
  ['read_file', '读取文件'],
  ['write_file', '写入文件'],
  ['edit_file', '编辑文件'],
  ['list_dir', '浏览目录'],
  ['terminal', '运行终端命令'],
  ['shell', '运行终端命令'],
  ['import_customers', '写入客户库'],
  ['todo', '更新任务清单'],
  ['delegate', '委派子任务'],
  ['search', '搜索'],
  ['fetch', '读取网页'],
];

export function toolLabel(name) {
  const normalized = String(name || 'unknown_tool').trim();
  const lowered = normalized.toLowerCase();
  const match = TOOL_LABELS.find(([marker]) => lowered.includes(marker));
  return match ? match[1] : '调用工具';
}

export function toolStatusLabel(status) {
  if (status === 'complete') return '已完成';
  if (status === 'failed') return '执行失败';
  return '运行中';
}

export function applyToolEvent(message, type, data = {}) {
  if (!Array.isArray(message.tools)) message.tools = [];
  const name = String(data.name || 'unknown_tool').trim();
  const id = String(data.id || data.tool_call_id || name);
  let tool = message.tools.find(item => item.id === id);
  if (!tool) {
    tool = {
      id,
      name,
      label: data.label || toolLabel(name),
      detail: '',
      status: 'running',
      durationMs: null,
    };
    message.tools.push(tool);
  }
  if (type === 'tool_start') {
    tool.status = 'running';
    tool.label = data.label || tool.label || toolLabel(name);
    tool.detail = data.detail || tool.detail || '';
  } else if (type === 'tool_result') {
    tool.status = data.is_error ? 'failed' : 'complete';
    tool.label = data.label || tool.label || toolLabel(name);
    tool.detail = data.detail || tool.detail || '';
    tool.durationMs = Number.isFinite(Number(data.duration_ms)) ? Number(data.duration_ms) : null;
  }
  return tool;
}
