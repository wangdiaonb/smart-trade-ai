const authPanel = document.getElementById('auth-panel');
const workspace = document.getElementById('workspace');
const loginForm = document.getElementById('login-form');
const registerForm = document.getElementById('register-form');
const loginTab = document.getElementById('show-login');
const registerTab = document.getElementById('show-register');
const statusMessage = document.getElementById('status-message');
const authTitle = document.getElementById('auth-title');
const authSubtitle = document.getElementById('auth-subtitle');
const workspaceEmail = document.getElementById('workspace-email');

function showMessage(message, success = false) {
  statusMessage.textContent = message;
  statusMessage.classList.toggle('is-success', success);
}

function showMode(mode) {
  const registering = mode === 'register';
  loginForm.hidden = registering;
  registerForm.hidden = !registering;
  loginTab.classList.toggle('is-active', !registering);
  registerTab.classList.toggle('is-active', registering);
  loginTab.setAttribute('aria-selected', String(!registering));
  registerTab.setAttribute('aria-selected', String(registering));
  authTitle.textContent = registering ? '创建账户' : '欢迎回来';
  authSubtitle.textContent = registering ? '使用邮箱创建个人空间' : '登录以进入你的工作台';
  showMessage('');
}

function showWorkspace(user) {
  authPanel.hidden = true;
  workspace.hidden = false;
  workspaceEmail.textContent = user.email;
}

async function requestJson(path, payload) {
  const response = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.detail || '请求失败，请稍后重试');
  return data;
}

function bindForm(form, endpoint) {
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    const submitButton = form.querySelector('button[type="submit"]');
    const payload = Object.fromEntries(new FormData(form).entries());
    submitButton.disabled = true;
    showMessage('');
    try {
      const user = await requestJson(endpoint, payload);
      showWorkspace(user);
    } catch (error) {
      showMessage(error.message);
    } finally {
      submitButton.disabled = false;
    }
  });
}

loginTab.addEventListener('click', () => showMode('login'));
registerTab.addEventListener('click', () => showMode('register'));
bindForm(loginForm, '/api/login');
bindForm(registerForm, '/api/register');

document.getElementById('logout-button').addEventListener('click', async () => {
  try {
    await requestJson('/api/logout', {});
    workspace.hidden = true;
    authPanel.hidden = false;
    loginForm.reset();
    showMode('login');
  } catch (error) {
    showMessage(error.message);
  }
});

async function restoreSession() {
  try {
    const response = await fetch('/api/me');
    if (response.ok) showWorkspace(await response.json());
  } catch (_) {
    showMessage('无法连接服务器，请确认本地服务正在运行');
  }
}

restoreSession();
