/*
 * api.js — SPA 后端契约消费统一出口
 *
 * 形态：fetch JSON 封装。401（AUTH_REQUIRED）统一跳登录页；非 2xx 解析
 * 错误体 {"code","message"}（D11 规范 4XX）抛 ApiError 供视图呈现。
 * 契约清单见技术书 §3（SPA 只消费在册端点，不自造）。
 */
const LOGIN_PAGE = "/login";

export class ApiError extends Error {
  constructor(status, code, message) {
    super(message || code || `HTTP ${status}`);
    this.status = status;
    this.code = code || "";
  }
}

async function request(method, path, body) {
  const options = { method, headers: {} };
  if (body !== undefined) {
    options.headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(body);
  }
  const response = await fetch(path, options);
  if (response.status === 401) {
    window.location.href = LOGIN_PAGE;
    throw new ApiError(401, "AUTH_REQUIRED", "");
  }
  let payload = null;
  const text = await response.text();
  if (text) {
    try { payload = JSON.parse(text); } catch { payload = null; }
  }
  if (!response.ok) {
    const code = payload && payload.code ? payload.code : "";
    const message = payload && payload.message ? payload.message : "";
    throw new ApiError(response.status, code, message);
  }
  return payload;
}

export const api = {
  get: (path) => request("GET", path),
  post: (path, body) => request("POST", path, body ?? {}),
  put: (path, body) => request("PUT", path, body ?? {}),
  delete: (path) => request("DELETE", path),
};
