const API_BASE = import.meta.env.VITE_API_BASE || "http://localhost:8000/api";

export function getToken() {
  return localStorage.getItem("ms_mail_token");
}

export function setSession(token, username) {
  localStorage.setItem("ms_mail_token", token);
  localStorage.setItem("ms_mail_username", username);
}

export function clearSession() {
  localStorage.removeItem("ms_mail_token");
  localStorage.removeItem("ms_mail_username");
}

export async function request(path, options = {}) {
  const headers = new Headers(options.headers || {});
  if (!headers.has("Content-Type") && options.body) {
    headers.set("Content-Type", "application/json");
  }
  const token = getToken();
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }

  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers,
  });
  const text = await response.text();
  const data = text ? JSON.parse(text) : null;
  if (!response.ok) {
    const message = data?.detail || data?.message || "请求失败";
    throw new Error(Array.isArray(message) ? message.map((item) => item.msg).join("; ") : message);
  }
  return data;
}

export const api = {
  login: (payload) => request("/auth/login", { method: "POST", body: JSON.stringify(payload) }),
  me: () => request("/auth/me"),
  apiKeys: () => request("/api-keys"),
  createApiKey: (name) => request("/api-keys", { method: "POST", body: JSON.stringify({ name }) }),
  updateApiKey: (id, enabled) => request(`/api-keys/${id}`, { method: "PATCH", body: JSON.stringify({ enabled }) }),
  deleteApiKey: (id) => request(`/api-keys/${id}`, { method: "DELETE" }),
  mailboxes: (page = 1, pageSize = 20) =>
    request(`/mailboxes?page=${encodeURIComponent(page)}&page_size=${encodeURIComponent(pageSize)}`),
  createMailbox: (payload) => request("/mailboxes", { method: "POST", body: JSON.stringify(payload) }),
  importMailboxes: (content) =>
    request("/mailboxes/import", { method: "POST", body: JSON.stringify({ content }) }),
  deleteMailbox: (id) => request(`/mailboxes/${id}`, { method: "DELETE" }),
  removeAbnormal: () => request("/mailboxes/abnormal", { method: "DELETE" }),
  checkMailbox: (id) => request(`/mailboxes/${id}/check`, { method: "POST" }),
  bulkCheckMailboxes: (ids) => request("/mailboxes/bulk-check", { method: "POST", body: JSON.stringify({ ids }) }),
  messages: (id, limit = 30) => request(`/mailboxes/${id}/messages?limit=${limit}`),
  messageDetail: (id, uid) => request(`/mailboxes/${id}/messages/${encodeURIComponent(uid)}`),
  publicMailboxes: (apiKey) => request(`/public/mailboxes?api_key=${encodeURIComponent(apiKey)}`),
  publicMailbox: (token, apiKey) =>
    request(`/public/mailboxes/${encodeURIComponent(token)}?api_key=${encodeURIComponent(apiKey)}`),
  publicMessages: (token, apiKey, limit = 30) =>
    request(`/public/mailboxes/${encodeURIComponent(token)}/messages?limit=${limit}&api_key=${encodeURIComponent(apiKey)}`),
  publicMessageDetail: (token, uid, apiKey) =>
    request(
      `/public/mailboxes/${encodeURIComponent(token)}/messages/${encodeURIComponent(uid)}?api_key=${encodeURIComponent(apiKey)}`,
    ),
  publicLatestCode: (token, apiKey, limit = 10) =>
    request(`/public/mailboxes/${encodeURIComponent(token)}/code?limit=${limit}&api_key=${encodeURIComponent(apiKey)}`),
  tokenLatestCode: (token, limit = 10) => request(`/token/${encodeURIComponent(token)}/code?limit=${limit}`),
};
