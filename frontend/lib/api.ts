import { apiBase } from "@/lib/utils";
import type { Conversation, Dashboard, ProduckPollResult } from "@/lib/types";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${apiBase()}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers || {}),
    },
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new Error(payload.detail || response.statusText);
  }
  return response.json();
}

export const api = {
  conversations: (params?: { q?: string; status?: string }) => {
    const query = new URLSearchParams();
    if (params?.q) query.set("q", params.q);
    if (params?.status && params.status !== "all") query.set("status", params.status);
    const suffix = query.toString() ? `?${query}` : "";
    return request<Conversation[]>(`/api/conversations${suffix}`);
  },
  conversation: (id: string) => request<Conversation>(`/api/conversations/${id}`),
  createConversation: () =>
    request<Conversation>("/api/conversations", {
      method: "POST",
      body: JSON.stringify({ title: "New incident" }),
    }),
  submitIncident: (payload: {
    incident: string;
    conversation_id?: string;
    employee_portal_path?: string;
    severity?: string;
    category?: string;
    tags?: string[];
  }) =>
    request<{ conversation: Conversation; execution: Conversation["executions"][number] }>("/api/incidents/submit", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  dashboard: () => request<Dashboard>("/api/dashboard"),
  search: (q: string) => request(`/api/search?q=${encodeURIComponent(q)}`),
  produckState: () => request<Record<string, unknown>>("/api/settings/produck-fetch"),
  setProduckFetch: (enabled: boolean) =>
    request<{ enabled: boolean; updated_at: string }>("/api/settings/produck-fetch", {
      method: "PUT",
      body: JSON.stringify({ enabled }),
    }),
  targetRepo: () => request<{ employee_portal_path: string; updated_at: string | null }>("/api/settings/target-repo"),
  setTargetRepo: (employee_portal_path: string) =>
    request<{ employee_portal_path: string; updated_at: string }>("/api/settings/target-repo", {
      method: "PUT",
      body: JSON.stringify({ employee_portal_path }),
    }),
  pollProduck: () => request<ProduckPollResult>("/api/produck/poll", { method: "POST" }),
  triggerProduckConversation: (conversationId: string) =>
    request<{ conversation: Conversation; execution: Conversation["executions"][number] }>(
      `/api/produck/conversations/${conversationId}/trigger`,
      { method: "POST" },
    ),
};
