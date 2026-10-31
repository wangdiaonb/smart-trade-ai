import test from 'node:test';
import assert from 'node:assert/strict';
import {readSSE} from '../static/sse.js';

function response(chunks) {
  return new Response(new ReadableStream({start(controller) {
    for (const chunk of chunks) controller.enqueue(chunk);
    controller.close();
  }}));
}

test('reads UTF-8 and CRLF SSE split across arbitrary byte boundaries', async () => {
  const bytes = new TextEncoder().encode('event: delta\r\ndata: {"content":"你好"}\r\n\r\nevent: done\r\ndata: {}\r\n\r\n');
  const events = [];
  await readSSE(response([...bytes].map(byte => Uint8Array.of(byte))), (type, data) => events.push([type, data]));
  assert.deepEqual(events, [['delta',{content:'你好'}], ['done',{}]]);
});

test('does not treat a truncated response as completed', async () => {
  const bytes = new TextEncoder().encode('event: delta\ndata: {"content":"partial"}\n\n');
  await assert.rejects(readSSE(response([bytes]), () => {}), /未完成/);
});

test('turns an error terminal event into a visible failure', async () => {
  const bytes = new TextEncoder().encode('event: error\ndata: {"detail":"服务失败"}\n\n');
  await assert.rejects(readSSE(response([bytes]), () => {}), /服务失败/);
});
