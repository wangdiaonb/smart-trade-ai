import {api} from './api.js';

const el = id => document.getElementById(id);
let active = false, epoch = 0, lifetime, editingAutomation = null, skills = [], customers = [];

function message(text, target = 'research-message') { el(target).textContent = text; }
function option(value, text) { const item=document.createElement('option'); item.value=String(value); item.textContent=text; return item; }
function empty(target, text) { const p=document.createElement('p'); p.className='section-description'; p.textContent=text; target.replaceChildren(p); }
function record(title, detail) { const row=document.createElement('div');row.className='record-row';const body=document.createElement('div');const strong=document.createElement('strong');strong.textContent=title;const p=document.createElement('p');p.textContent=detail;body.append(strong,p);const actions=document.createElement('div');actions.className='record-actions';row.append(body,actions);return {row,actions}; }
function button(text, task, danger=false) { const b=document.createElement('button');b.type='button';b.className=danger?'text-button danger-text':'text-button';b.textContent=text;b.addEventListener('click',()=>run(task));return b; }
function run(task, target='business-message') { const owner=epoch; return Promise.resolve().then(()=>{if(active)return task(()=>active&&owner===epoch);}).catch(error=>{if(active&&owner===epoch&&error.name!=='AbortError')message(error.message,target);}); }
async function download(path, name) { const response=await api(path,{raw:true,signal:lifetime.signal});const owner=epoch;const data=await response.blob();if(!active||owner!==epoch)return;const url=URL.createObjectURL(data);const link=document.createElement('a');link.href=url;link.download=name;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000); }

async function loadDashboard() {
  const owner=epoch;
  const [data,company]=await Promise.all([
    api('/api/dashboard',{signal:lifetime.signal}),
    api('/api/company',{signal:lifetime.signal}),
  ]);
  if(!active||owner!==epoch)return;
  el('dashboard-company').textContent=`${company.name} · ${company.products||'尚未填写主营产品'}`;
  const definitions=[
    ['customers','客户','位'],['open_orders','进行中订单','张'],['documents','文档','份'],
    ['conversations','对话','段'],['automations','启用自动化','个'],['templates','文案模板','份'],
  ];
  el('metric-grid').replaceChildren(...definitions.map(([key,label,unit])=>{const item=document.createElement('div');item.className='metric';const number=document.createElement('strong');number.textContent=String(data.counts[key]||0);const text=document.createElement('span');text.textContent=`${label} · ${unit}`;item.append(number,text);return item;}));
  const orders=document.createDocumentFragment();
  for(const order of data.recent_orders){const {row}=record(`${order.order_no||'未编号订单'} · ${order.customer_name}`,`${order.status} · ${order.currency} ${order.total_amount??'待谈'}`);orders.append(row);}
  el('dashboard-orders').replaceChildren(orders);if(!data.recent_orders.length)empty(el('dashboard-orders'),'还没有订单。');
  const tasks=document.createDocumentFragment();
  for(const task of data.next_tasks){const {row}=record(task.name,`${task.frequency==='daily'?'每天':task.frequency==='weekdays'?'工作日':'每周'} ${task.time_of_day} · ${new Date(task.next_run_at).toLocaleString('zh-CN')}`);tasks.append(row);}
  el('dashboard-tasks').replaceChildren(tasks);if(!data.next_tasks.length)empty(el('dashboard-tasks'),'还没有启用自动化。');
}

async function loadSkillsAndCustomers() {
  const owner=epoch;
  [skills,customers]=await Promise.all([
    api('/api/chat/skills',{signal:lifetime.signal}),
    api('/api/customers?limit=100',{signal:lifetime.signal}).then(data=>data.items),
  ]);
  if(!active||owner!==epoch)return;
  el('research-customer').replaceChildren(option('','不关联客户'),...customers.map(customer=>option(customer.id,customer.name)));
  el('automation-skill').replaceChildren(...skills.map(skill=>option(skill.id,skill.name)));
}

