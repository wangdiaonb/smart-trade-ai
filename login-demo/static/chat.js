import {api} from './api.js';
import {readSSE} from './sse.js';

const el = id => document.getElementById(id);
let active = false;
let epoch = 0;
let lifetime;
let streamController;
let currentId = null;
let generating = false;
let selectionNumber = 0;

function showError(error, target = 'chat-message') {
  if (error.name !== 'AbortError') el(target).textContent = error.message;
}

function setBusy(value) {
  generating = value;
  el('send-chat').disabled = value;
  el('stop-chat').hidden = !value;
  el('new-conversation').disabled = value;
  el('chat-customer').disabled = value || currentId !== null;
  el('delete-conversation').disabled = value || currentId === null;
  el('conversation-list').querySelectorAll('button').forEach(button => { button.disabled = value; });
}

function newConversation() {
  currentId = null;
  selectionNumber++;
  el('chat-messages').replaceChildren();
  const intro = document.createElement('div');
  intro.className = 'chat-welcome';
  const title = document.createElement('h2'); title.textContent = '今天先处理哪件事？';
  const text = document.createElement('p'); text.textContent = '选择工作模式和关联客户，开始一段新的对话。';
  intro.append(title, text); el('chat-messages').append(intro);
  el('chat-input').value = ''; el('chat-message').textContent = '';
  el('chat-customer').value = ''; setBusy(false);
}

function addMessage(role, content, status = 'complete') {
  const article = document.createElement('article'); article.className = `chat-bubble ${role}`;
  const label = document.createElement('span'); label.className = 'message-role'; label.textContent = role === 'user' ? '你' : '业务助手';
  const text = document.createElement('div'); text.className = 'message-content'; text.textContent = content;
  const state = document.createElement('small'); state.className = 'message-state';
  state.textContent = {error:'回复未完成',cancelled:'已停止',streaming:'生成中…'}[status] || '';
  article.append(label, text, state); el('chat-messages').append(article);
  el('chat-messages').scrollTop = el('chat-messages').scrollHeight;
  return {text, state};
}

async function loadThreads() {
  const owner = epoch;
  const threads = await api('/api/conversations', {signal: lifetime.signal});
  if (!active || owner !== epoch) return;
  const fragment = document.createDocumentFragment();
  for (const thread of threads) {
    const button = document.createElement('button'); button.type = 'button';
    button.className = 'conversation-button'; button.textContent = thread.title;
    if (thread.id === currentId) button.classList.add('is-active');
    button.disabled = generating;
    button.addEventListener('click', () => selectThread(thread.id).catch(showError)); fragment.append(button);
  }
  el('conversation-list').replaceChildren(fragment);
}

async function selectThread(id) {
  if (generating) return;
  const owner = epoch;
  const sequence = ++selectionNumber;
  const thread = await api(`/api/conversations/${id}`, {signal: lifetime.signal});
  if (!active || owner !== epoch || sequence !== selectionNumber) return;
  currentId = id; el('chat-messages').replaceChildren();
  thread.messages.forEach(message => addMessage(message.role, message.content, message.status));
  el('chat-customer').value = thread.customer_id ? String(thread.customer_id) : '';
  setBusy(false); el('chat-message').textContent = ''; await loadThreads();
}

async function loadSettings() {
  const owner = epoch;
  const [settings, memory, skills, customers] = await Promise.all([
    api('/api/model-settings', {signal:lifetime.signal}), api('/api/memory', {signal:lifetime.signal}),
    api('/api/chat/skills', {signal:lifetime.signal}), api('/api/customers?limit=100', {signal:lifetime.signal}),
  ]);
  if (!active || owner !== epoch) return;
  const form = el('model-form'); form.elements.namedItem('model').value = settings.model;
  form.elements.namedItem('api_key').value = '';
  el('model-key-state').textContent = settings.has_key ? '已保存 API Key（不会回传明文）；留空可保留。' : '尚未配置 API Key';
  el('chat-model-label').textContent = settings.has_key ? settings.model : '请先到“模型与记忆”配置 API Key';
  el('memory-content').value = memory.content;
  el('chat-skill').replaceChildren(...skills.map(skill => {
    const option = document.createElement('option'); option.value = skill.id; option.textContent = skill.name; return option;
  }));
  const unbound = document.createElement('option'); unbound.value=''; unbound.textContent='不关联客户';
  el('chat-customer').replaceChildren(unbound, ...customers.items.map(customer => {
    const option = document.createElement('option'); option.value=String(customer.id); option.textContent=customer.name; return option;
  }));
}

export async function startChat() {
  stopChat(); active=true; lifetime=new AbortController();
  newConversation(); await Promise.all([loadSettings(), loadThreads()]);
}

