import {api} from './api.js';
import {readSSE} from './sse.js';

const app = document.getElementById('app');
const dialog = document.getElementById('app-dialog');
const dialogTitle = document.getElementById('dialog-title');
const dialogBody = document.getElementById('dialog-body');
const sidebar = document.getElementById('sidebar');

const CONTEXTS = {
  daily: {title:'今日简报', skill:'b2b-daily-automation', intro:'整理今天最值得处理的客户、订单和跟进事项。', prompts:['生成今天的早安简报','总结本周客户跟进进度','今天应该优先联系哪些客户？']},
  lead: {title:'客户开发', skill:'b2b-lead-generation', intro:'告诉我你卖什么、目标市场，以及想找哪类客户。', prompts:['帮我制定本周客户开发计划','根据产品定位筛选目标客户类型','生成一套多通道获客流程']},
  platform: {title:'网站诊断', skill:'b2b-platform', intro:'粘贴 B2B 平台、公司官网或独立站链接，分析内容和转化问题。', prompts:['分析我的产品页有什么转化问题','为独立站设计询盘优化方案','评估阿里国际站产品标题']},
  social: {title:'社媒营销', skill:'b2b-social-media', intro:'规划 Facebook、Instagram、TikTok、YouTube 等渠道内容。', prompts:['生成本周社媒内容日历','把产品卖点改成短视频选题','设计一组客户案例帖子']},
  linkedin: {title:'LinkedIn 营销', skill:'b2b-linkedin-marketing', intro:'优化 LinkedIn 主页、内容计划和客户开发流程。', prompts:['优化我的 LinkedIn Profile','生成一个月 LinkedIn 内容计划','设计 LinkedIn 客户开发六步流程']},
  customs: {title:'海关数据', skill:'b2b-customs-data', intro:'描述要分析的市场、产品或上传的数据；涉及实时数据时会说明需要核验。', prompts:['分析欧洲水泵采购市场','设计海关数据分析维度','如何用进口记录筛选采购商？']},
  docgen: {title:'文档生成', skill:'b2b-doc-generation', intro:'描述要生成的报价单、PI、合同或业务方案。', prompts:['生成一份报价单内容','起草一份 PI','为欧洲客户准备商业提案']},
  docs: {title:'文档库问答', skill:'b2b-document', intro:'选择当前文档库中的资料后提问，或直接粘贴需要分析的内容。', prompts:['概括所选文档的重点','从产品资料中提取报价参数','分析合同中的付款和交期条款']},
};
const VIEW_TITLES = {customers:'客户管理',documents:'文档库',osint:'客户背调',tasks:'定时任务',history:'对话记录'};
const state = {
  company:null,email:'',customers:[],libraries:[],skills:[],settings:null,
  view:'chat',context:'daily',conversationId:null,messages:[],chatController:null,
  chatCustomerId:null,chatDocumentId:null,libraryId:null,webSearch:true,
};

function esc(value) {
  return String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
}
function md(text) {
  if (window.marked && window.DOMPurify) {
    return DOMPurify.sanitize(marked.parse(text || '', {breaks:true,gfm:true}));
  }
  return esc(text).replace(/\n/g,'<br>');
}
function toast(text, type='') {
  const item=document.createElement('div');item.className=`toast ${type}`;item.textContent=text;
  document.getElementById('toast-container').append(item);
  setTimeout(()=>item.remove(),4000);
}
function showDialog(title, content, onOpen) {
  dialogTitle.textContent=title;dialogBody.innerHTML=content;dialog.showModal();
  onOpen?.(dialogBody);
}
function closeDialog(){if(dialog.open)dialog.close();}
function setActive(key) {
  document.querySelectorAll('.nav-item').forEach(item=>{
    const active=item.dataset.context===key||item.dataset.view===key;
    item.classList.toggle('active',active);
  });
}
function closeMobile(){sidebar.classList.remove('open');}
function safeError(error) {
  if (error.name==='AbortError') return;
  toast(error.message||'操作失败','error');
}

async function loadBootstrap() {
  const [me,company,companies,skills,settings,customers,libraries]=await Promise.all([
    api('/api/me'),api('/api/company'),api('/api/companies'),api('/api/chat/skills'),api('/api/model-settings'),
    api('/api/customers?limit=100'),api('/api/libraries'),
  ]);
  state.email=me.email;state.company=company;state.skills=skills;state.settings=settings;
  state.customers=customers.items||[];state.libraries=libraries||[];
  document.getElementById('account-email').textContent=me.email;
  const select=document.getElementById('company-select');
  select.innerHTML=companies.map(item=>`<option value="${item.id}" ${item.id===company.id?'selected':''}>${esc(item.name)}</option>`).join('');
  select.addEventListener('change',async()=>{
    try{await api(`/api/companies/${select.value}/select`,{method:'POST',body:{}});location.reload();}
    catch(error){safeError(error);select.value=String(company.id);}
  });
}