async function loadResearch() {
  const owner=epoch;
  const [settings,reports]=await Promise.all([
    api('/api/research/settings',{signal:lifetime.signal}),
    api('/api/research/reports',{signal:lifetime.signal}),
  ]);
  if(!active||owner!==epoch)return;
  el('research-key-state').textContent=settings.has_key?'已保存 Tavily Key':'尚未配置 Tavily Key';
  el('research-settings-form').elements.namedItem('api_key').value='';
  const fragment=document.createDocumentFragment();
  for(const report of reports){
    const {row,actions}=record(report.query,`${report.status==='success'?'已完成':'失败'} · ${report.customer_name||'未关联客户'} · ${report.source_count||0} 个来源 · ${new Date(report.created_at).toLocaleString('zh-CN')}`);
    actions.append(button('查看',()=>showReport(report.id)));
    fragment.append(row);
  }
  el('research-reports').replaceChildren(fragment);if(!reports.length)empty(el('research-reports'),'还没有客户情报记录。');
}

async function showReport(id) {
  const owner=epoch;const report=await api(`/api/research/reports/${id}`,{signal:lifetime.signal});if(!active||owner!==epoch)return;
  el('research-report-title').textContent=report.query;
  el('research-report-meta').textContent=`${report.status==='success'?'完成':'失败'} · ${new Date(report.created_at).toLocaleString('zh-CN')}${report.error?' · '+report.error:''}`;
  el('research-report-answer').textContent=report.answer||report.error||'没有可用摘要。';
  el('research-sources').replaceChildren(...report.sources.map(source=>{const a=document.createElement('a');a.href=source.url;a.target='_blank';a.rel='noopener noreferrer';a.textContent=source.title||source.url;const p=document.createElement('p');p.textContent=source.content;const item=document.createElement('div');item.className='source-item';item.append(a,p);return item;}));
  el('research-report-dialog').showModal();
}

function automationSchedule(task){return task.frequency==='daily'?'每天':task.frequency==='weekdays'?'工作日':'每周';}
async function loadAutomations() {
  const owner=epoch;
  const [tasks,runs]=await Promise.all([
    api('/api/automations',{signal:lifetime.signal}),api('/api/automation-runs',{signal:lifetime.signal}),
  ]);
  if(!active||owner!==epoch)return;
  const fragment=document.createDocumentFragment();
  for(const task of tasks){
    const {row,actions}=record(task.name,`${automationSchedule(task)} ${task.time_of_day} · ${task.enabled?'已启用':'已暂停'} · 下次 ${new Date(task.next_run_at).toLocaleString('zh-CN')}`);
    actions.append(button('立即运行',()=>runAutomation(task.id)),button('编辑',()=>openAutomation(task)),button(task.enabled?'暂停':'启用',()=>toggleAutomation(task)),button('删除',()=>deleteAutomation(task),true));
    fragment.append(row);
  }
  el('automations-list').replaceChildren(fragment);if(!tasks.length)empty(el('automations-list'),'还没有自动化任务。');
  const history=document.createDocumentFragment();
  for(const entry of runs){
    const {row,actions}=record(`${entry.automation_name} · ${entry.status==='success'?'成功':'失败'}`,`${new Date(entry.finished_at).toLocaleString('zh-CN')}${entry.error?' · '+entry.error:''}`);
    if(entry.output)actions.append(button('查看输出',()=>{el('research-report-title').textContent=entry.automation_name;el('research-report-meta').textContent=`运行于 ${new Date(entry.finished_at).toLocaleString('zh-CN')}`;el('research-report-answer').textContent=entry.output;el('research-sources').replaceChildren();el('research-report-dialog').showModal();}));
    history.append(row);
  }
  el('automation-runs').replaceChildren(history);if(!runs.length)empty(el('automation-runs'),'还没有运行记录。');
}

