export class ApiError extends Error {
  constructor(message, status) { super(message); this.status = status; }
}

const messages = {
  'Invalid email or password': '邮箱或密码不正确；密码需为 8–128 位。',
  'Email already registered': '这个邮箱已经注册，请直接登录。',
  'Not logged in': '登录已过期，请重新登录。',
  'Record not found': '记录不存在或无权访问，请刷新后重试。',
  'Customer not found': '关联客户不存在或不属于当前公司空间。',
  'Conversation not found': '对话不存在或无权访问，请刷新后重试。',
};

export async function api(path, options = {}) {
  const { body, raw, notifyExpired = true, ...rest } = options;
  let response;
  try {
    response = await fetch(path, {
      credentials: 'same-origin', cache: 'no-store', ...rest,
      ...(body === undefined ? {} : body instanceof FormData ? {body} : {headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)}),
    });
  } catch (error) {
    if (error.name === 'AbortError') throw error;
    throw new Error('无法连接本地服务，请稍后重试。');
  }
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    if (response.status === 401 && notifyExpired) window.dispatchEvent(new Event('session-expired'));
    const detail = typeof data.detail === 'string' ? data.detail : '输入内容有误，请检查必填项和字段格式。';
    throw new ApiError(messages[detail] || detail, response.status);
  }
  return raw ? response : response.json();
}
