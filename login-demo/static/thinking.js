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
  return message.state === 'failed' ? '处理未完成' : `已完成思考 · ${elapsedLabel(elapsedMs)}`;
}

export function thinkingText(message) {
  if (message.thinking) return message.thinking;
  if (message.active) return message.statusText || '正在准备回复…';
  return message.state === 'failed' ? '本轮处理未完成。' : '处理完成。';
}
