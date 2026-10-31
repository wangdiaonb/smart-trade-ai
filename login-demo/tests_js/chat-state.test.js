import test from 'node:test';
import assert from 'node:assert/strict';
import {
  canOpenConversation,
  contextNavigationState,
  isContinuationRequest,
  isChatBusy,
  shouldUseHermesTools,
} from '../static/chat-state.js';

test('context navigation preserves the current conversation and messages', () => {
  const state = {
    context: 'daily',
    conversationId: 7,
    messages: [{role: 'user', content: '继续找客户'}],
    chatController: new AbortController(),
  };
  const next = contextNavigationState(state, 'lead');
  assert.equal(next.context, 'lead');
  assert.equal(next.conversationId, 7);
  assert.equal(next.messages, state.messages);
});

test('chat is busy while a request controller is active', () => {
  assert.equal(isChatBusy({chatController: new AbortController()}), true);
  assert.equal(isChatBusy({chatController: null}), false);
});

test('history may reopen the active conversation but not a different one', () => {
  const state = {conversationId: 7, chatController: new AbortController()};
  assert.equal(canOpenConversation(state, 7), true);
  assert.equal(canOpenConversation(state, 8), false);
  assert.equal(canOpenConversation({conversationId: null, chatController: null}, 8), true);
});

test('short conversational continuations do not start the full Hermes tool agent', () => {
  assert.equal(isContinuationRequest('继续'), true);
  assert.equal(isContinuationRequest('请接着上面的回答继续写'), true);
  assert.equal(shouldUseHermesTools(true, '继续'), false);
  assert.equal(shouldUseHermesTools(true, '继续查一下越南官网'), true);
  assert.equal(shouldUseHermesTools(true, '分析这个客户'), true);
});

test('continuation retries the tool agent after a failed tool turn', () => {
  assert.equal(shouldUseHermesTools(true, '继续', true), true);
  assert.equal(shouldUseHermesTools(true, '继续', false), false);
});
