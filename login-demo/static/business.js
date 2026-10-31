import {api} from './api.js';
import {startChat, stopChat} from './chat.js';

const el = id => document.getElementById(id);
const companyForm = el('company-form');
const customerForm = el('customer-form');
const dialogs = ['customer-dialog', 'delete-dialog', 'import-dialog'];
let active = false;
let epoch = 0;
let controller;
let requestNumber = 0;
let offset = 0;
let total = 0;
let editing = null;
let deleting = null;
let rows = new Map();
const pageSize = 20;

function message(text = '', success = false) {
  el('business-message').textContent = text;
  el('business-message').classList.toggle('is-success', success);
}

function fillForm(form, values) {
  form.reset();
  for (const input of form.elements) {
    if (input.name && Object.hasOwn(values, input.name)) input.value = values[input.name] ?? '';
  }
}

function filters() {
  return new URLSearchParams(Object.fromEntries(new FormData(el('customer-search'))));
}

function cell(text, className = '') {
  const td = document.createElement('td');
  td.textContent = text || '—';
  td.className = className;
  return td;
}

function openCustomer(customer = null) {
  if (!active) return;
  editing = customer?.id ?? null;
  fillForm(customerForm, customer || {match_score: 0, source: 'manual'});
  el('customer-dialog-title').textContent = customer ? '编辑客户' : '新增客户';
  el('customer-form-message').textContent = '';
  el('customer-dialog').showModal();
  customerForm.elements.namedItem('name').focus();
}

function renderCustomers(data) {
  total = data.total;
  rows = new Map(data.items.map(row => [row.id, row]));
  const fragment = document.createDocumentFragment();
  for (const customer of data.items) {
    const tr = document.createElement('tr');
    const name = cell(customer.name, 'customer-name');
    const secondary = document.createElement('small');
    secondary.textContent = customer.company_website || customer.main_category || '';
    name.append(secondary);
    const contact = cell(customer.contact);
    const email = document.createElement('small');
    email.textContent = customer.email;
    contact.append(email);
    const tier = cell('');
    const badge = document.createElement('span');
    badge.className = `tier-badge tier-${customer.tier || 'none'}`;
    badge.textContent = customer.tier || '未分级';
    tier.replaceChildren(badge);
    const actions = cell('');
    actions.replaceChildren();
    for (const [label, handler] of [
      ['编辑', () => openCustomer(rows.get(customer.id))],
      ['删除', () => {
        deleting = customer.id;
        el('delete-description').textContent = `确定删除“${customer.name}”吗？`;
        el('delete-message').textContent = '';
        el('delete-dialog').showModal();
      }],
    ]) {
      const button = document.createElement('button');
      button.type = 'button'; button.className = 'text-button'; button.textContent = label;
      button.addEventListener('click', handler);
      actions.append(button);
    }
    tr.append(name, contact, cell(customer.country), tier, actions);
    fragment.append(tr);
  }
  el('customer-rows').replaceChildren(fragment);
  el('customer-count').textContent = String(total);
  el('list-summary').textContent = `共 ${total} 位客户`;
  const hasFilters = [...filters().values()].some(Boolean);
  el('customer-empty').hidden = total > 0;
  el('customer-empty').querySelector('h2').textContent = hasFilters ? '没有匹配的客户' : '从第一位客户开始';
  el('customer-empty').querySelector('p').textContent = hasFilters ? '调整搜索词或筛选条件后再试试。' : '点击“新增客户”，或导入现有的客户 CSV 文件。';
  el('page-summary').textContent = total ? `${offset + 1}–${Math.min(offset + pageSize, total)} / ${total}` : '';
  el('previous-page').disabled = offset === 0;
  el('next-page').disabled = offset + pageSize >= total;
}

async function loadCustomers() {
  const owner = epoch;
  const sequence = ++requestNumber;
  const params = filters();
  params.set('limit', String(pageSize)); params.set('offset', String(offset));
  const data = await api(`/api/customers?${params}`, {signal: controller.signal});
  if (!active || owner !== epoch || sequence !== requestNumber) return;
  if (data.total && offset >= data.total) { offset = Math.floor((data.total - 1) / pageSize) * pageSize; return loadCustomers(); }
  renderCustomers(data);
}

function action(button, task, errorTarget = null) {
  const owner = epoch;
  if (!active) return;
  button.disabled = true;
  const stillActive = () => active && epoch === owner;
  Promise.resolve().then(() => task(stillActive)).catch(error => {
    if (!stillActive() || error.name === 'AbortError') return;
    if (errorTarget) errorTarget.textContent = error.message;
    else message(error.message);
  }).finally(() => {
    if (!stillActive()) return;
    button.disabled = button.id === 'previous-page' ? offset === 0 : button.id === 'next-page' ? offset + pageSize >= total : false;
  });
}

