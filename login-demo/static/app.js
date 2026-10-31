import {api} from './api.js';

const loginForm = document.getElementById('login-form');
const registerForm = document.getElementById('register-form');
const loginTab = document.getElementById('show-login');
const registerTab = document.getElementById('show-register');
const statusMessage = document.getElementById('status-message');
const authTitle = document.getElementById('auth-title');
const authSubtitle = document.getElementById('auth-subtitle');

function showMessage(text) {
  statusMessage.textContent = text;
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
  authSubtitle.textContent = registering ? '创建你的独立公司空间' : '登录以进入你的公司空间';
  showMessage('');
}

async function submitForm(form, endpoint, submitButton) {
  submitButton.disabled = true;
  showMessage('');
  try {
    await api(endpoint, {
      method:'POST',
      body:Object.fromEntries(new FormData(form).entries()),
      notifyExpired:false,
    });
    window.location.assign('/trade');
  } catch (error) {
    showMessage(error.message);
  } finally {
    submitButton.disabled = false;
  }
}

loginTab.addEventListener('click', () => showMode('login'));
registerTab.addEventListener('click', () => showMode('register'));
loginForm.addEventListener('submit', event => {
  event.preventDefault();
  submitForm(loginForm, '/api/login', loginForm.querySelector('[type=submit]'));
});
registerForm.addEventListener('submit', event => {
  event.preventDefault();
  submitForm(registerForm, '/api/register', registerForm.querySelector('[type=submit]'));
});

(async function restoreSession() {
  try {
    await api('/api/me', {notifyExpired:false});
    window.location.replace('/trade');
  } catch (error) {
    if (error.status !== 401) showMessage(error.message);
  }
})();
