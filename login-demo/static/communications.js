import {api} from './api.js';

const el=id=>document.getElementById(id);
let active=false,epoch=0,lifetime,customers=[],templates=[],pending=null;
function message(text,target='mail-message'){el(target).textContent=text;}
function empty(target,text){const p=document.createElement('p');p.className='section-description';p.textContent=text;target.replaceChildren(p);}
function option(value,text){const item=document.createElement('option');item.value=String(value);item.textContent=text;return item;}
async function guarded(task,target='mail-message'){const owner=epoch;if(!active)return;try{await task(()=>active&&owner===epoch);}catch(error){if(active&&owner===epoch&&error.name!=='AbortError')message(error.message,target);}}

function renderHistory(rows){
  const fragment=document.createDocumentFragment();
  for(const row of rows){
    const item=document.createElement('div');item.className='record-row';
    const body=document.createElement('div');const title=document.createElement('strong');title.textContent=row.subject;
    const detail=document.createElement('p');detail.textContent=`${row.status==='sent'?'已发送':'发送失败'} · ${row.recipient} · ${row.customer_name||'未关联客户'} · ${new Date(row.created_at).toLocaleString('zh-CN')}${row.error?' · '+row.error:''}`;
    body.append(title,detail);item.append(body);fragment.append(item);
  }
  el('mail-history').replaceChildren(fragment);if(!rows.length)empty(el('mail-history'),'还没有邮件发送记录。');
}

async function loadMail(){
  const owner=epoch;
  const [settings,customerData,templateData,history]=await Promise.all([
    api('/api/communications/settings',{signal:lifetime.signal}),
    api('/api/customers?limit=100',{signal:lifetime.signal}),
    api('/api/templates',{signal:lifetime.signal}),
    api('/api/communications/history',{signal:lifetime.signal}),
  ]);
  if(!active||owner!==epoch)return;
  customers=customerData.items;templates=templateData;
  const form=el('smtp-settings-form');
  for(const field of ['host','port','security','username','from_email'])form.elements.namedItem(field).value=settings[field];
  form.elements.namedItem('password').value='';
  el('smtp-password-state').textContent=settings.has_password?'已保存 SMTP 密码':'尚未保存 SMTP 密码';
  el('mail-customer').replaceChildren(option('','不关联客户'),...customers.map(customer=>option(customer.id,customer.name)));
  el('mail-template').replaceChildren(option('','不使用模板'),...templates.map(template=>option(template.id,template.name)));
  renderHistory(history);
}

function fillCustomer(){
  const id=el('mail-customer').value;
  const customer=customers.find(item=>String(item.id)===id);
  if(customer?.email&&!el('mail-to').value)el('mail-to').value=customer.email;
}
function fillTemplate(){
  const id=el('mail-template').value;
  const template=templates.find(item=>String(item.id)===id);
  if(!template)return;
  if(!el('mail-subject').value)el('mail-subject').value=template.name;
  el('mail-body').value=template.content;
}

el('mail-customer').addEventListener('change',fillCustomer);
el('mail-template').addEventListener('change',fillTemplate);
el('smtp-settings-form').addEventListener('submit',event=>{event.preventDefault();const body=Object.fromEntries(new FormData(el('smtp-settings-form')));guarded(async valid=>{const result=await api('/api/communications/settings',{method:'PUT',body,signal:lifetime.signal});if(!valid())return;el('smtp-settings-form').elements.namedItem('password').value='';el('smtp-password-state').textContent=result.has_password?'已保存 SMTP 密码':'尚未保存 SMTP 密码';message('SMTP 配置已保存。','smtp-message');},'smtp-message');});
el('clear-smtp-password').addEventListener('click',()=>{
  const form=el('smtp-settings-form');
  const host=form.elements.namedItem('host').value.trim();
  const fromEmail=form.elements.namedItem('from_email').value.trim();
  if(!host||!fromEmail){message('请先填写并保存 SMTP 主机和发件邮箱。','smtp-message');return;}
  guarded(async valid=>{await api('/api/communications/settings',{method:'PUT',body:{clear_password:true,host,from_email:fromEmail,port:Number(form.elements.namedItem('port').value),security:form.elements.namedItem('security').value,username:form.elements.namedItem('username').value},signal:lifetime.signal});if(!valid())return;el('smtp-password-state').textContent='尚未保存 SMTP 密码';message('已清除 SMTP 密码。','smtp-message');},'smtp-message');
});

el('mail-form').addEventListener('submit',event=>{
  event.preventDefault();
  const values=Object.fromEntries(new FormData(el('mail-form')));
  pending={to:values.to.trim(),subject:values.subject.trim(),body:values.body,customer_id:values.customer_id?Number(values.customer_id):null};
  el('send-mail-summary').textContent=`收件人：${pending.to} · 主题：${pending.subject}`;
  el('send-mail-preview').textContent=pending.body;
  el('send-mail-error').textContent='';
  el('send-mail-dialog').showModal();
});
el('confirm-send-mail').addEventListener('click',()=>{
  if(!pending)return;
  const button=el('confirm-send-mail');button.disabled=true;
  guarded(async valid=>{
    await api('/api/communications/send',{method:'POST',body:pending,signal:lifetime.signal});
    if(!valid())return;
    el('send-mail-dialog').close();pending=null;el('mail-form').reset();message('邮件已发送并记录。');await loadMail();
  },'send-mail-error').finally(()=>{button.disabled=false;});
});

export function startCommunications(){stopCommunications();active=true;lifetime=new AbortController();}
export function stopCommunications(){active=false;epoch++;lifetime?.abort();pending=null;const dialog=el('send-mail-dialog');if(dialog.open)dialog.close();['smtp-settings-form','mail-form'].forEach(id=>el(id).reset());el('mail-history').replaceChildren();el('mail-customer').replaceChildren();el('mail-template').replaceChildren();customers=[];templates=[];['smtp-message','mail-message','send-mail-error'].forEach(id=>message('',id));}
window.addEventListener('workspace-view',event=>{if(active&&event.detail==='communications')guarded(loadMail);});