function contextButtons(ctx) {
  return CONTEXTS[ctx].prompts.map(text=>`<button type="button" class="prompt-chip" data-prompt="${esc(text)}">${esc(text)}</button>`).join('');
}
function renderChat(ctx=state.context,title=CONTEXTS[ctx]?.title||'AI 对话') {
  state.view='chat';state.context=ctx;setActive(ctx);closeMobile();
  const context=CONTEXTS[ctx]||CONTEXTS.daily;
  const messages=state.messages.length?state.messages.map(message=>`
    <article class="message ${message.role}">
      <div class="msg-avatar">${message.role==='user'?'你':'AI'}</div>
      <div class="msg-body" data-message-id="${message.id||''}">${message.role==='assistant'?md(message.content):esc(message.content)}</div>
    </article>`).join(''):`
    <div class="chat-empty">
      <div class="empty-symbol">✦</div><h2>${esc(title)}</h2><p>${esc(context.intro)}</p>
      <div class="prompt-chips">${contextButtons(ctx)}</div>
    </div>`;
  app.innerHTML=`
    <div class="chat-view">
      <div class="chat-topbar">
        <div class="chat-badges"><h2>${esc(title)}</h2><span class="chat-context-tag" style="display:inline-flex">${esc(context.skill)}</span></div>
        <div class="chat-selectors">
          <select id="chat-customer" aria-label="关联客户"><option value="">不关联客户</option>${state.customers.map(c=>`<option value="${c.id}" ${String(state.chatCustomerId)===String(c.id)?'selected':''}>${esc(c.name)}</option>`).join('')}</select>
          <select id="chat-document" aria-label="参考文档"><option value="">不参考文档</option>${state.libraries.flatMap(lib=>lib._documents||[]).map(doc=>`<option value="${doc.id}" ${String(state.chatDocumentId)===String(doc.id)?'selected':''}>${esc(doc.filename)}</option>`).join('')}</select>
          <label class="chat-web-search"><input id="chat-web-search" type="checkbox" ${state.webSearch?'checked':''}>联网搜索</label>
        </div>
        <div class="chat-topbar-actions"><button id="new-conversation" type="button">＋ 新对话</button></div>
      </div>
      <div class="chat-messages" id="chat-messages">${messages}</div>
      <form class="chat-input-area" id="chat-form">
        <div class="chat-input-inner">
          <textarea id="chat-input" rows="2" maxlength="20000" placeholder="输入任何业务问题，按 Enter 发送，Shift+Enter 换行"></textarea>
          <button id="chat-send" type="submit" aria-label="发送">↑</button>
          <button id="chat-stop" type="button" hidden>■</button>
        </div>
      </form>
    </div>`;
  bindChat();
  requestAnimationFrame(()=>{const box=document.getElementById('chat-messages');box.scrollTop=box.scrollHeight;});
}
function bindChat() {
  document.getElementById('chat-customer').addEventListener('change',event=>{state.chatCustomerId=event.target.value?Number(event.target.value):null;});
  document.getElementById('chat-document').addEventListener('change',event=>{state.chatDocumentId=event.target.value?Number(event.target.value):null;});
  document.getElementById('chat-web-search').addEventListener('change',event=>{state.webSearch=event.target.checked;});
  document.getElementById('new-conversation').addEventListener('click',()=>{state.conversationId=null;state.messages=[];state.chatCustomerId=null;state.chatDocumentId=null;renderChat();});
  app.querySelectorAll('[data-prompt]').forEach(button=>button.addEventListener('click',()=>{
    const input=document.getElementById('chat-input');input.value=button.dataset.prompt;input.focus();
  }));
  document.getElementById('chat-stop').addEventListener('click',()=>{state.chatController?.abort();});
  document.getElementById('chat-form').addEventListener('submit',sendChat);
  document.getElementById('chat-input').addEventListener('keydown',event=>{
    if(event.key==='Enter'&&!event.shiftKey){event.preventDefault();document.getElementById('chat-form').requestSubmit();}
  });
}
async function sendChat(event) {
  event.preventDefault();
  const input=document.getElementById('chat-input');
  const content=input.value.trim();
  if(!content)return;
  const context=CONTEXTS[state.context]||CONTEXTS.daily;
  if(!state.settings?.has_key){openModelSettings();toast('请先配置模型 API Key','error');return;}
  state.messages.push({role:'user',content});state.messages.push({role:'assistant',content:''});
  const assistant=state.messages.at(-1);state.chatController=new AbortController();
  input.value='';
  renderChat();
  document.getElementById('chat-send').disabled=true;
  document.getElementById('chat-stop').hidden=false;
  try {
    if(!state.conversationId){
      const body={title:content.slice(0,80)};
      if(state.chatCustomerId)body.customer_id=state.chatCustomerId;
      const thread=await api('/api/conversations',{method:'POST',body,signal:state.chatController.signal});
      state.conversationId=thread.id;
    }
    const response=await api(`/api/conversations/${state.conversationId}/stream`,{
      method:'POST',body:{content,skill_id:context.skill,document_ids:state.chatDocumentId?[state.chatDocumentId]:[],web_search:state.webSearch},
      raw:true,signal:state.chatController.signal,
    });
    await readSSE(response,(type,data)=>{
      if(type==='sources'){
        assistant.sources=data.sources||[];
        const body=document.querySelector('.message.assistant:last-of-type .msg-body');
        if(body)body.innerHTML=md(assistant.content)+sourceLinks(assistant.sources);
      }
      if(type==='delta'){
        assistant.content+=data.content;
        const body=document.querySelector(`.message.assistant:last-of-type .msg-body`);
        if(body){body.innerHTML=md(assistant.content)+sourceLinks(assistant.sources);const box=document.getElementById('chat-messages');box.scrollTop=box.scrollHeight;}
      }
    });
    toast('回复已生成','success');
  } catch(error) {
    if(error.name==='AbortError'){toast('已停止生成');}
    else{safeError(error);if(state.messages.at(-1)?.content==='')state.messages.pop();renderChat();}
  } finally {
    state.chatController=null;
    const send=document.getElementById('chat-send');if(send)send.disabled=false;
    const stop=document.getElementById('chat-stop');if(stop)stop.hidden=true;
  }
}

function sourceLinks(sources=[]){
  if(!sources.length)return '';
  return `<div class="sources"><div class="sources-title">公开信息来源</div>${sources.map(source=>`<a href="${esc(source.url)}" target="_blank" rel="noopener noreferrer">${esc(source.title||source.url)}</a>`).join('<br>')}</div>`;
}

