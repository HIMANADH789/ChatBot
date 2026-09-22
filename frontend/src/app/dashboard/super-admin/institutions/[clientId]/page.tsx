"use client";

import { useEffect, useState, useCallback } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import { api } from "@/lib/api";
import type { ClientRecord, SetupSummary, MenuGraphNode } from "@/types";
import { MenuGraphBuilder } from "@/components/MenuGraphBuilder";

const BACKEND_URL = process.env.NEXT_API_URL || "http://localhost:8000";

const inputCls = "w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500";

// ── General settings card ─────────────────────────────────────────────────────

function GeneralSection({ clientId, initial }: { clientId: string; initial: ClientRecord }) {
  const [name] = useState(initial.name || "");
  const [welcomeMessage, setWelcomeMessage] = useState(initial.settings?.welcome_message || "Hello! How can I help you today?");
  const [systemPrompt, setSystemPrompt] = useState(initial.settings?.system_prompt || "");
  const [maxHistory, setMaxHistory] = useState(initial.settings?.max_history_turns ?? 5);
  const [themeColor, setThemeColor] = useState(initial.settings?.theme_color || "#1E40AF");
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState("");

  async function save() {
    setSaving(true); setError(""); setSaved(false);
    try {
      await api.updateClientSettings(clientId, { welcome_message: welcomeMessage, system_prompt: systemPrompt || undefined, max_history_turns: maxHistory, theme_color: themeColor });
      setSaved(true); setTimeout(() => setSaved(false), 3000);
    } catch (e) { setError(e instanceof Error ? e.message : "Failed"); }
    finally { setSaving(false); }
  }

  return (
    <div className="rounded-xl border border-gray-200 bg-white p-6 shadow-sm">
      <h2 className="mb-5 text-base font-semibold text-gray-900">General Settings</h2>
      <div className="space-y-4">
        <div>
          <label className="mb-1 block text-sm font-medium text-gray-700">Institution Name</label>
          <div className="rounded-lg bg-gray-50 px-3 py-2 text-sm text-gray-600">{name}</div>
        </div>
        <div>
          <label className="mb-1 block text-sm font-medium text-gray-700">Client ID</label>
          <code className="block rounded-md bg-gray-100 px-3 py-2 text-sm font-mono text-gray-700">{clientId}</code>
        </div>
        <div>
          <label className="mb-1 block text-sm font-medium text-gray-700">Welcome Message</label>
          <input className={inputCls} value={welcomeMessage} onChange={e => setWelcomeMessage(e.target.value)} />
        </div>
        <div>
          <label className="mb-1 block text-sm font-medium text-gray-700">System Prompt <span className="text-gray-400 font-normal">(optional)</span></label>
          <textarea className={`${inputCls} min-h-[80px] resize-y`} value={systemPrompt} onChange={e => setSystemPrompt(e.target.value)} placeholder="You are a helpful assistant for..." />
        </div>
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="mb-1 block text-sm font-medium text-gray-700">Max History Turns</label>
            <input type="number" min={1} max={20} className={inputCls} value={maxHistory} onChange={e => setMaxHistory(Number(e.target.value))} />
          </div>
          <div>
            <label className="mb-1 block text-sm font-medium text-gray-700">Theme Color</label>
            <div className="flex items-center gap-2">
              <input type="color" className="h-10 w-14 cursor-pointer rounded-lg border border-gray-300 p-1" value={themeColor} onChange={e => setThemeColor(e.target.value)} />
              <input className={`${inputCls} font-mono`} value={themeColor} onChange={e => setThemeColor(e.target.value)} maxLength={7} />
            </div>
          </div>
        </div>
        <div className="flex items-center gap-3 pt-1">
          <button onClick={save} disabled={saving} className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50">
            {saving ? "Saving…" : "Save"}
          </button>
          {saved && <span className="text-xs text-green-600">Saved</span>}
          {error && <span className="text-xs text-red-600">{error}</span>}
        </div>
      </div>
    </div>
  );
}

