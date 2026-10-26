"use client";

import { useEffect, useState, useCallback } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import { api } from "@/lib/api";
import type { ClientRecord, SetupSummary, MenuGraphNode } from "@/types";

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
  widget: "bg-blue-50 text-blue-700 border-blue-200",
  web_api: "bg-purple-50 text-purple-700 border-purple-200",
  whatsapp: "bg-emerald-50 text-emerald-700 border-emerald-200",
  facebook: "bg-sky-50 text-sky-700 border-sky-200",
  telegram: "bg-cyan-50 text-cyan-700 border-cyan-200",
  slack: "bg-violet-50 text-violet-700 border-violet-200",
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
    <div className={`rounded-2xl border transition-all duration-200 p-5 ${setup.enabled ? "bg-white border-gray-200 shadow-sm hover:shadow-md hover:border-blue-300" : "bg-gray-50/70 border-gray-200 opacity-75"}`}>
      <div className="flex items-start justify-between mb-3.5">
        <div className="flex items-center gap-3">
          <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-gray-50 border border-gray-100 text-2xl shadow-2xs">
            {setup.emoji}
          </div>
          <div>
            <p className="font-bold text-gray-900 text-sm">{setup.label}</p>
            <div className="flex items-center gap-2 mt-0.5">
              <span className={`inline-block rounded-full border px-2 py-0.5 text-[11px] font-semibold ${colorCls}`}>
                {setup.enabled ? "Active Interface" : "Inactive"}
              </span>
              {setup.enabled && (
                <span className="text-[11px] text-gray-400 font-medium">⚡ Menus &amp; RAG</span>
              )}
            </div>
          </div>
        </div>
        <button
          onClick={handleToggle}
          disabled={toggling}
          className={`relative inline-flex h-6 w-11 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 focus:outline-none disabled:opacity-50 ${setup.enabled ? "bg-blue-600" : "bg-gray-200"}`}
          title={setup.enabled ? "Deactivate Interface" : "Activate Interface"}
        >
          <span className={`inline-block h-5 w-5 transform rounded-full bg-white shadow ring-0 transition duration-200 ${setup.enabled ? "translate-x-5" : "translate-x-0"}`} />
        </button>
      </div>

      {setup.enabled && (
        <div className="mb-4 grid grid-cols-3 gap-2 text-center">
          <div className="rounded-xl bg-gray-50/80 border border-gray-100 px-2 py-2">
            <p className="text-[10px] font-medium uppercase tracking-wider text-gray-400">RPM</p>
            <p className="text-sm font-bold text-gray-700">{setup.rate_limit_rpm || "∞"}</p>
          </div>
          <div className="rounded-xl bg-gray-50/80 border border-gray-100 px-2 py-2">
            <p className="text-[10px] font-medium uppercase tracking-wider text-gray-400">RPD</p>
            <p className="text-sm font-bold text-gray-700">{setup.rate_limit_rpd || "∞"}</p>
          </div>
          <div className="rounded-xl bg-gray-50/80 border border-gray-100 px-2 py-2">
            <p className="text-[10px] font-medium uppercase tracking-wider text-gray-400">Session</p>
            <p className="text-sm font-bold text-gray-700">{setup.max_queries_per_session || "∞"}</p>
          </div>
        </div>
      )}

      {setup.channel in { widget: 1, web_api: 1 } && setup.enabled && (
        <div className="mb-3.5 flex items-center gap-1.5 px-1">
          <span className={`h-2 w-2 rounded-full ${setup.token_set ? "bg-emerald-500 ring-2 ring-emerald-100" : "bg-gray-300"}`} />
          <span className="text-xs text-gray-500 font-medium">{setup.token_set ? "Token Security Enabled" : "Open Public Access"}</span>
        </div>
      )}

      <button
        onClick={() => router.push(`/dashboard/super-admin/institutions/${clientId}/setups/${setup.channel}`)}
        className="w-full rounded-xl border border-blue-200 bg-blue-50/50 py-2 text-xs font-semibold text-blue-700 hover:bg-blue-600 hover:text-white hover:border-blue-600 transition flex items-center justify-center gap-1.5 shadow-2xs"
      >
        <span>Configure Interface &amp; Menus</span>
        <span>&rarr;</span>
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
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-xs p-4">
      <div className="w-full max-w-sm rounded-2xl bg-white shadow-xl border border-gray-100">
        <div className="flex items-center justify-between border-b border-gray-100 px-6 py-4">
          <div>
            <h2 className="font-semibold text-gray-900">Delete Institution</h2>
            <p className="text-xs text-gray-400">{client.name}</p>
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-xl leading-none">&times;</button>
        </div>
        <form onSubmit={handleSubmit} className="space-y-4 p-6">
          <div className="rounded-xl bg-red-50 border border-red-100 p-3.5 text-xs text-red-800 space-y-1">
            <strong>Warning:</strong> Permanently deletes <strong>{client.name}</strong> and all associated admin accounts. This cannot be undone.
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
                className="absolute right-3 top-2 text-xs text-gray-400 hover:text-gray-600">{showKey ? "Hide" : "Show"}</button>
            </div>
          </div>
          <div className="flex gap-3 pt-2">
            <button type="button" onClick={onClose}
              className="flex-1 rounded-xl border border-gray-200 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50">Cancel</button>
            <button type="submit" disabled={loading}
              className="flex-1 rounded-xl bg-red-600 px-4 py-2 text-sm font-semibold text-white hover:bg-red-700 disabled:opacity-50 shadow-sm">
              {loading ? "Deleting…" : "Delete Permanently"}
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
  const [copiedId, setCopiedId] = useState(false);

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

  function copyClientId() {
    navigator.clipboard.writeText(clientId);
    setCopiedId(true);
    setTimeout(() => setCopiedId(false), 2000);
  }

  if (loading) return (
    <div className="flex h-64 items-center justify-center">
      <div className="h-8 w-8 animate-spin rounded-full border-4 border-blue-600 border-t-transparent" />
    </div>
  );

  if (loadError) return (
    <div className="space-y-4">
      <Link href="/dashboard/super-admin/institutions" className="text-sm text-blue-600 hover:underline">&larr; Back to Institutions</Link>
      <div className="rounded-xl bg-red-50 p-4 text-sm text-red-600 border border-red-100">{loadError}</div>
    </div>
  );

  const activeSetups = setups.filter(s => s.enabled);
  const inactiveSetups = setups.filter(s => !s.enabled);

  return (
    <div className="space-y-8 max-w-7xl mx-auto">
      {/* Header Banner */}
      <div className="rounded-2xl bg-gradient-to-r from-blue-900 via-indigo-900 to-slate-900 p-6 text-white shadow-md">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
          <div className="space-y-1.5">
            <Link href="/dashboard/super-admin/institutions" className="inline-flex items-center gap-1.5 text-xs font-semibold text-blue-200 hover:text-white transition">
              <span>&larr;</span> All Institutions
            </Link>
            <div className="flex items-center gap-3">
              <span className="text-3xl">🏛️</span>
              <div>
                <h1 className="text-2xl font-bold text-white tracking-tight">{client?.name}</h1>
                <div className="flex items-center gap-2 mt-1">
                  <span className="text-xs text-blue-200 font-mono bg-white/10 px-2.5 py-0.5 rounded-md border border-white/10">
                    ID: {clientId}
                  </span>
                  <button
                    onClick={copyClientId}
                    className="text-[11px] font-semibold text-blue-300 hover:text-white underline cursor-pointer"
                  >
                    {copiedId ? "Copied!" : "Copy ID"}
                  </button>
                </div>
              </div>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <Link
              href={`/dashboard/super-admin/institutions/${clientId}/analytics`}
              className="rounded-xl bg-white/10 hover:bg-white/20 border border-white/20 px-4 py-2 text-xs font-semibold text-white transition backdrop-blur-xs flex items-center gap-2 shadow-xs"
            >
              <span>📈</span> Institution Analytics
            </Link>
          </div>
        </div>

        {/* Quick Summary Metrics */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mt-6 pt-5 border-t border-white/10">
          <div className="rounded-xl bg-white/5 border border-white/10 p-3">
            <p className="text-[11px] font-medium text-blue-200 uppercase tracking-wider">Active Interfaces</p>
            <p className="text-xl font-bold text-white mt-0.5">{activeSetups.length} <span className="text-xs font-normal text-blue-300">/ {setups.length}</span></p>
          </div>
          <div className="rounded-xl bg-white/5 border border-white/10 p-3">
            <p className="text-[11px] font-medium text-blue-200 uppercase tracking-wider">Theme Color</p>
            <div className="flex items-center gap-2 mt-1">
              <span className="h-4 w-4 rounded-full border border-white/30" style={{ backgroundColor: client?.settings?.theme_color || "#1E40AF" }} />
              <span className="text-sm font-mono text-white font-semibold">{client?.settings?.theme_color || "#1E40AF"}</span>
            </div>
          </div>
          <div className="rounded-xl bg-white/5 border border-white/10 p-3">
            <p className="text-[11px] font-medium text-blue-200 uppercase tracking-wider">Max History Turns</p>
            <p className="text-xl font-bold text-white mt-0.5">{client?.settings?.max_history_turns ?? 5} <span className="text-xs font-normal text-blue-300">turns</span></p>
          </div>
          <div className="rounded-xl bg-white/5 border border-white/10 p-3">
            <p className="text-[11px] font-medium text-blue-200 uppercase tracking-wider">RAG Memory</p>
            <p className="text-xl font-bold text-white mt-0.5 capitalize">{client?.settings?.context_mode || "Adaptive"}</p>
          </div>
        </div>
      </div>

      {/* SECTION 1: Configured Channel Interfaces & Interactive Menus */}
      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-lg font-bold text-gray-900 flex items-center gap-2">
              <span>📱</span> Channel Interfaces &amp; Interactive Menus
            </h2>
            <p className="text-xs text-gray-500 mt-0.5">
              Select any interface to configure its credentials, interactive menu state machine, button flows, and channel-specific RAG.
            </p>
          </div>
          <span className="text-xs font-semibold bg-blue-50 text-blue-700 px-3 py-1 rounded-full border border-blue-200">
            {activeSetups.length} Active
          </span>
        </div>

        {activeSetups.length === 0 ? (
          <div className="rounded-2xl border-2 border-dashed border-gray-200 bg-white p-8 text-center text-sm text-gray-400">
            No active interfaces configured. Toggle any channel below to activate.
          </div>
        ) : (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {activeSetups.map(s => (
              <SetupCard key={s.channel} setup={s} clientId={clientId} onToggle={handleToggle} />
            ))}
          </div>
        )}
      </div>

      {/* SECTION 2: General Institution & AI Persona Settings */}
      <div className="space-y-3">
        <div>
          <h2 className="text-lg font-bold text-gray-900 flex items-center gap-2">
            <span>🤖</span> General &amp; AI Persona Configuration
          </h2>
          <p className="text-xs text-gray-500 mt-0.5">
            Core institution identity, baseline system persona prompt, and global chat parameters.
          </p>
        </div>
        {client && <GeneralSection clientId={clientId} initial={client} />}
      </div>

      {/* SECTION 3: Available Channels to Activate */}
      {inactiveSetups.length > 0 && (
        <div className="space-y-3 pt-2">
          <div>
            <h2 className="text-base font-semibold text-gray-600 flex items-center gap-2">
              <span>🔌</span> Available Interfaces to Activate
            </h2>
            <p className="text-xs text-gray-400 mt-0.5">
              Toggle to enable new communication channels for this institution.
            </p>
          </div>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {inactiveSetups.map(s => (
              <SetupCard key={s.channel} setup={s} clientId={clientId} onToggle={handleToggle} />
            ))}
          </div>
        </div>
      )}

      {/* SECTION 4: Danger Zone */}
      {client && (
        <div className="rounded-2xl border border-red-200 bg-red-50/30 p-6 shadow-xs">
          <h2 className="mb-1 text-sm font-bold text-red-800 flex items-center gap-2">
            <span>⚠️</span> Danger Zone
          </h2>
          <p className="mb-4 text-xs text-red-600">
            Permanently delete this institution, all associated admin accounts, and knowledge documents.
          </p>
          <button
            onClick={() => setShowDelete(true)}
            className="rounded-xl bg-red-600 px-4 py-2 text-xs font-bold text-white hover:bg-red-700 transition shadow-xs"
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