async function runAutomation(id){
  const owner=epoch;
  await api(`/api/automations/${id}/run`,{method:'POST',signal:lifetime.signal});
  if(active&&owner===epoch)await loadAutomations();
}
function fillAutomation(form,task={}){form.reset();for(const input of form.elements)if(input.name&&Object.hasOwn(task,input.name)){if(input.type==='checkbox')input.checked=Boolean(task[input.name]);else input.value=String(task[input.name]);}}
function openAutomation(task=null){editingAutomation=task?.id??null;fillAutomation(el('automation-form'),task||{skill_id:'b2b-daily-automation',frequency:'daily',time_of_day:'09:00',weekday:0,enabled:true});el('automation-title').textContent=task?'编辑自动化':'新建自动化';el('automation-message').textContent='';el('automation-dialog').showModal();}
async function toggleAutomation(task){await api(`/api/automations/${task.id}`,{method:'PUT',body:{enabled:!task.enabled},signal:lifetime.signal});await loadAutomations();}
async function deleteAutomation(task){
  // Reuse the dedicated confirmation dialog to avoid an unchecked destructive action.
  el('delete-description').textContent=`确定删除自动化“${task.name}”及其运行记录吗？`;
  el('delete-message').textContent='';
  const submit=el('delete-form').querySelector('[type=submit]');
  el('delete-form').dataset.automationId=String(task.id);
  el('delete-dialog').showModal();
  submit.textContent='确认删除任务';
}

el('research-settings-form').addEventListener('submit',event=>{event.preventDefault();const body=Object.fromEntries(new FormData(el('research-settings-form')));run(async valid=>{const result=await api('/api/research/settings',{method:'PUT',body,signal:lifetime.signal});if(!valid())return;el('research-key-state').textContent=result.has_key?'已保存 Tavily Key':'尚未配置 Tavily Key';message('搜索配置已保存。');});});
el('clear-research-key').addEventListener('click',()=>run(async valid=>{await api('/api/research/settings',{method:'PUT',body:{clear_key:true},signal:lifetime.signal});if(!valid())return;el('research-key-state').textContent='尚未配置 Tavily Key';message('已清除搜索密钥。');}));
el('research-form').addEventListener('submit',event=>{event.preventDefault();const values=Object.fromEntries(new FormData(el('research-form')));const body={query:values.query};if(values.customer_id)body.customer_id=Number(values.customer_id);const submit=event.submitter;submit.disabled=true;run(async valid=>{const report=await api('/api/research/search',{method:'POST',body,signal:lifetime.signal});if(!valid())return;message('搜索完成，已保存带来源的报告。');await loadResearch();await showReport(report.id);},'research-message').finally(()=>{submit.disabled=false;});});
el('new-automation').addEventListener('click',()=>openAutomation());
el('automation-form').addEventListener('submit',event=>{event.preventDefault();const raw=Object.fromEntries(new FormData(el('automation-form')));const body={...raw,weekday:Number(raw.weekday),enabled:raw.enabled==='on'};run(async valid=>{await api(editingAutomation?`/api/automations/${editingAutomation}`:'/api/automations',{method:editingAutomation?'PUT':'POST',body,signal:lifetime.signal});if(!valid())return;el('automation-dialog').close();await loadAutomations();},'automation-message');});
document.querySelectorAll('[data-jump]').forEach(button=>button.addEventListener('click',()=>window.dispatchEvent(new CustomEvent('workspace-navigate',{detail:button.dataset.jump}))));
el('quick-chat').addEventListener('click',()=>window.dispatchEvent(new CustomEvent('workspace-navigate',{detail:'chat'})));
document.querySelectorAll('[data-close]').forEach(button=>button.addEventListener('click',()=>el(button.dataset.close).close()));

export function startPlatform(){stopPlatform();active=true;lifetime=new AbortController();run(()=>Promise.all([loadDashboard(),loadSkillsAndCustomers()]));}
export function stopPlatform(){active=false;epoch++;lifetime?.abort();['metric-grid','dashboard-orders','dashboard-tasks','research-reports','automations-list','automation-runs'].forEach(id=>el(id).replaceChildren());el('automation-form').reset();el('research-form').reset();el('research-settings-form').reset();editingAutomation=null;skills=[];customers=[];['business-message','research-message','automation-message'].forEach(id=>message('',id));}
window.addEventListener('workspace-view',event=>{if(!active)return;if(event.detail==='dashboard')run(()=>loadDashboard());if(event.detail==='research')run(()=>Promise.all([loadSkillsAndCustomers(),loadResearch()]));if(event.detail==='automations')run(()=>Promise.all([loadSkillsAndCustomers(),loadAutomations()]));});