// ── Setup card ────────────────────────────────────────────────────────────────

const CHANNEL_COLORS: Record<string, string> = {
  widget: "bg-blue-100 text-blue-700 border-blue-200",
  web_api: "bg-purple-100 text-purple-700 border-purple-200",
  whatsapp: "bg-green-100 text-green-700 border-green-200",
  facebook: "bg-blue-100 text-blue-700 border-blue-200",
  telegram: "bg-sky-100 text-sky-700 border-sky-200",
  slack: "bg-violet-100 text-violet-700 border-violet-200",
};

function SetupCard({ setup, clientId, onToggle }: {
  setup: SetupSummary;
  clientId: string;
  onToggle: (channel: string, enabled: boolean) => void;
}) {
  const router = useRouter();
  const [toggling, setToggling] = useState(false);
  const colorCls = CHANNEL_COLORS[setup.channel] || "bg-gray-100 text-gray-700 border-gray-200";

  async function handleToggle(e: React.MouseEvent) {
    e.stopPropagation();
    setToggling(true);
    try {
      await api.toggleSetup(clientId, setup.channel, !setup.enabled);
      onToggle(setup.channel, !setup.enabled);
    } catch (err) { alert(err instanceof Error ? err.message : "Failed"); }
    finally { setToggling(false); }
  }

  return (
    <div className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm hover:shadow-md transition-shadow">
      <div className="flex items-start justify-between mb-3">
        <div className="flex items-center gap-3">
          <span className="text-2xl">{setup.emoji}</span>
          <div>
            <p className="font-semibold text-gray-900 text-sm">{setup.label}</p>
            <span className={`inline-block mt-0.5 rounded-full border px-2 py-0.5 text-xs font-medium ${colorCls} ${setup.enabled ? "" : "opacity-50"}`}>
              {setup.enabled ? "Active" : "Inactive"}
            </span>
          </div>
        </div>
        <button
          onClick={handleToggle}
          disabled={toggling}
          className={`relative inline-flex h-6 w-11 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 focus:outline-none disabled:opacity-50 ${setup.enabled ? "bg-blue-600" : "bg-gray-200"}`}
          title={setup.enabled ? "Deactivate" : "Activate"}
        >
          <span className={`inline-block h-5 w-5 transform rounded-full bg-white shadow ring-0 transition duration-200 ${setup.enabled ? "translate-x-5" : "translate-x-0"}`} />
        </button>
      </div>

      {setup.enabled && (
        <div className="mb-3 grid grid-cols-3 gap-2 text-center">
          <div className="rounded-lg bg-gray-50 px-2 py-1.5">
            <p className="text-xs text-gray-400">RPM</p>
            <p className="text-sm font-semibold text-gray-700">{setup.rate_limit_rpm || "∞"}</p>
          </div>
          <div className="rounded-lg bg-gray-50 px-2 py-1.5">
            <p className="text-xs text-gray-400">RPD</p>
            <p className="text-sm font-semibold text-gray-700">{setup.rate_limit_rpd || "∞"}</p>
          </div>
          <div className="rounded-lg bg-gray-50 px-2 py-1.5">
            <p className="text-xs text-gray-400">Session</p>
            <p className="text-sm font-semibold text-gray-700">{setup.max_queries_per_session || "∞"}</p>
          </div>
        </div>
      )}

      {setup.channel in { widget: 1, web_api: 1 } && setup.enabled && (
        <div className="mb-3 flex items-center gap-1.5">
          <span className={`h-2 w-2 rounded-full ${setup.token_set ? "bg-green-400" : "bg-gray-300"}`} />
          <span className="text-xs text-gray-500">{setup.token_set ? "Token security on" : "No token (open access)"}</span>
        </div>
      )}

      <button
        onClick={() => router.push(`/dashboard/super-admin/institutions/${clientId}/setups/${setup.channel}`)}
        className="w-full rounded-lg border border-gray-200 bg-gray-50 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-100"
      >
        Configure →
      </button>
    </div>
  );
}

