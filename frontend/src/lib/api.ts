const API_BASE = "/api";

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const token = typeof window !== "undefined" ? localStorage.getItem("token") : null;
  const headers: Record<string, string> = { ...(options.headers as Record<string, string>) };
  if (token) headers["Authorization"] = `Bearer ${token}`;
  if (!(options.body instanceof FormData)) headers["Content-Type"] = "application/json";

  const res = await fetch(`${API_BASE}${path}`, { ...options, headers });

  if (res.status === 401) {
    if (typeof window !== "undefined") { localStorage.removeItem("token"); window.location.href = "/login"; }
    throw new Error("Unauthorized");
  }
  if (!res.ok) {
    const errObj = await res.json().catch(() => ({}));
    let msg = "Request failed";
    if (typeof errObj.detail === "string") {
      msg = errObj.detail;
    } else if (Array.isArray(errObj.detail)) {
      msg = errObj.detail.map((e: any) => e.msg || JSON.stringify(e)).join("; ");
    } else if (typeof errObj.message === "string") {
      msg = errObj.message;
    } else if (typeof errObj.error === "string") {
      msg = errObj.error;
    }
    throw new Error(msg);
  }
  return res.json();
}

export const api = {
  // ── Auth ────────────────────────────────────────────────────────────────────
  login: (email: string, password: string) =>
    request<{ access_token: string }>("/auth/login", { method: "POST", body: JSON.stringify({ email, password }) }),

  register: (email: string, password: string, client_id: string, role = "admin", setup_key = "") =>
    request<{ message: string }>("/auth/register", { method: "POST", body: JSON.stringify({ email, password, client_id, role, setup_key }) }),

  getSetupStatus: () => request<{ setup_required: boolean }>("/auth/setup-status"),

  // ── Documents ────────────────────────────────────────────────────────────────
  uploadDocument: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<{ doc_id: string; filename: string; status: string; chunks_count: number }>("/documents/upload", { method: "POST", body: form });
  },
  listDocuments: () => request<{ documents: import("@/types").Document[]; total: number }>("/documents"),
  deleteDocument: (docId: string) => request(`/documents/${docId}`, { method: "DELETE" }),

  // ── Chat ─────────────────────────────────────────────────────────────────────
  chat: (clientId: string, message: string, sessionId?: string, channel = "web_api", departmentCode = "") =>
    request<import("@/types").ChatResponse>(`/chat/${clientId}/query`, {
      method: "POST",
      body: JSON.stringify({ message, session_id: sessionId, channel, department_code: departmentCode }),
    }),

  getChatHistory: (clientId: string, sessionId: string) =>
    request<{ session_id: string; messages: import("@/types").ChatMessage[] }>(`/chat/${clientId}/history/${sessionId}`),

  getQuota: () => request<{ remaining_daily: number }>("/chat/quota"),

  // ── Analytics & Monitoring ───────────────────────────────────────────────────
  getUsage: () => request<import("@/types").UsageStats>("/analytics/usage"),
  getChannelUsage: (channel: string) => request<import("@/types").ChannelStats>(`/analytics/channel/${channel}`),
  getQueries: (page = 1, pageSize = 20) =>
    request<{ logs: import("@/types").QueryLog[]; total: number; page: number }>(`/analytics/queries?page=${page}&page_size=${pageSize}`),
  getWebhookLogs: (params: { clientId?: string; page?: number; pageSize?: number; channel?: string; status?: string; search?: string } = {}) => {
    const q = new URLSearchParams();
    if (params.clientId) q.append("client_id", params.clientId);
    if (params.page) q.append("page", String(params.page));
    if (params.pageSize) q.append("page_size", String(params.pageSize));
    if (params.channel) q.append("channel", params.channel);
    if (params.status) q.append("status", params.status);
    if (params.search) q.append("search", params.search);
    return request<{ logs: import("@/types").WebhookLog[]; total: number; page: number; page_size: number }>(
      `/analytics/webhook-logs?${q.toString()}`
    );
  },

  // ── Clients ──────────────────────────────────────────────────────────────────
  getMyProfile: () =>
    request<{ email: string; client_id: string; role: string; client: import("@/types").ClientRecord | null }>("/clients/me/profile"),

  updateClientSettings: (clientId: string, settings: Record<string, unknown>) =>
    request(`/clients/${clientId}/settings`, { method: "PATCH", body: JSON.stringify(settings) }),

  validateMenuGraph: (clientId: string, nodes: import("@/types").MenuGraphNode[], rootNodeId?: string) =>
    request<import("@/types").MenuGraphValidationResult>(`/clients/${clientId}/validate-menu-graph`, {
      method: "POST",
      body: JSON.stringify({ nodes, root_node_id: rootNodeId }),
    }),

  publishMenuGraph: (clientId: string, nodes: import("@/types").MenuGraphNode[], rootNodeId?: string) =>
    request<{ message: string; validation: import("@/types").MenuGraphValidationResult; compiled_setups: Record<string, any> }>(
      `/clients/${clientId}/publish-menu-graph`,
      {
        method: "POST",
        body: JSON.stringify({ nodes, root_node_id: rootNodeId }),
      }
    ),

  createClient: (data: { client_id: string; name: string; domain?: string; admin_email?: string; admin_password?: string }) =>
    request<{ message: string; client_id: string }>("/clients", { method: "POST", body: JSON.stringify(data) }),

  deleteClient: (clientId: string, masterKey: string) =>
    request<{ message: string; users_deleted: number }>(`/clients/${clientId}`, {
      method: "DELETE",
      headers: { "X-Master-Key": masterKey }
    }),

  listClients: () => request<{ clients: import("@/types").ClientRecord[]; total: number }>("/clients"),

  getClientConfig: (clientId: string) =>
    request<import("@/types").ClientRecord>(`/clients/${clientId}/config`),

  // ── Setups ───────────────────────────────────────────────────────────────────
  listSetups: (clientId: string) =>
    request<{ setups: import("@/types").SetupSummary[] }>(`/clients/${clientId}/setups`),

  getSetupConfig: (clientId: string, channel: string) =>
    request<{ channel: string; label: string; emoji: string; config: Record<string, unknown>; editable: boolean }>(
      `/clients/${clientId}/setups/${channel}`
    ),

  updateSetupConfig: (clientId: string, channel: string, config: Record<string, unknown>) =>
    request(`/clients/${clientId}/setups/${channel}`, { method: "PATCH", body: JSON.stringify(config) }),

  toggleSetup: (clientId: string, channel: string, enabled: boolean) =>
    request<{ message: string; enabled: boolean }>(`/clients/${clientId}/setups/${channel}/toggle`, {
      method: "POST",
      body: JSON.stringify({ enabled }),
    }),

  rotateSetupToken: (clientId: string, channel: string) =>
    request<{ token: string; channel: string }>(`/clients/${clientId}/setups/${channel}/rotate-token`, { method: "POST" }),

  disableSetupToken: (clientId: string, channel: string) =>
    request(`/clients/${clientId}/setups/${channel}/token`, { method: "DELETE" }),

  registerTelegramWebhook: (clientId: string, webhookUrl: string) =>
    request(`/clients/${clientId}/setups/telegram/register-webhook`, {
      method: "POST",
      body: JSON.stringify({ webhook_url: webhookUrl }),
    }),

  // ── Profile Compilation Engine ───────────────────────────────────────────────
  getCompiledProfile: (clientId: string, channel = "widget") =>
    request<{ compiled_profile: import("@/types").CompiledProfile }>(`/clients/${clientId}/compiled-profile?channel=${channel}`),

  recompileProfile: (clientId: string, channel = "widget") =>
    request<{ message: string; compiled_profile: import("@/types").CompiledProfile }>(
      `/clients/${clientId}/recompile-profile?channel=${channel}`,
      { method: "POST" }
    ),

  // ── Super-admin analytics ─────────────────────────────────────────────────────
  superAdminOverview: () => request<import("@/types").SuperAdminOverview>("/analytics/super-admin/overview"),
  superAdminClientDetail: (clientId: string, page = 1, pageSize = 20) =>
    request<import("@/types").SuperAdminClientDetail>(`/analytics/super-admin/clients/${clientId}?page=${page}&page_size=${pageSize}`),
  superAdminChannelDetail: (clientId: string, channel: string) =>
    request<import("@/types").ChannelStats>(`/analytics/super-admin/clients/${clientId}/channel/${channel}`),

  // ── Master keys ───────────────────────────────────────────────────────────────
  listMasterKeys: () => request<{ keys: { key_id: string; name: string; created_at: string }[] }>("/auth/master-keys"),
  createMasterKey: (name: string, value: string) =>
    request<{ key_id: string; name: string; value: string }>("/auth/master-keys", { method: "POST", body: JSON.stringify({ name, value }) }),
  deleteMasterKey: (keyId: string) => request(`/auth/master-keys/${keyId}`, { method: "DELETE" }),

  impersonate: (clientId: string, master_key: string) =>
    request<{ access_token: string; institution_name: string; client_id: string }>(
      `/auth/impersonate/${clientId}`, { method: "POST", body: JSON.stringify({ master_key }) }
    ),

  // ── Legacy (kept for backward compat) ────────────────────────────────────────
  rotateWidgetToken: (clientId: string) =>
    request<{ widget_token: string }>(`/clients/${clientId}/rotate-widget-token`, { method: "POST" }),
  disableWidgetToken: (clientId: string) =>
    request(`/clients/${clientId}/widget-token`, { method: "DELETE" }),
};