export function stopChat() {
  active=false; epoch++; selectionNumber++;
  lifetime?.abort(); streamController?.abort();
  const dialog = el('delete-chat-dialog'); if (dialog.open) dialog.close();
  el('conversation-list').replaceChildren(); el('chat-messages').replaceChildren();
  el('model-form').reset(); el('memory-form').reset(); el('chat-form').reset();
  ['chat-message','model-message','memory-message'].forEach(id => { el(id).textContent=''; });
  el('chat-model-label').textContent='请先配置模型'; el('model-key-state').textContent='尚未配置 API Key';
  el('chat-customer').replaceChildren(); currentId=null; setBusy(false);
}

el('new-conversation').addEventListener('click', () => { newConversation(); loadThreads().catch(showError); });

el('chat-form').addEventListener('submit', async event => {
  event.preventDefault();
  if (!active || generating) return;
  const content=el('chat-input').value.trim(); if (!content) return;
  const owner=epoch; setBusy(true); el('chat-message').textContent='';
  let reply;
  let streamId;
  streamController=new AbortController();
  try {
    if (currentId === null) {
      const customerId=el('chat-customer').value;
      const thread=await api('/api/conversations', {method:'POST',body:{...(customerId ? {customer_id:Number(customerId)} : {})},signal:streamController.signal});
      if (!active || owner !== epoch) return;
      currentId=thread.id; el('chat-messages').replaceChildren();
    }
    streamId=currentId;
    addMessage('user',content); reply=addMessage('assistant','', 'streaming');
    const response=await api(`/api/conversations/${streamId}/stream`, {method:'POST',body:{content,skill_id:el('chat-skill').value},raw:true,signal:streamController.signal});
    el('chat-input').value='';
    await readSSE(response, (type,data) => {
      if (!active || owner !== epoch) return;
      if (type==='delta') { reply.text.textContent += data.content; el('chat-messages').scrollTop=el('chat-messages').scrollHeight; }
      if (type==='done') reply.state.textContent='';
    });
  } catch (error) {
    if (!active || owner!==epoch) return;
    if (reply) reply.state.textContent=error.name==='AbortError' ? '已停止' : '回复未完成';
    showError(error);
  } finally {
    if (active && owner===epoch) { setBusy(false); loadThreads().catch(showError); }
  }
});

el('stop-chat').addEventListener('click', async () => {
  const owner=epoch; const id=currentId;
  streamController?.abort();
  try { if (id!==null) await api(`/api/conversations/${id}/cancel`,{method:'POST',signal:lifetime.signal}); }
  catch(error) { if(active && owner===epoch) showError(error); }
});

el('delete-conversation').addEventListener('click',()=>el('delete-chat-dialog').showModal());
el('cancel-delete-chat').addEventListener('click',()=>el('delete-chat-dialog').close());
el('confirm-delete-chat').addEventListener('click',async()=>{
  const owner=epoch;
  try {
    await api(`/api/conversations/${currentId}`,{method:'DELETE',signal:lifetime.signal});
    if(!active || owner!==epoch)return;
    el('delete-chat-dialog').close(); newConversation(); await loadThreads();
  }catch(error){if(active && owner===epoch)showError(error);}
});

el('model-form').addEventListener('submit',async event=>{
  event.preventDefault(); const owner=epoch; const button=event.submitter; button.disabled=true;
  const body=Object.fromEntries(new FormData(el('model-form')));
  try {
    const settings=await api('/api/model-settings',{method:'PUT',body,signal:lifetime.signal});
    if(!active || owner!==epoch)return;
    el('model-form').elements.namedItem('api_key').value='';
    el('model-key-state').textContent=settings.has_key?'已保存 API Key（不会回传明文）。':'尚未配置 API Key';
    el('chat-model-label').textContent=settings.has_key?settings.model:'请先配置 API Key';
    el('model-message').textContent='模型设置已保存。';
  }catch(error){if(active && owner===epoch)showError(error,'model-message');}
  finally{if(active && owner===epoch)button.disabled=false;}
});
el('clear-model-key').addEventListener('click',async()=>{
  const owner=epoch;
  try{
    await api('/api/model-settings',{method:'PUT',body:{clear_key:true},signal:lifetime.signal});
    if(!active || owner!==epoch)return;
    el('model-form').elements.namedItem('api_key').value=''; el('model-key-state').textContent='尚未配置 API Key';
    el('chat-model-label').textContent='请先配置 API Key'; el('model-message').textContent='已清除保存的 API Key。';
  }catch(error){if(active && owner===epoch)showError(error,'model-message');}
});
el('memory-form').addEventListener('submit',async event=>{
  event.preventDefault(); const owner=epoch;
  try{
    await api('/api/memory',{method:'PUT',body:{content:el('memory-content').value},signal:lifetime.signal});
    if(active && owner===epoch)el('memory-message').textContent='业务记忆备注已保存。';
  }catch(error){if(active && owner===epoch)showError(error,'memory-message');}
});
