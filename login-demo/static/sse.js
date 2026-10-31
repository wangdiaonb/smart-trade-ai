export async function readSSE(response, onEvent) {
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  try {
    while (true) {
      const part = await reader.read();
      buffer = (buffer + decoder.decode(part.value, {stream: !part.done})).replace(/\r\n/g, '\n');
      let boundary;
      while ((boundary = buffer.indexOf('\n\n')) >= 0) {
        const block = buffer.slice(0, boundary); buffer = buffer.slice(boundary + 2);
        const lines = block.split('\n');
        const type = lines.find(line => line.startsWith('event:'))?.slice(6).trim();
        const raw = lines.filter(line => line.startsWith('data:')).map(line => line.slice(5).trim()).join('\n');
        if (!raw) continue;
        let data;
        try { data = JSON.parse(raw); }
        catch (_) { throw new Error('回复格式错误，回复未完成。'); }
        if (type === 'error') throw new Error(data.detail || '模型回复失败。');
        onEvent(type, data);
        if (type === 'done') return;
      }
      if (part.done) throw new Error('连接中断，回复未完成，请重试。');
    }
  } finally {
    await reader.cancel().catch(() => {});
    reader.releaseLock();
  }
}