// ── Delete Institution Modal ──────────────────────────────────────────────────

function DeleteInstitutionModal({ client, onClose, onDelete }: { client: ClientRecord; onClose: () => void; onDelete: () => void }) {
  const [masterKey, setMasterKey] = useState("");
  const [showKey, setShowKey] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(""); setLoading(true);
    try {
      await api.deleteClient(client.client_id, masterKey);
      onDelete();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to delete institution.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="w-full max-w-sm rounded-2xl bg-white shadow-xl">
        <div className="flex items-center justify-between border-b border-gray-100 px-6 py-4">
          <div>
            <h2 className="font-semibold text-gray-900">Delete Institution</h2>
            <p className="text-xs text-gray-400">{client.name}</p>
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-xl">&times;</button>
        </div>
        <form onSubmit={handleSubmit} className="space-y-4 p-6">
          <div className="rounded-lg bg-red-50 border border-red-100 p-3 text-xs text-red-800">
            <strong>Warning:</strong> This will permanently delete <strong>{client.name}</strong> and all associated admins. This action cannot be undone. Enter your master key to confirm.
          </div>
          {error && <div className="rounded-lg bg-red-50 p-3 text-sm text-red-600">{error}</div>}
          <div>
            <label className="mb-1 block text-sm font-medium text-gray-700">Master Key</label>
            <div className="relative">
              <input
                type={showKey ? "text" : "password"}
                className="w-full rounded-lg border border-gray-300 px-3 py-2 pr-16 text-sm font-mono focus:border-red-500 focus:outline-none"
                value={masterKey}
                onChange={(e) => setMasterKey(e.target.value)}
                placeholder="Enter master key"
                autoFocus
                required
              />
              <button type="button" onClick={() => setShowKey((v) => !v)}
                className="absolute right-3 top-2 text-xs text-gray-400">{showKey ? "Hide" : "Show"}</button>
            </div>
          </div>
          <div className="flex gap-3">
            <button type="button" onClick={onClose}
              className="flex-1 rounded-lg border border-gray-300 px-4 py-2 text-sm hover:bg-gray-50">Cancel</button>
            <button type="submit" disabled={loading}
              className="flex-1 rounded-lg bg-red-600 px-4 py-2 text-sm font-medium text-white hover:bg-red-700 disabled:opacity-50">
              {loading ? "Deleting\u2026" : "Delete Permanently"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function InstitutionConfigPage() {
  const params = useParams();
  const clientId = params.clientId as string;
  const router = useRouter();

  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [client, setClient] = useState<ClientRecord | null>(null);
  const [setups, setSetups] = useState<SetupSummary[]>([]);
  const [showDelete, setShowDelete] = useState(false);

  const load = useCallback(async () => {
    try {
      const [clientData, setupsData] = await Promise.all([
        api.getClientConfig(clientId),
        api.listSetups(clientId),
      ]);
      setClient(clientData);
      setSetups(setupsData.setups);
    } catch (e) {
      setLoadError(e instanceof Error ? e.message : "Failed to load");
    } finally {
      setLoading(false);
    }
  }, [clientId]);

  useEffect(() => { load(); }, [load]);

  function handleToggle(channel: string, enabled: boolean) {
    setSetups(prev => prev.map(s => s.channel === channel ? { ...s, enabled } : s));
  }

  if (loading) return (
    <div className="flex h-64 items-center justify-center">
      <div className="h-8 w-8 animate-spin rounded-full border-4 border-blue-600 border-t-transparent" />
    </div>
  );

  if (loadError) return (
    <div className="space-y-4">
      <Link href="/dashboard/super-admin/institutions" className="text-sm text-blue-600 hover:underline">&larr; Back</Link>
      <div className="rounded-lg bg-red-50 p-4 text-sm text-red-600">{loadError}</div>
    </div>
  );

  const activeSetups = setups.filter(s => s.enabled);
  const inactiveSetups = setups.filter(s => !s.enabled);

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center gap-4">
        <Link href="/dashboard/super-admin/institutions" className="text-sm text-blue-600 hover:underline">&larr; Institutions</Link>
        <div>
          <h1 className="text-xl font-bold text-gray-900">{client?.name}</h1>
          <p className="text-xs text-gray-400">Institution Configuration · <code className="font-mono">{clientId}</code></p>
        </div>
      </div>

      {/* Quick nav */}
      <div className="flex flex-wrap gap-2">
        <Link href={`/dashboard/super-admin/institutions/${clientId}/analytics`}
          className="rounded-lg border border-gray-200 bg-white px-3 py-1.5 text-xs font-medium text-gray-600 hover:bg-gray-50">
          📈 Analytics
        </Link>
        {activeSetups.map(s => (
          <Link key={s.channel} href={`/dashboard/super-admin/institutions/${clientId}/setups/${s.channel}`}
            className="rounded-lg border border-gray-200 bg-white px-3 py-1.5 text-xs font-medium text-gray-600 hover:bg-gray-50">
            {s.emoji} {s.label}
          </Link>
        ))}
      </div>

      {/* General settings */}
      {client && <GeneralSection clientId={clientId} initial={client} />}

      {/* ⚡ Visual Menu & Channel Builder (Graph State Machine) */}
      {client && (
        <MenuGraphBuilder
          clientId={clientId}
          nodes={client.settings?.menu_graph_nodes || []}
          rootNodeId={client.settings?.menu_graph_root_node_id || "MENU_ROOT"}
          onChange={(updatedNodes, updatedRootId) => {
            setClient((prev) => {
              if (!prev) return prev;
              return {
                ...prev,
                settings: {
                  ...prev.settings,
                  menu_graph_nodes: updatedNodes,
                  menu_graph_root_node_id: updatedRootId,
                },
              };
            });
          }}
          onSaved={() => {
            load();
          }}
        />
      )}

      {/* Active setups */}
      <div>
        <h2 className="mb-3 text-base font-semibold text-gray-900">Active Setups <span className="text-sm font-normal text-gray-400">({activeSetups.length})</span></h2>
        {activeSetups.length === 0 ? (
          <div className="rounded-xl border-2 border-dashed border-gray-200 p-8 text-center text-sm text-gray-400">No active setups</div>
        ) : (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {activeSetups.map(s => <SetupCard key={s.channel} setup={s} clientId={clientId} onToggle={handleToggle} />)}
          </div>
        )}
      </div>

      {/* Inactive setups */}
      {inactiveSetups.length > 0 && (
        <div>
          <h2 className="mb-3 text-base font-semibold text-gray-500">Available Setups <span className="text-sm font-normal text-gray-400">— click toggle to activate</span></h2>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {inactiveSetups.map(s => <SetupCard key={s.channel} setup={s} clientId={clientId} onToggle={handleToggle} />)}
          </div>
        </div>
      )}

      {/* Danger Zone */}
      {client && (
        <div className="mt-8 rounded-xl border border-red-200 bg-white p-6 shadow-sm">
          <h2 className="mb-2 text-base font-semibold text-red-700">Danger Zone</h2>
          <p className="mb-4 text-sm text-gray-500">
            Permanently delete this institution and all associated admin accounts.
          </p>
          <button
            onClick={() => setShowDelete(true)}
            className="rounded-lg bg-red-50 border border-red-200 px-4 py-2 text-sm font-medium text-red-700 hover:bg-red-100 hover:text-red-800"
          >
            Delete Institution
          </button>
        </div>
      )}

      {showDelete && client && (
        <DeleteInstitutionModal
          client={client}
          onClose={() => setShowDelete(false)}
          onDelete={() => {
            setShowDelete(false);
            router.push("/dashboard/super-admin/institutions");
          }}
        />
      )}
    </div>
  );
}
