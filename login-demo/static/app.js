import {api} from './api.js';
import {startBusiness, stopBusiness} from './business.js';

let authEpoch = 0;
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

async function showWorkspace(user) {
  const owner = ++authEpoch;
  authPanel.hidden = true;
  workspace.hidden = false;
  loginForm.reset(); registerForm.reset();
  try {
    await startBusiness();
    if (owner === authEpoch) workspaceEmail.textContent = user.email;
  } catch (error) {
    if (owner !== authEpoch || error.name === 'AbortError') return;
    document.getElementById('business-message').textContent = error.message;
  }
}

async function requestJson(path, payload) {
  return api(path, {method: 'POST', body: payload, notifyExpired: false});
}

function showLogin(message = '') {
  authEpoch++;
  stopBusiness();
  workspace.hidden = true;
  authPanel.hidden = false;
  loginForm.reset(); registerForm.reset();
  showMode('login'); showMessage(message);
}

window.addEventListener('session-expired', () => showLogin('登录已过期，请重新登录。'));

function bindForm(form, endpoint) {
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    const submitButton = form.querySelector('button[type="submit"]');
    const payload = Object.fromEntries(new FormData(form).entries());
    submitButton.disabled = true;
    showMessage('');
    try {
      const user = await requestJson(endpoint, payload);
      await showWorkspace(user);
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
    showLogin();
  } catch (error) {
    document.getElementById('business-message').textContent = error.message;
  }
});

async function restoreSession() {
  try {
    const user = await api('/api/me', {notifyExpired: false});
    await showWorkspace(user);
  } catch (error) {
    if (error.status !== 401) showMessage(error.message);
  }
}

restoreSession();
