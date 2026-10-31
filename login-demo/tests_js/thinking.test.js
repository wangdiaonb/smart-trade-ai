import test from 'node:test';
import assert from 'node:assert/strict';
import {
  applyToolEvent,
  elapsedLabel,
  thinkingLabel,
  thinkingStage,
  thinkingText,
  toolLabel,
  toolStatusLabel,
} from '../static/thinking.js';

test('thinking stages advance while the model is preparing a reply', () => {
  assert.equal(thinkingStage(200), '正在理解你的问题');
  assert.equal(thinkingStage(1800), '正在整理业务上下文');
  assert.equal(thinkingStage(4200), '正在组织回答');
});

test('thinking summary reports elapsed time and completion state', () => {
  assert.equal(elapsedLabel(430), '不足 1 秒');
  assert.equal(elapsedLabel(6800), '7 秒');
  assert.equal(thinkingLabel({active: true, startedAt: 0}, 1800), '正在整理业务上下文');
  assert.equal(thinkingLabel({active: false, startedAt: 1000, durationMs: 6800}), '已完成思考 · 7 秒');
  assert.equal(thinkingLabel({
    active: false,
    startedAt: 1000,
    durationMs: 6800,
    tools: [{id: '1'}, {id: '2'}],
  }), '已完成思考 · 2 个工具 · 7 秒');
});

test('local progress text is honest when the model has no reasoning stream', () => {
  assert.equal(thinkingText({active: true, statusText: '正在整理业务上下文'}), '正在整理业务上下文');
  assert.equal(thinkingText({active: false, statusText: '正在组织回答', thinking: ''}), '处理完成。');
  assert.equal(thinkingText({active: false, thinking: '模型返回的推理内容'}), '模型返回的推理内容');
});

test('tool events keep the real tool name and update one timeline row', () => {
  const message = {tools: []};
  applyToolEvent(message, 'tool_start', {
    id: 'call-1',
    name: 'web_search',
    label: '网页搜索',
    detail: 'industrial pump buyers',
  });
  applyToolEvent(message, 'tool_result', {
    id: 'call-1',
    name: 'web_search',
    label: '网页搜索',
    detail: '找到 4 条公开来源',
    duration_ms: 2400,
  });

  assert.equal(message.tools.length, 1);
  assert.equal(message.tools[0].name, 'web_search');
  assert.equal(message.tools[0].status, 'complete');
  assert.equal(message.tools[0].durationMs, 2400);
  assert.equal(toolLabel('browser_navigate'), '浏览器操作');
  assert.equal(toolLabel('custom_unknown_tool'), '调用工具');
  assert.equal(toolStatusLabel('failed'), '执行失败');
});