async function loadAllDocuments() {
  await Promise.all(state.libraries.map(async lib=>{
    lib._documents=await api(`/api/libraries/${lib.id}/files`);
  }));
}
async function renderCustomers() {
  state.view='customers';setActive('customers');closeMobile();
  state.customers=(await api('/api/customers?limit=100')).items||[];
  app.innerHTML=`
    <div class="panel-view">
      <div class="panel-topbar"><h2>客户管理</h2><div class="panel-topbar-actions">
        <input id="customer-search" class="panel-search" placeholder="搜索客户..." aria-label="搜索客户">
        <select id="customer-tier" class="panel-search" aria-label="客户等级"><option value="">全部等级</option><option>A</option><option>B</option><option>C</option></select>
        <button class="btn btn-primary" id="add-customer" type="button">＋ 添加客户</button>
      </div></div>
      <div class="panel-body">
        <div class="section-toolbar" style="margin-bottom:12px;"><button class="btn-xs" id="import-customers" type="button">📥 CSV 导入</button><button class="btn-xs" id="export-customers" type="button">📤 导出客户</button><input id="customer-file" type="file" accept=".csv" hidden></div>
        <table class="data-table"><thead><tr><th>客户信息</th><th>联系人</th><th>国家</th><th>等级</th><th>操作</th></tr></thead><tbody id="customer-rows"></tbody></table>
        <div id="customer-empty" class="empty-state hidden"><div class="empty-icon">👤</div><h2>暂无客户</h2><p>添加客户或导入 CSV 开始管理。</p></div>
      </div>
    </div>`;
  drawCustomerRows();
  document.getElementById('customer-search').addEventListener('input',drawCustomerRows);
  document.getElementById('customer-tier').addEventListener('change',drawCustomerRows);
  document.getElementById('add-customer').addEventListener('click',()=>customerEditor());
  document.getElementById('import-customers').addEventListener('click',()=>document.getElementById('customer-file').click());
  document.getElementById('customer-file').addEventListener('change',async event=>{
    const file=event.target.files[0];if(!file)return;
    try{const result=await api('/api/customers/import',{method:'POST',body:{content:await file.text()}});toast(`成功导入 ${result.imported} 个客户`,'success');renderCustomers();}
    catch(error){safeError(error);}
  });
  document.getElementById('export-customers').addEventListener('click',async()=>{
    try{const response=await api('/api/customers/export',{raw:true});const url=URL.createObjectURL(await response.blob());const link=document.createElement('a');link.href=url;link.download='customers.csv';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
    catch(error){safeError(error);}
  });
}
function drawCustomerRows() {
  const query=(document.getElementById('customer-search')?.value||'').toLowerCase();
  const tier=document.getElementById('customer-tier')?.value||'';
  const rows=state.customers.filter(c=>(!query||`${c.name} ${c.contact} ${c.email}`.toLowerCase().includes(query))&&(!tier||c.tier===tier));
  const tbody=document.getElementById('customer-rows');
  tbody.innerHTML=rows.map(c=>`<tr class="customer-row" data-id="${c.id}" tabindex="0">
    <td><strong>${esc(c.name)}</strong><div class="muted">${esc(c.main_category||c.company_website||'')}</div></td>
    <td>${esc(c.contact||'—')}<div class="muted">${esc(c.email||'')}</div></td>
    <td>${esc(c.country||'—')}</td><td><strong>${esc(c.tier||'未分级')}</strong></td>
    <td><button class="btn-xs" type="button" data-edit-customer="${c.id}">编辑</button></td>
  </tr>`).join('');
  document.getElementById('customer-empty').classList.toggle('hidden',rows.length>0);
  tbody.querySelectorAll('.customer-row').forEach(row=>{
    row.addEventListener('click',event=>{if(!event.target.closest('[data-edit-customer]'))openCustomerDetail(Number(row.dataset.id));});
    row.addEventListener('keydown',event=>{if(event.key==='Enter')openCustomerDetail(Number(row.dataset.id));});
  });
  tbody.querySelectorAll('[data-edit-customer]').forEach(button=>button.addEventListener('click',()=>customerEditor(Number(button.dataset.editCustomer))));
}
function customerEditor(id=null) {
  const c=state.customers.find(item=>item.id===id)||{tier:'',match_score:0};
  showDialog(id?'编辑客户':'添加客户',`<form id="customer-form" class="form-grid">
    <div class="form-group full"><label>公司名称 *</label><input name="name" required maxlength="200" value="${esc(c.name||'')}"></div>
    <div class="form-group"><label>联系人</label><input name="contact" value="${esc(c.contact||'')}"></div>
    <div class="form-group"><label>职位</label><input name="title" value="${esc(c.title||'')}"></div>
    <div class="form-group"><label>邮箱</label><input name="email" type="email" value="${esc(c.email||'')}"></div>
    <div class="form-group"><label>备用邮箱</label><input name="backup_email" type="email" value="${esc(c.backup_email||'')}"></div>
    <div class="form-group"><label>国家</label><input name="country" value="${esc(c.country||'')}"></div>
    <div class="form-group"><label>客户等级</label><select name="tier"><option value="">未分级</option>${['A','B','C'].map(v=>`<option ${c.tier===v?'selected':''}>${v}</option>`).join('')}</select></div>
    <div class="form-group"><label>买家类型</label><input name="buyer_type" value="${esc(c.buyer_type||'')}"></div>
    <div class="form-group"><label>主营品类</label><input name="main_category" value="${esc(c.main_category||'')}"></div>
    <div class="form-group"><label>公司网站</label><input name="company_website" value="${esc(c.company_website||'')}"></div>
    <div class="form-group"><label>LinkedIn</label><input name="linkedin_url" value="${esc(c.linkedin_url||'')}"></div>
    <div class="form-group"><label>电话 / WhatsApp</label><input name="phone" value="${esc(c.phone||c.whatsapp||'')}"></div>
    <div class="form-group"><label>来源</label><input name="source" value="${esc(c.source||'manual')}"></div>
    <div class="form-group"><label>匹配度（0–5）</label><input name="match_score" type="number" min="0" max="5" step="1" value="${Number(c.match_score||0)}"></div>
    <div class="form-group full"><label>备注 / 跟进项目</label><textarea name="note" rows="3">${esc(c.note||'')}</textarea></div>
    <div class="form-group full"><label>AI 跟进建议</label><textarea name="follow_up_note" rows="2">${esc(c.follow_up_note||'')}</textarea></div>
    <div class="full dialog-actions"><button class="btn" type="button" data-close>取消</button><button class="btn btn-primary" type="submit">保存</button></div>
  </form>`);
  dialogBody.querySelector('[data-close]').addEventListener('click',closeDialog);
  dialogBody.querySelector('#customer-form').addEventListener('submit',async event=>{
    event.preventDefault();const body=Object.fromEntries(new FormData(event.target));body.match_score=Number(body.match_score||0);
    try{
      if(id)await api(`/api/customers/${id}`,{method:'PUT',body});
      else await api('/api/customers',{method:'POST',body});
      closeDialog();toast(id?'客户已更新':'客户已添加','success');state.customers=(await api('/api/customers?limit=100')).items;drawCustomerRows();
    }catch(error){safeError(error);}
  });
}
async function openCustomerDetail(id) {
  try{
    const [customer,orders,customerLibraries,allLibraries]=await Promise.all([
      api(`/api/customers/${id}`),api('/api/orders'),api(`/api/customers/${id}/libraries`),api('/api/libraries'),
    ]);
    const ownOrders=orders.filter(o=>o.customer_id===id);
    showDialog(customer.name,`
      <div class="customer-detail-grid">
        ${[['联系人',customer.contact],['职位',customer.title],['邮箱',customer.email],['国家',customer.country],['等级',customer.tier],['买家类型',customer.buyer_type],['主营品类',customer.main_category],['网站',customer.company_website]].map(([label,value])=>`<div class="customer-detail-field"><label>${label}</label>${esc(value||'—')}</div>`).join('')}
      </div>
      ${customer.note?`<div class="detail-section"><h4>备注</h4><p>${esc(customer.note)}</p></div>`:''}
      <div class="detail-section"><h4>关联文档库</h4>
        <div class="simple-list">${customerLibraries.length?customerLibraries.map(lib=>`<div class="simple-item"><span>${esc(lib.name)}</span><button class="btn-xs" data-unlink-lib="${lib.id}" type="button">取消关联</button></div>`).join(''):'<div class="empty-list">暂无关联文档库</div>'}</div>
        <div class="section-toolbar" style="margin-top:8px"><select id="link-library-select" class="panel-search"><option value="">选择文档库</option>${allLibraries.filter(lib=>!customerLibraries.some(linked=>linked.id===lib.id)).map(lib=>`<option value="${lib.id}">${esc(lib.name)}</option>`).join('')}</select><button class="btn-xs" id="link-library" type="button">关联</button></div>
      </div>
      <div class="detail-section"><div class="section-toolbar" style="justify-content:space-between"><h4>订单</h4><button class="btn-xs primary" id="new-order" type="button">＋ 新增订单</button></div>
        <div class="simple-list">${ownOrders.length?ownOrders.map(o=>`<div class="simple-item"><div><strong>${esc(o.order_no||'未编号订单')}</strong><br><small>${esc(o.status)} · ${esc(o.currency)} ${esc(o.total_amount??'待谈')}</small></div><button class="btn-xs" data-edit-order="${o.id}" type="button">编辑</button></div>`).join(''):'<div class="empty-list">暂无订单</div>'}</div>
      </div>
      <div class="dialog-actions"><button class="btn" type="button" id="edit-customer">编辑客户</button><button class="btn btn-danger" type="button" id="delete-customer">删除客户</button><button class="btn btn-primary" type="button" id="chat-customer-action">与此客户对话</button></div>`);
    dialogBody.querySelector('[data-close]')?.addEventListener('click',closeDialog);
    dialogBody.querySelector('#edit-customer').addEventListener('click',()=>{closeDialog();customerEditor(id);});
    dialogBody.querySelector('#chat-customer-action').addEventListener('click',()=>{closeDialog();state.chatCustomerId=id;state.conversationId=null;state.messages=[];renderChat('lead','客户: '+customer.name);});
    dialogBody.querySelector('#new-order').addEventListener('click',()=>orderEditor(null,id));
    dialogBody.querySelector('#link-library').addEventListener('click',async()=>{
      const libraryId=Number(document.getElementById('link-library-select').value);if(!libraryId)return;
      try{await api(`/api/customers/${id}/libraries/${libraryId}`,{method:'POST'});await openCustomerDetail(id);toast('文档库已关联','success');}catch(error){safeError(error);}
    });
    dialogBody.querySelectorAll('[data-unlink-lib]').forEach(button=>button.addEventListener('click',async()=>{
      try{await api(`/api/customers/${id}/libraries/${button.dataset.unlinkLib}`,{method:'DELETE'});await openCustomerDetail(id);toast('已取消关联');}catch(error){safeError(error);}
    }));
    dialogBody.querySelectorAll('[data-edit-order]').forEach(button=>button.addEventListener('click',()=>orderEditor(Number(button.dataset.editOrder))));
    dialogBody.querySelector('#delete-customer').addEventListener('click',async()=>{
      if(!confirm(`确定删除“${customer.name}”？`))return;
      try{await api(`/api/customers/${id}`,{method:'DELETE'});closeDialog();toast('客户已删除');await renderCustomers();}catch(error){safeError(error);}
    });
  }catch(error){safeError(error);}
}
async function orderEditor(id=null,customerId=null) {
  const existing=id?await api(`/api/orders/${id}`):null;
  const cid=existing?.customer_id||customerId;
  const customer=state.customers.find(c=>c.id===cid);
  const items=existing?.items?.length?existing.items:[{product_name:'',quantity:'',unit:'',unit_price:''}];
  showDialog(id?'编辑订单':'新增订单',`<form id="order-form">
    <div class="form-group"><label>客户</label><input value="${esc(customer?.name||'')}" disabled></div>
    <div class="form-grid"><div class="form-group"><label>订单号</label><input name="order_no" value="${esc(existing?.order_no||'')}"></div><div class="form-group"><label>币种</label><select name="currency">${['USD','EUR','CNY','GBP'].map(v=>`<option ${existing?.currency===v?'selected':''}>${v}</option>`).join('')}</select></div><div class="form-group"><label>状态</label><select name="status">${['报价中','已下单','已出货','已完成','已取消'].map(v=>`<option ${existing?.status===v?'selected':''}>${v}</option>`).join('')}</select></div><div class="form-group"><label>交期</label><input name="delivery_date" type="date" value="${esc((existing?.delivery_date||'').slice(0,10))}"></div></div>
    <div class="detail-section"><div class="section-toolbar" style="justify-content:space-between"><h4>商品明细</h4><button class="btn-xs" id="add-item" type="button">＋ 商品</button></div><div id="order-items">${items.map(item=>orderItemHtml(item)).join('')}</div></div>
    <div class="form-group"><label>付款条款</label><input name="payment_terms" value="${esc(existing?.payment_terms||'')}"></div>
    <div class="form-group"><label>备注</label><textarea name="notes" rows="2">${esc(existing?.notes||'')}</textarea></div>
    <div class="dialog-actions"><button class="btn" type="button" id="cancel-order">取消</button><button class="btn btn-primary" type="submit">保存订单</button></div>
  </form>`);
  dialogBody.querySelector('#cancel-order').addEventListener('click',()=>openCustomerDetail(cid));
  dialogBody.querySelector('#add-item').addEventListener('click',()=>document.getElementById('order-items').insertAdjacentHTML('beforeend',orderItemHtml({})));
  dialogBody.querySelector('#order-form').addEventListener('submit',async event=>{
    event.preventDefault();const form=event.target;
    const items=[...form.querySelectorAll('.order-item')].map(row=>{
      const item={product_name:row.querySelector('[data-field=name]').value.trim(),quantity:row.querySelector('[data-field=quantity]').value||null,unit:row.querySelector('[data-field=unit]').value,unit_price:row.querySelector('[data-field=price]').value||null};
      return item;
    }).filter(item=>item.product_name);
    const body={customer_id:cid,order_no:form.elements.order_no.value,currency:form.elements.currency.value,status:form.elements.status.value,delivery_date:form.elements.delivery_date.value,payment_terms:form.elements.payment_terms.value,notes:form.elements.notes.value,items};
    try{await api(id?`/api/orders/${id}`:'/api/orders',{method:id?'PUT':'POST',body});toast('订单已保存','success');openCustomerDetail(cid);}catch(error){safeError(error);}
  });
}
function orderItemHtml(item) {
  return `<div class="order-item"><div class="form-grid" style="margin-bottom:10px"><div class="form-group full"><label>商品名称</label><input data-field="name" value="${esc(item.product_name||'')}" required></div><div class="form-group"><label>数量</label><input data-field="quantity" type="number" min="0" step="any" value="${esc(item.quantity??'')}"></div><div class="form-group"><label>单位</label><input data-field="unit" value="${esc(item.unit||'')}"></div><div class="form-group"><label>单价（留空=待谈）</label><input data-field="price" type="number" min="0" step="any" value="${esc(item.unit_price??'')}"></div></div></div>`;
}

async function renderDocuments() {
  state.view='documents';setActive('documents');closeMobile();
  state.libraries=await api('/api/libraries');await loadAllDocuments();
  const active=state.libraries.find(lib=>lib.id===state.libraryId)||state.libraries[0];
  state.libraryId=active?.id||null;
  app.innerHTML=`<div class="panel-view"><div class="panel-topbar"><h2>文档库</h2><div class="panel-topbar-actions"><button class="btn btn-primary" id="add-library" type="button">＋ 添加文档库</button></div></div><div class="panel-body">
    <div class="form-group" style="margin-bottom:14px"><label>当前文档库</label><select id="library-select">${state.libraries.length?state.libraries.map(lib=>`<option value="${lib.id}" ${lib.id===state.libraryId?'selected':''}>${esc(lib.name)}</option>`).join(''):'<option value="">暂无文档库</option>'}</select></div>
    ${active?.root_path?`<div class="document-upload"><div style="flex:1"><small class="settings-note">本地文件夹：${esc(active.root_path)}</small></div><button class="btn-xs" id="scan-library" type="button">扫描文件夹</button></div>`:''}
    <form class="document-upload" id="upload-form"><label>上传文件<input id="upload-file" type="file" required accept=".txt,.md,.csv,.pdf,.docx,.xlsx,.png,.jpg,.jpeg,.webp"></label><button class="btn btn-primary" type="submit" ${state.libraryId?'':'disabled'}>上传</button></form>
    <div class="simple-list" id="document-list"></div>
  </div></div>`;
  drawDocuments();
  document.getElementById('add-library').addEventListener('click',libraryEditor);
  document.getElementById('library-select').addEventListener('change',event=>{state.libraryId=Number(event.target.value);drawDocuments();});
  document.getElementById('scan-library')?.addEventListener('click',async event=>{
    event.target.disabled=true;
    try{const result=await api(`/api/libraries/${state.libraryId}/scan`,{method:'POST'});toast(`扫描完成，找到 ${result.found} 个可读文件`,'success');await renderDocuments();}
    catch(error){safeError(error);event.target.disabled=false;}
  });
  document.getElementById('upload-form').addEventListener('submit',async event=>{
    event.preventDefault();const file=document.getElementById('upload-file').files[0];if(!file||!state.libraryId)return;
    const form=new FormData();form.append('file',file);
    try{const doc=await api(`/api/libraries/${state.libraryId}/files`,{method:'POST',body:form});toast(`已上传 ${doc.filename}`,'success');await renderDocuments();}catch(error){safeError(error);}
  });
}
function drawDocuments() {
  const lib=state.libraries.find(item=>item.id===state.libraryId);
  const docs=lib?._documents||[];
  const target=document.getElementById('document-list');
  target.innerHTML=docs.length?docs.map(doc=>`<div class="simple-item"><div><strong>${esc(doc.filename)}</strong><br><small>${(doc.size/1024).toFixed(1)} KB · ${esc(doc.extraction_note)}</small></div><div class="simple-actions"><button class="btn-xs" type="button" data-text="${doc.id}">查看文字</button><button class="btn-xs" type="button" data-download="${doc.id}" data-name="${esc(doc.filename)}">下载</button></div></div>`).join(''):'<div class="empty-list">这个文档库还没有文件。</div>';
  target.querySelectorAll('[data-text]').forEach(button=>button.addEventListener('click',async()=>{
    try{const data=await api(`/api/documents/${button.dataset.text}/text`);showDialog(data.filename,`<p class="settings-note">${esc(data.note)}</p><pre class="preview-text">${esc(data.text||'未提取到文字')}</pre><div class="dialog-actions"><button class="btn" data-close>关闭</button></div>`);dialogBody.querySelector('[data-close]').addEventListener('click',closeDialog);}catch(error){safeError(error);}
  }));
  target.querySelectorAll('[data-download]').forEach(button=>button.addEventListener('click',()=>download(`/api/documents/${button.dataset.download}/download`,button.dataset.name)));
}
function libraryEditor() {
  showDialog('添加文档库',`<form id="library-form"><div class="form-group"><label>库名称 *</label><input name="name" required maxlength="200"></div><div class="form-group"><label>本地文件夹路径</label><input name="root_path" maxlength="2000" placeholder="例如：C:\\Users\\你的用户名\\Documents\\客户资料"></div><p class="settings-note">可以留空并稍后通过页面上传。关联文件夹后，可在文档库页面扫描文本、PDF、Office 文件和常见图片。</p><div class="form-group"><label>描述</label><input name="description" maxlength="2000"></div><div class="dialog-actions"><button class="btn" type="button" data-close>取消</button><button class="btn btn-primary" type="submit">添加</button></div></form>`);
  dialogBody.querySelector('[data-close]').addEventListener('click',closeDialog);
  dialogBody.querySelector('#library-form').addEventListener('submit',async event=>{event.preventDefault();try{const body=Object.fromEntries(new FormData(event.target));await api('/api/libraries',{method:'POST',body});closeDialog();await renderDocuments();toast('文档库已创建','success');}catch(error){safeError(error);}});
}

async function renderTasks() {
  state.view='tasks';setActive('tasks');closeMobile();
  const [tasks,runs]=await Promise.all([api('/api/automations'),api('/api/automation-runs')]);
  app.innerHTML=`<div class="panel-view"><div class="panel-topbar"><h2>定时任务</h2><div class="panel-topbar-actions"><button class="btn btn-primary" id="add-task" type="button">＋ 新建任务</button></div></div><div class="panel-body">
    <div class="panel-section"><div class="panel-section-title">任务模板</div><div class="prompt-chips" style="justify-content:flex-start">${[['早安简报','生成今天的早安简报，汇总客户跟进、订单进度和业务行动。'],['客户跟进','根据客户列表和订单，列出今天应优先跟进的客户。'],['LinkedIn 内容','生成本周 LinkedIn 内容计划。'],['市场简报','整理目标市场本周值得关注的公开信息。']].map(([title,prompt])=>`<button class="prompt-chip" data-template="${esc(prompt)}" data-name="${title}" type="button">${title}</button>`).join('')}</div></div>
    <div class="simple-list">${tasks.length?tasks.map(task=>`<div class="simple-item"><div><strong>${esc(task.name)}</strong><br><small>${task.frequency==='daily'?'每天':task.frequency==='weekdays'?'工作日':'每周'} ${esc(task.time_of_day)} · ${task.enabled?'已启用':'已暂停'} · 下次 ${new Date(task.next_run_at).toLocaleString('zh-CN')}</small></div><div class="simple-actions"><button class="btn-xs primary" type="button" data-run="${task.id}">立即执行</button><button class="btn-xs" type="button" data-task="${task.id}">编辑</button></div></div>`).join(''):'<div class="empty-list">暂无定时任务</div>'}</div>
    <div class="detail-section"><h4>最近运行</h4><div class="simple-list">${runs.length?runs.map(run=>`<div class="simple-item"><div><strong>${esc(run.automation_name)} · ${run.status==='success'?'成功':'失败'}</strong><br><small>${new Date(run.finished_at).toLocaleString('zh-CN')} ${esc(run.error||'')}</small></div>${run.output?`<button class="btn-xs" data-output="${esc(run.output)}" type="button">查看结果</button>`:''}</div>`).join(''):'<div class="empty-list">暂无运行记录</div>'}</div></div>
  </div></div>`;
  document.getElementById('add-task').addEventListener('click',()=>taskEditor());
  app.querySelectorAll('[data-template]').forEach(button=>button.addEventListener('click',()=>taskEditor(null,{name:button.dataset.name,prompt:button.dataset.template})));
  app.querySelectorAll('[data-task]').forEach(button=>button.addEventListener('click',()=>taskEditor(Number(button.dataset.task))));
  app.querySelectorAll('[data-run]').forEach(button=>button.addEventListener('click',async()=>{button.disabled=true;try{await api(`/api/automations/${button.dataset.run}/run`,{method:'POST'});toast('任务已执行','success');await renderTasks();}catch(error){safeError(error);button.disabled=false;}}));
  app.querySelectorAll('[data-output]').forEach(button=>button.addEventListener('click',()=>{showDialog('运行结果',`<div class="preview-text">${esc(button.dataset.output)}</div><div class="dialog-actions"><button class="btn" data-close>关闭</button></div>`);dialogBody.querySelector('[data-close]').addEventListener('click',closeDialog);}));
}
async function taskEditor(id=null,preset={}) {
  const task=id?await api(`/api/automations/${id}`):preset;
  showDialog(id?'编辑任务':'新建任务',`<form id="task-form" class="form-grid">
    <div class="form-group full"><label>任务名称</label><input name="name" required maxlength="200" value="${esc(task.name||'')}"></div>
    <div class="form-group full"><label>执行指令</label><textarea name="prompt" rows="5" required>${esc(task.prompt||'')}</textarea></div>
    <div class="form-group"><label>业务技能</label><select name="skill_id">${state.skills.map(skill=>`<option value="${skill.id}" ${task.skill_id===skill.id?'selected':''}>${esc(skill.name)}</option>`).join('')}</select></div>
    <div class="form-group"><label>频率</label><select name="frequency"><option value="daily" ${task.frequency==='daily'?'selected':''}>每天</option><option value="weekdays" ${task.frequency==='weekdays'?'selected':''}>工作日</option><option value="weekly" ${task.frequency==='weekly'?'selected':''}>每周</option></select></div>
    <div class="form-group"><label>时间</label><input name="time_of_day" type="time" value="${esc(task.time_of_day||'09:00')}"></div>
    <div class="form-group"><label>每周执行日</label><select name="weekday">${['周一','周二','周三','周四','周五','周六','周日'].map((n,i)=>`<option value="${i}" ${Number(task.weekday||0)===i?'selected':''}>${n}</option>`).join('')}</select></div>
    <div class="dialog-actions full"><button class="btn" type="button" data-close>取消</button><button class="btn btn-primary" type="submit">保存</button></div>
  </form>`);
  dialogBody.querySelector('[data-close]').addEventListener('click',closeDialog);
  dialogBody.querySelector('#task-form').addEventListener('submit',async event=>{event.preventDefault();const values=Object.fromEntries(new FormData(event.target));values.weekday=Number(values.weekday);values.enabled=true;try{await api(id?`/api/automations/${id}`:'/api/automations',{method:id?'PUT':'POST',body:values});closeDialog();await renderTasks();toast('任务已保存','success');}catch(error){safeError(error);}});
}

async function renderOsint() {
  state.view='osint';setActive('osint');closeMobile();
  const [settings,reports]=await Promise.all([api('/api/research/settings'),api('/api/research/reports')]);
  app.innerHTML=`<div class="panel-view"><div class="panel-topbar"><h2>客户背调</h2><button class="btn-xs" id="research-settings" type="button">搜索配置</button></div><div class="panel-body">
    <form id="research-form" class="document-upload"><label style="flex:2">目标邮箱、域名、官网或核验问题<input id="research-query" required maxlength="2000" placeholder="例如：buyer@acme.com 或 acme.com"></label><label>关联客户<select id="research-customer"><option value="">不关联客户</option>${state.customers.map(c=>`<option value="${c.id}">${esc(c.name)}</option>`).join('')}</select></label><button class="btn btn-primary" type="submit">搜索公开信息</button><button class="btn" id="deep-research" type="button">深度背调</button></form>
    <p class="settings-note">${settings.has_key?'已配置 Tavily 搜索。':'尚未配置 Tavily 搜索，可点击右上角配置。'}</p>
    <div class="simple-list">${reports.length?reports.map(report=>`<div class="simple-item"><div><strong>${esc(report.query)}</strong><br><small>${report.status==='success'?'完成':'失败'} · ${report.customer_name||'未关联客户'} · ${report.source_count||0} 个来源 · ${new Date(report.created_at).toLocaleString('zh-CN')}</small></div><button class="btn-xs" type="button" data-report="${report.id}">查看</button></div>`).join(''):'<div class="empty-list">暂无背调记录</div>'}</div>
  </div></div>`;
  document.getElementById('research-settings').addEventListener('click',openResearchSettings);
  document.getElementById('deep-research').addEventListener('click',async()=>{
    const target=document.getElementById('research-query').value.trim();if(!target)return;
    const cid=document.getElementById('research-customer').value;const body={target};if(cid)body.customer_id=Number(cid);
    const button=document.getElementById('deep-research');button.disabled=true;button.textContent='背调中…';
    try{const report=await api('/api/research/deep',{method:'POST',body});showReport(report);await renderOsint();}
    catch(error){safeError(error);}
    finally{const current=document.getElementById('deep-research');if(current){current.disabled=false;current.textContent='深度背调';}}
  });
  document.getElementById('research-form').addEventListener('submit',async event=>{
    event.preventDefault();const query=document.getElementById('research-query').value.trim();const cid=document.getElementById('research-customer').value;
    try{const body={query};if(cid)body.customer_id=Number(cid);const report=await api('/api/research/search',{method:'POST',body});showReport(report);await renderOsint();}catch(error){safeError(error);}
  });
  app.querySelectorAll('[data-report]').forEach(button=>button.addEventListener('click',async()=>{try{showReport(await api(`/api/research/reports/${button.dataset.report}`));}catch(error){safeError(error);}}));
}
function showReport(report) {
  const details=report.details||{};
  const layers=details.layers&&typeof details.layers==='object'?Object.entries(details.layers).map(([name,layer])=>`<details style="margin:8px 0"><summary>${esc(name)}</summary><pre class="preview-text">${esc(JSON.stringify(layer,null,2))}</pre></details>`).join(''):'';
  const flags=Array.isArray(details.flags)&&details.flags.length?`<p class="error-text">风险标记：${details.flags.map(esc).join('、')}</p>`:'';
  showDialog(report.query,`<p class="settings-note">${esc(report.error||'公开信息摘要')}</p><div class="preview-text">${esc(report.answer||'没有可用摘要')}</div>${flags}<div class="simple-list" style="margin-top:12px">${(details.recommendations||[]).map(item=>`<div class="simple-item">${esc(item)}</div>`).join('')}</div>${layers}<h4 style="margin:16px 0 8px">来源</h4><div class="simple-list">${(report.sources||[]).map(source=>`<div class="simple-item"><div><a href="${esc(source.url)}" target="_blank" rel="noopener noreferrer">${esc(source.title||source.url)}</a><br><small>${esc(source.content)}</small></div></div>`).join('')||'<div class="empty-list">深度背调不使用搜索来源时会列出各检测层。</div>'}</div><div class="dialog-actions"><button class="btn" data-close>关闭</button></div>`);
  dialogBody.querySelector('[data-close]').addEventListener('click',closeDialog);
}

async function renderHistory() {
  state.view='history';setActive('history');closeMobile();
  const conversations=await api('/api/conversations');
  app.innerHTML=`<div class="panel-view"><div class="panel-topbar"><h2>对话记录</h2></div><div class="panel-body"><div class="simple-list">${conversations.length?conversations.map(c=>`<div class="simple-item"><div><strong>${esc(c.title)}</strong><br><small>${new Date(c.updated_at).toLocaleString('zh-CN')}</small></div><div class="simple-actions"><button class="btn-xs" type="button" data-open-chat="${c.id}">打开</button><button class="btn-xs" type="button" data-delete-chat="${c.id}">删除</button></div></div>`).join(''):'<div class="empty-list">暂无对话记录</div>'}</div></div></div>`;
  app.querySelectorAll('[data-open-chat]').forEach(button=>button.addEventListener('click',async()=>{try{const thread=await api(`/api/conversations/${button.dataset.openChat}`);state.conversationId=thread.id;state.messages=thread.messages;const skill=thread.messages.at(-1)?.skill_id||'general';state.context=Object.entries(CONTEXTS).find(([,v])=>v.skill===skill)?.[0]||'daily';renderChat(state.context,thread.title);}catch(error){safeError(error);}}));
  app.querySelectorAll('[data-delete-chat]').forEach(button=>button.addEventListener('click',async()=>{if(!confirm('确定删除这段对话？'))return;try{await api(`/api/conversations/${button.dataset.deleteChat}`,{method:'DELETE'});await renderHistory();toast('对话已删除');}catch(error){safeError(error);}}));
}

function openModelSettings() {
  showDialog('模型设置',`<form id="model-form" class="model-form"><label>模型名称<input name="model" required value="${esc(state.settings?.model||'deepseek-chat')}"></label><label>API Key<input name="api_key" type="password" maxlength="1000" placeholder="${state.settings?.has_key?'已保存；留空保留':'填写 API Key'}"></label><p class="settings-note">模型密钥只保存在本机并加密。对话会提交当前公司资料、所选客户和文档内容。</p><div class="dialog-actions"><button class="btn" type="button" data-close>取消</button><button class="btn btn-primary" type="submit">保存</button></div></form>`);
  dialogBody.querySelector('[data-close]').addEventListener('click',closeDialog);
  dialogBody.querySelector('#model-form').addEventListener('submit',async event=>{event.preventDefault();const values=Object.fromEntries(new FormData(event.target));try{state.settings=await api('/api/model-settings',{method:'PUT',body:values});closeDialog();toast('模型设置已保存','success');}catch(error){safeError(error);}});
}
async function openResearchSettings() {
  const current=await api('/api/research/settings');
  showDialog('客户背调配置',`<form id="research-settings-form" class="model-form"><label>Tavily API Key<input name="api_key" type="password" maxlength="1000" placeholder="${current.has_key?'已保存；留空保留':'填写 Tavily API Key'}"></label><p class="settings-note">该密钥只用于当前账号的客户情报搜索。</p><div class="dialog-actions"><button class="btn" type="button" data-close>取消</button><button class="btn btn-primary" type="submit">保存</button></div></form>`);
  dialogBody.querySelector('[data-close]').addEventListener('click',closeDialog);
  dialogBody.querySelector('#research-settings-form').addEventListener('submit',async event=>{event.preventDefault();const values=Object.fromEntries(new FormData(event.target));try{await api('/api/research/settings',{method:'PUT',body:values});closeDialog();toast('搜索配置已保存','success');await renderOsint();}catch(error){safeError(error);}});
}
function openCompanySettings() {
  const c=state.company;
  showDialog('公司设置',`<form id="company-form" class="form-grid"><div class="form-group full"><label>公司名称</label><input name="name" required value="${esc(c.name||'')}"></div><div class="form-group"><label>联系人</label><input name="contact_name" value="${esc(c.contact_name||'')}"></div><div class="form-group"><label>邮箱</label><input name="contact_email" type="email" value="${esc(c.contact_email||'')}"></div><div class="form-group"><label>官网</label><input name="website" value="${esc(c.website||'')}"></div><div class="form-group"><label>行业</label><input name="industry" value="${esc(c.industry||'')}"></div><div class="form-group full"><label>地址</label><input name="address" value="${esc(c.address||'')}"></div><div class="form-group full"><label>主营产品</label><textarea name="products" rows="3">${esc(c.products||'')}</textarea></div><div class="form-group full"><label>Agent 身份设定</label><textarea name="agent_identity_md" rows="4">${esc(c.agent_identity_md||'')}</textarea></div><div class="dialog-actions full"><button class="btn" type="button" data-close>取消</button><button class="btn btn-primary" type="submit">保存</button></div></form>`);
  dialogBody.querySelector('[data-close]').addEventListener('click',closeDialog);
  dialogBody.querySelector('#company-form').addEventListener('submit',async event=>{event.preventDefault();try{state.company=await api('/api/company',{method:'PUT',body:Object.fromEntries(new FormData(event.target))});closeDialog();document.querySelector('#company-select option').textContent=state.company.name;toast('公司资料已保存','success');}catch(error){safeError(error);}});
}
function openCompanyCreate() {
  showDialog('添加公司',`<form id="company-create-form" class="form-grid"><div class="form-group full"><label>公司名称 *</label><input name="name" required maxlength="200"></div><div class="form-group"><label>联系人</label><input name="contact_name"></div><div class="form-group"><label>邮箱</label><input name="contact_email" type="email"></div><div class="form-group"><label>官网</label><input name="website"></div><div class="form-group"><label>行业</label><input name="industry"></div><div class="form-group full"><label>主营产品</label><textarea name="products" rows="3"></textarea></div><div class="dialog-actions full"><button class="btn" type="button" data-close>取消</button><button class="btn btn-primary" type="submit">创建并切换</button></div></form>`);
  dialogBody.querySelector('[data-close]').addEventListener('click',closeDialog);
  dialogBody.querySelector('#company-create-form').addEventListener('submit',async event=>{
    event.preventDefault();
    try{await api('/api/companies',{method:'POST',body:Object.fromEntries(new FormData(event.target))});location.reload();}
    catch(error){safeError(error);}
  });
}
function openSkillsHelp() {
  showDialog(`全部 ${state.skills.length} 个业务技能`,`<p class="settings-note">技能会按当前业务入口自动使用。你也可以在对话提示中写明需要的技能。</p><div class="skill-grid">${state.skills.map(skill=>`<div class="skill-card"><strong>${esc(skill.name)}</strong><p>${esc(skill.description)}</p></div>`).join('')}</div><div class="dialog-actions"><button class="btn" data-close>关闭</button></div>`);
  dialogBody.querySelector('[data-close]').addEventListener('click',closeDialog);
}
function openOnboarding() {
  showDialog('欢迎使用 Trade AI','<div class="onboarding-card" style="padding:28px;border-radius:14px"><div style="font-size:42px;text-align:center">🎉</div><h3 style="text-align:center;margin:12px 0">从第一次客户开发开始</h3><p class="settings-note" style="text-align:center;margin-bottom:18px">先在“公司设置”补齐产品与定位，再到“客户管理”添加客户，随后可使用今日简报、开发信、背调和定时任务。</p><div class="simple-list"><div class="simple-item">🏢 完善公司资料</div><div class="simple-item">👤 添加第一位客户</div><div class="simple-item">💬 从客户开发开始对话</div></div><div class="dialog-actions"><button class="btn" id="onboard-later" type="button">稍后</button><button class="btn btn-primary" id="onboard-start" type="button">开始客户开发</button></div></div>');
  dialogBody.querySelector('#onboard-later').addEventListener('click',closeDialog);
  dialogBody.querySelector('#onboard-start').addEventListener('click',()=>{closeDialog();newChat('lead');});
}
function newChat(ctx){state.context=ctx;state.conversationId=null;state.messages=[];state.chatCustomerId=null;state.chatDocumentId=null;renderChat(ctx);}
async function download(path,name){try{const response=await api(path,{raw:true});const url=URL.createObjectURL(await response.blob());const a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}catch(error){safeError(error);}}

document.querySelectorAll('[data-context]').forEach(item=>item.addEventListener('click',()=>newChat(item.dataset.context)));
document.querySelectorAll('[data-view]').forEach(item=>item.addEventListener('click',()=>{
  const view=item.dataset.view;
  if(view==='customers')renderCustomers().catch(safeError);
  if(view==='documents')renderDocuments().catch(safeError);
  if(view==='osint')renderOsint().catch(safeError);
  if(view==='tasks')renderTasks().catch(safeError);
  if(view==='history')renderHistory().catch(safeError);
}));
document.getElementById('company-settings').addEventListener('click',openCompanySettings);
document.getElementById('company-add').addEventListener('click',openCompanyCreate);
document.getElementById('model-settings-button').addEventListener('click',openModelSettings);
document.getElementById('skills-help-button').addEventListener('click',openSkillsHelp);
document.getElementById('onboarding-button').addEventListener('click',openOnboarding);
document.getElementById('logout-button').addEventListener('click',async()=>{try{await api('/api/logout',{method:'POST',body:{}});}finally{location.href='/';}});
document.getElementById('mobile-open').addEventListener('click',()=>sidebar.classList.add('open'));
document.getElementById('mobile-close').addEventListener('click',closeMobile);
document.getElementById('dialog-close').addEventListener('click',closeDialog);
window.addEventListener('session-expired',()=>{location.href='/';});

(async function init(){
  try{
    await loadBootstrap();
    await loadAllDocuments();
    renderChat('daily','今日简报');
  }catch(error){
    if(error.status===401)location.href='/';
    else{app.innerHTML=`<div class="workspace-loading"><div class="error-text">${esc(error.message)}</div></div>`;}
  }
})();
