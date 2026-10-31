import test from 'node:test';
import assert from 'node:assert/strict';
import {
  elapsedLabel,
  thinkingLabel,
  thinkingStage,
  thinkingText,
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
});

test('local progress text is honest when the model has no reasoning stream', () => {
  assert.equal(thinkingText({active: true, statusText: '正在整理业务上下文'}), '正在整理业务上下文');
  assert.equal(thinkingText({active: false, statusText: '正在组织回答', thinking: ''}), '处理完成。');
  assert.equal(thinkingText({active: false, thinking: '模型返回的推理内容'}), '模型返回的推理内容');
});