export function stopBusiness() {
  stopChat();
  active = false;
  epoch++;
  controller?.abort();
  dialogs.forEach(id => { if (el(id).open) el(id).close(); });
  ['company-form', 'customer-form', 'customer-search', 'import-form'].forEach(id => el(id).reset());
  document.querySelectorAll('#workspace button, dialog button').forEach(button => { button.disabled = false; });
  el('customer-rows').replaceChildren();
  el('space-name').textContent = '';
  el('workspace-email').textContent = '';
  el('customer-count').textContent = '0';
  el('list-summary').textContent = '正在加载客户…';
  el('page-summary').textContent = '';
  ['customer-form-message', 'import-message', 'delete-message', 'delete-description'].forEach(id => { el(id).textContent = ''; });
  message();
  rows.clear(); editing = null; deleting = null; offset = 0; total = 0;
}

export async function startBusiness() {
  stopBusiness(); active = true; controller = new AbortController();
  const owner = epoch;
  selectView('chat');
  const company = await api('/api/company', {signal: controller.signal});
  if (!active || owner !== epoch) return;
  fillForm(companyForm, company);
  el('space-name').textContent = company.name;
  await loadCustomers();
  if (active && owner === epoch) await startChat();
}

function selectView(view) {
  el('customers-view').hidden = view !== 'customers';
  el('company-view').hidden = view !== 'company';
  el('chat-view').hidden = view !== 'chat';
  el('model-view').hidden = view !== 'model';
  document.querySelectorAll('[data-view]').forEach(button => {
    if (button.dataset.view === view) button.setAttribute('aria-current', 'page');
    else button.removeAttribute('aria-current');
  });
}

document.querySelectorAll('[data-view]').forEach(button => button.addEventListener('click', () => { selectView(button.dataset.view); message(); }));
el('add-customer').addEventListener('click', () => openCustomer());
['close-customer', 'cancel-customer'].forEach(id => el(id).addEventListener('click', () => el('customer-dialog').close()));
el('cancel-delete').addEventListener('click', () => el('delete-dialog').close());
el('close-import').addEventListener('click', () => el('import-dialog').close());

companyForm.addEventListener('submit', event => {
  event.preventDefault();
  const body = Object.fromEntries(new FormData(companyForm));
  action(companyForm.querySelector('[type=submit]'), async valid => {
    const data = await api('/api/company', {method: 'PUT', body, signal: controller.signal});
    if (!valid()) return;
    el('space-name').textContent = data.name;
    message('公司资料已保存。', true);
  });
});

customerForm.addEventListener('submit', event => {
  event.preventDefault();
  const id = editing;
  const body = Object.fromEntries(new FormData(customerForm));
  body.match_score = Number(body.match_score || 0);
  // Existing social_media remains intact because partial updates omit it.
  action(customerForm.querySelector('[type=submit]'), async valid => {
    await api(id ? `/api/customers/${id}` : '/api/customers', {method: id ? 'PUT' : 'POST', body, signal: controller.signal});
    if (!valid()) return;
    el('customer-dialog').close();
    message(id ? '客户资料已更新。' : '客户已添加。', true);
    await loadCustomers();
  }, el('customer-form-message'));
});

el('customer-search').addEventListener('submit', event => {
  event.preventDefault(); offset = 0;
  action(el('customer-search').querySelector('button'), () => loadCustomers());
});
for (const [id, delta] of [['previous-page', -pageSize], ['next-page', pageSize]]) {
  el(id).addEventListener('click', () => { offset = Math.max(0, offset + delta); action(el(id), () => loadCustomers()); });
}
el('delete-form').addEventListener('submit', event => {
  event.preventDefault();
  const id = deleting;
  action(el('delete-form').querySelector('[type=submit]'), async valid => {
    await api(`/api/customers/${id}`, {method: 'DELETE', signal: controller.signal});
    if (!valid()) return;
    el('delete-dialog').close(); message('客户已删除。', true); await loadCustomers();
  }, el('delete-message'));
});

el('import-customers').addEventListener('click', () => {
  el('import-form').reset(); el('import-message').textContent = ''; el('import-dialog').showModal();
});
el('import-form').addEventListener('submit', event => {
  event.preventDefault();
  const file = el('import-file').files[0];
  action(el('import-form').querySelector('[type=submit]'), async valid => {
    if (!file || file.size > 2_000_000) throw new Error('请选择不超过 2 MB 的 UTF-8 CSV 文件。');
    const content = await file.text();
    if (!valid()) return;
    const result = await api('/api/customers/import', {method: 'POST', body: {content}, signal: controller.signal});
    if (!valid()) return;
    el('import-dialog').close(); offset = 0; message(`已导入 ${result.imported} 位客户。`, true); await loadCustomers();
  }, el('import-message'));
});
el('export-customers').addEventListener('click', () => {
  action(el('export-customers'), async valid => {
    const response = await api(`/api/customers/export?${filters()}`, {raw: true, signal: controller.signal});
    const blob = await response.blob();
    if (!valid()) return;
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a'); link.href = url; link.download = 'customers.csv';
    document.body.append(link); link.click(); link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    message('客户 CSV 已导出。', true);
  });
});
