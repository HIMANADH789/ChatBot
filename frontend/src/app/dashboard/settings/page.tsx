"use client";

import { useState, useEffect } from "react";
import { api } from "@/lib/api";
import type { ClientSettings, SubMenu, MenuNode, MenuGraphNode, ContextImage, DescriptiveRule } from "@/types";
import { MenuGraphBuilder } from "@/components/MenuGraphBuilder";


function getClientIdFromToken(): string {
  if (typeof window === "undefined") return "";
  const token = localStorage.getItem("token");
  if (!token) return "";
  try {
    const payload = JSON.parse(atob(token.split(".")[1]));
    return payload.client_id || "";
  } catch {
    return "";
  }
}

const DEFAULTS: ClientSettings = {
  welcome_message: "Hello! How can I help you today?",
  chatbot_title: "AI Front Desk",
  system_prompt: `You are a helpful front desk assistant for an educational institution.
Answer questions ONLY based on the provided context. Do not make up information.
If the context does not contain enough information to answer the question, say so clearly.
Be concise, friendly, and professional.`,
  theme_color: "#1E40AF",
  max_history_turns: 5,
  context_mode: "none",
  context_instructions: "",
  context_capacity: 4,
  menu_options: [],
  menu_tree: [],
  menu_graph_nodes: [
    {
      node_id: "MENU_ROOT",
      menu_number: "1.0",
      title: "Welcome & Select Program Stream",
      whatsapp_media: {
        image_url: "",
        caption: "Welcome to our institution",
      },
      frequency: "always",
      options: [
        {
          option_number: "1",
          button_text: "Commerce / CA",
          target_type: "NAVIGATE_MENU",
          target_id: "MENU_COMMERCE",
        },
        {
          option_number: "2",
          button_text: "Admissions Info",
          target_type: "TRIGGER_RAG",
          rag_prompt: "What are the admission requirements and application process?",
        },
      ],
    },
    {
      node_id: "MENU_COMMERCE",
      menu_number: "1.1",
      title: "Commerce & Professional Programs",
      whatsapp_media: {
        image_url: "",
        caption: "Commerce Stream Brochure",
      },
      frequency: "always",
      options: [
        {
          option_number: "1",
          button_text: "CA Foundation",
          target_type: "TRIGGER_RAG",
          rag_prompt: "What is the fee structure and syllabus for CA Foundation?",
        },
        {
          option_number: "2",
          button_text: "CA Intermediate",
          target_type: "TRIGGER_RAG",
          rag_prompt: "What is the eligibility and course structure for CA Intermediate?",
        },
      ],
    },
  ],
  menu_graph_root_node_id: "MENU_ROOT",
  context_images: [],
  descriptive_rules: [],
};

function newSubMenu(): SubMenu {
  return { id: crypto.randomUUID(), label: "New Submenu", sub_questions: [] };
}

export default function SettingsPage() {
  const [clientId, setClientId] = useState("");
  const [backendUrl, setBackendUrl] = useState("http://localhost:8000");
  const [copied, setCopied] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  const [settings, setSettings] = useState<ClientSettings>(DEFAULTS);
  const [setups, setSetups] = useState<any[]>([]);
  const [setupConfigs, setSetupConfigs] = useState<Record<string, any>>({});
  const [savingSetups, setSavingSetups] = useState<Record<string, boolean>>({});

  useEffect(() => {
    let id = getClientIdFromToken();
    if (id) setClientId(id);

    api.getMyProfile().then((profile) => {
      const activeId = profile.client_id || (profile.client as any)?.client_id || id;
      if (activeId) {
        setClientId(activeId);
        id = activeId;
      }
      const s = (profile.client as unknown as { settings?: any })?.settings;
      const setupsDict = s?.setups ?? {};
      const activeSetup = setupsDict?.whatsapp ?? setupsDict?.widget ?? {};

      setSettings({
        welcome_message: s?.welcome_message ?? DEFAULTS.welcome_message,
        chatbot_title: s?.chatbot_title ?? DEFAULTS.chatbot_title,
        system_prompt: s?.system_prompt ?? activeSetup?.system_prompt ?? DEFAULTS.system_prompt,
        theme_color: s?.theme_color ?? DEFAULTS.theme_color,
        max_history_turns: s?.max_history_turns ?? DEFAULTS.max_history_turns,
        context_mode: s?.context_mode ?? activeSetup?.context_mode ?? DEFAULTS.context_mode,
        context_instructions: s?.context_instructions ?? activeSetup?.context_instructions ?? DEFAULTS.context_instructions,
        context_capacity: s?.context_capacity ?? activeSetup?.context_capacity ?? DEFAULTS.context_capacity,
        menu_options: s?.menu_options ?? DEFAULTS.menu_options,
        menu_tree: (s?.menu_tree && s.menu_tree.length > 0) ? s.menu_tree : (activeSetup?.menu_tree ?? DEFAULTS.menu_tree),
        menu_graph_nodes: (s?.menu_graph_nodes && s.menu_graph_nodes.length > 0)
          ? s.menu_graph_nodes
          : (activeSetup?.menu_graph_nodes && activeSetup.menu_graph_nodes.length > 0)
          ? activeSetup.menu_graph_nodes
          : DEFAULTS.menu_graph_nodes,
        menu_graph_root_node_id: s?.menu_graph_root_node_id ?? activeSetup?.menu_graph_root_node_id ?? DEFAULTS.menu_graph_root_node_id,
        context_images: (s?.context_images && s.context_images.length > 0) ? s.context_images : (activeSetup?.context_images ?? DEFAULTS.context_images),
        descriptive_rules: (s?.descriptive_rules && s.descriptive_rules.length > 0) ? s.descriptive_rules : (activeSetup?.descriptive_rules ?? DEFAULTS.descriptive_rules),
      });

      if (activeId) {
        api.listSetups(activeId).then(res => {
          setSetups(res.setups);
          res.setups.filter(s => s.enabled && ["whatsapp", "facebook", "telegram", "slack"].includes(s.channel)).forEach(setup => {
            api.getSetupConfig(activeId, setup.channel).then(detail => {
              setSetupConfigs(prev => ({ ...prev, [setup.channel]: detail.config }));
            }).catch(() => {});
          });
        }).catch(() => {}).finally(() => setLoading(false));
      } else {
        setLoading(false);
      }
    }).catch(() => setLoading(false));
  }, []);

  async function saveIntegrationConfig(channel: string) {
    if (!clientId) return;
    setSavingSetups(prev => ({ ...prev, [channel]: true }));
    try {
      await api.updateSetupConfig(clientId, channel, setupConfigs[channel]);
      alert(`${channel} configuration saved!`);
    } catch (err: any) {
      alert(`Failed to save ${channel}: ` + err.message);
    } finally {
      setSavingSetups(prev => ({ ...prev, [channel]: false }));
    }
  }

  const widgetCode = `<script src="${backendUrl}/api/clients/${clientId}/widget.js" data-client-id="${clientId}" data-theme-color="${settings.theme_color}"></script>`;

  function copyCode() {
    navigator.clipboard.writeText(widgetCode);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  async function saveSettings() {
    if (!clientId) return;
    setSaving(true);
    setError("");
    try {
      await api.updateClientSettings(clientId, settings as unknown as Record<string, unknown>);
      setSaved(true);
      setTimeout(() => setSaved(false), 3000);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save");
    } finally {
      setSaving(false);
    }
  }

  if (loading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <div className="h-8 w-8 animate-spin rounded-full border-4 border-blue-600 border-t-transparent" />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Settings</h1>
        <span className="text-sm text-gray-500">
          Client ID: <span className="font-medium text-blue-600">{clientId}</span>
        </span>
      </div>

      {/* Chatbot Behaviour */}
      <div className="rounded-xl bg-white p-6 shadow-sm">
        <h2 className="mb-1 text-lg font-semibold">Chatbot Behaviour</h2>
        <p className="mb-5 text-sm text-gray-500">
          Configure how the chatbot introduces itself and responds to users.
        </p>

        <div className="space-y-5">
          <div>
            <label className="mb-1 block text-sm font-medium text-gray-700">
              Welcome Message
            </label>
            <p className="mb-2 text-xs text-gray-400">
              The first message users see when they open the chat widget.
            </p>
            <textarea
              value={settings.welcome_message}
              onChange={(e) =>
                setSettings((s) => ({ ...s, welcome_message: e.target.value }))
              }
              rows={5}
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
              placeholder={"Hello! 👋\nWelcome to our support system.\nHow can I help you today?"}
            />
          </div>

          <div>
            <label className="mb-1 block text-sm font-medium text-gray-700">
              Chatbot Title
            </label>
            <p className="mb-2 text-xs text-gray-400">
              The title displayed at the top of the chat window.
            </p>
            <input
              type="text"
              value={settings.chatbot_title}
              onChange={(e) =>
                setSettings((s) => ({ ...s, chatbot_title: e.target.value }))
              }
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
              placeholder="e.g. AI Front Desk"
            />
          </div>

          <div>
            <label className="mb-1 block text-sm font-medium text-gray-700">
              System Prompt
            </label>
            <p className="mb-2 text-xs text-gray-400">
              Instructions that define the chatbot&apos;s personality, tone, and rules. This is
              sent to the AI on every query — be specific about your institution&apos;s name and
              style.
            </p>
            <textarea
              value={settings.system_prompt}
              onChange={(e) =>
                setSettings((s) => ({ ...s, system_prompt: e.target.value }))
              }
              rows={7}
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
              placeholder="You are a helpful assistant for..."
            />
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="mb-1 block text-sm font-medium text-gray-700">
                Theme Color
              </label>
              <div className="flex items-center gap-2">
                <input
                  type="color"
                  value={settings.theme_color}
                  onChange={(e) =>
                    setSettings((s) => ({ ...s, theme_color: e.target.value }))
                  }
                  className="h-10 w-14 cursor-pointer rounded border border-gray-300"
                />
                <input
                  value={settings.theme_color}
                  onChange={(e) =>
                    setSettings((s) => ({ ...s, theme_color: e.target.value }))
                  }
                  className="flex-1 rounded-lg border border-gray-300 px-3 py-2 text-sm font-mono"
                  placeholder="#1E40AF"
                />
              </div>
            </div>

            <div>
              <label className="mb-1 block text-sm font-medium text-gray-700">
                Conversation Memory (turns)
              </label>
              <p className="mb-1 text-xs text-gray-400">
                How many past exchanges the bot remembers.
              </p>
              <select
                value={settings.max_history_turns}
                onChange={(e) =>
                  setSettings((s) => ({
                    ...s,
                    max_history_turns: Number(e.target.value),
                  }))
                }
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm"
              >
                {[1, 3, 5, 10].map((n) => (
                  <option key={n} value={n}>
                    {n} turns
                  </option>
                ))}
              </select>
            </div>
          </div>

          {/* Context-Adaptive RAG & Multi-Turn Memory */}
          <div className="rounded-xl border border-indigo-100 bg-indigo-50/50 p-5 space-y-4">
            <div className="flex items-center justify-between">
              <div>
                <h3 className="text-sm font-semibold text-indigo-950 flex items-center gap-2">
                  <span>🧠 Context-Adaptive RAG (Context Carrying)</span>
                  <span className={`px-2 py-0.5 rounded-full text-[11px] font-medium ${
                    settings.context_mode === "adaptive" ? "bg-indigo-200 text-indigo-900" :
                    settings.context_mode === "full" ? "bg-purple-200 text-purple-900" : "bg-gray-200 text-gray-700"
                  }`}>
                    {(settings.context_mode || "none").toUpperCase()}
                  </span>
                </h3>
                <p className="text-xs text-indigo-700 mt-0.5">
                  Resolves pronouns (&quot;it&quot;, &quot;its fee&quot;, &quot;that department&quot;) into unambiguous search queries before vector retrieval.
                </p>
              </div>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div>
                <label className="mb-1 block text-xs font-semibold text-gray-700">
                  Context Carrying Mode
                </label>
                <select
                  value={settings.context_mode || "none"}
                  onChange={(e) => setSettings((s) => ({ ...s, context_mode: e.target.value }))}
                  className="w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
                >
                  <option value="none">None (Standard / Standalone Retrieval — Default)</option>
                  <option value="adaptive">Adaptive (Auto-detects pronouns &amp; follow-up questions)</option>
                  <option value="full">Full (Always synthesizes query against chat history)</option>
                </select>
              </div>

              <div>
                <label className="mb-1 block text-xs font-semibold text-gray-700">
                  Context Memory Capacity
                </label>
                <div className="flex items-center gap-2">
                  <input
                    type="number"
                    min={1}
                    max={10}
                    value={settings.context_capacity ?? 4}
                    onChange={(e) => setSettings((s) => ({ ...s, context_capacity: Math.max(1, Math.min(10, Number(e.target.value))) }))}
                    className="w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
                  />
                  <span className="text-xs text-gray-500 shrink-0">turns</span>
                </div>
              </div>
            </div>

            <div>
              <label className="mb-1 block text-xs font-semibold text-gray-700">
                Tracked Details &amp; Developer Directives
              </label>
              <p className="mb-1 text-xs text-gray-400">
                Specify entities, fields, and details to retain in direct development terminology (zero translation overhead).
              </p>
              <textarea
                rows={2}
                value={settings.context_instructions || ""}
                onChange={(e) => setSettings((s) => ({ ...s, context_instructions: e.target.value }))}
                placeholder="e.g., Track course_name, branch, fee_structure, admission_category, eligibility_criteria, application_deadline, semester."
                className="w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-xs font-mono focus:border-blue-500 focus:outline-none"
              />
            </div>
          </div>
        </div>

        {error && (
          <p className="mt-3 text-sm text-red-600">{error}</p>
        )}

        <div className="mt-6 flex items-center gap-3">
          <button
            onClick={saveSettings}
            disabled={saving}
            className="rounded-lg bg-blue-600 px-5 py-2.5 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
          >
            {saving ? "Saving..." : "Save Settings"}
          </button>
          {saved && (
            <span className="text-sm text-green-600">Settings saved!</span>
          )}
        </div>
      </div>

      {/* ⚡ Visual Menu & Channel Builder (Graph State Machine) */}
      <MenuGraphBuilder
        clientId={clientId}
        nodes={settings.menu_graph_nodes || []}
        rootNodeId={settings.menu_graph_root_node_id || "MENU_ROOT"}
        onChange={(updatedNodes, updatedRootId) => {
          setSettings((s) => ({
            ...s,
            menu_graph_nodes: updatedNodes,
            menu_graph_root_node_id: updatedRootId,
          }));
        }}
        onSaved={() => {
          setSaved(true);
          setTimeout(() => setSaved(false), 3000);
        }}
      />

      {/* Widget Integration */}
      <div className="rounded-xl bg-white p-6 shadow-sm">
        <h2 className="mb-1 text-lg font-semibold">Widget Integration</h2>
        <p className="mb-5 text-sm text-gray-500">
          Paste this script tag before the closing &lt;/body&gt; tag on your website.
        </p>

        <div className="mb-4">
          <label className="mb-1 block text-sm font-medium text-gray-700">
            Backend URL
          </label>
          <input
            value={backendUrl}
            onChange={(e) => setBackendUrl(e.target.value)}
            className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm"
            placeholder="https://your-backend.onrender.com"
          />
        </div>

        <div className="relative">
          <pre className="overflow-x-auto rounded-lg bg-gray-900 p-4 text-sm text-green-400">
            {widgetCode}
          </pre>
          <button
            onClick={copyCode}
            className="absolute right-3 top-3 rounded bg-gray-700 px-3 py-1 text-xs text-white hover:bg-gray-600"
          >
            {copied ? "Copied!" : "Copy"}
          </button>
        </div>
      </div>

      {/* Integrations & Channels */}
      {setups.filter(s => s.enabled && s.channel !== "widget" && s.channel !== "web_api").length > 0 && (
        <div className="rounded-xl bg-white p-6 shadow-sm">
          <h2 className="mb-1 text-lg font-semibold">Integrations &amp; Channels</h2>
          <p className="mb-5 text-sm text-gray-500">
            Configure credentials for third-party integrations enabled for your account.
          </p>

          <div className="space-y-6">
            {setups.filter(s => s.enabled && s.channel !== "widget" && s.channel !== "web_api").map(setup => (
              <div key={setup.channel} className="rounded-lg border border-gray-200 p-5">
                <div className="flex items-center gap-2 mb-4">
                  <span className="text-xl">{setup.emoji}</span>
                  <h3 className="font-semibold text-gray-800">{setup.label}</h3>
                </div>

                {setupConfigs[setup.channel] ? (
                  <div className="space-y-4">
                    {/* Channel specific fields */}
                    {setup.channel === "whatsapp" && (
                      <>
                        <div>
                          <label className="mb-1 block text-sm font-medium text-gray-700">Phone Number ID</label>
                          <input
                            type="text"
                            value={setupConfigs[setup.channel].phone_number_id || ""}
                            onChange={(e) => setSetupConfigs(prev => ({ ...prev, [setup.channel]: { ...prev[setup.channel], phone_number_id: e.target.value } }))}
                            className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm"
                          />
                        </div>
                        <div>
                          <label className="mb-1 block text-sm font-medium text-gray-700">Access Token</label>
                          <input
                            type="password"
                            value={setupConfigs[setup.channel].access_token || ""}
                            onChange={(e) => setSetupConfigs(prev => ({ ...prev, [setup.channel]: { ...prev[setup.channel], access_token: e.target.value } }))}
                            className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm"
                            placeholder={setupConfigs[setup.channel].access_token === "••••••••••••••••" ? "••••••••••••••••" : ""}
                          />
                        </div>
                        <div>
                          <label className="mb-1 block text-sm font-medium text-gray-700">Verify Token</label>
                          <input
                            type="password"
                            value={setupConfigs[setup.channel].verify_token || ""}
                            onChange={(e) => setSetupConfigs(prev => ({ ...prev, [setup.channel]: { ...prev[setup.channel], verify_token: e.target.value } }))}
                            className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm"
                            placeholder={setupConfigs[setup.channel].verify_token === "••••••••••••••••" ? "••••••••••••••••" : ""}
                          />
                        </div>
                      </>
                    )}

                    {/* Generic Fallback for other channels if needed */}
                    {setup.channel !== "whatsapp" && Object.keys(setupConfigs[setup.channel]).map(key => {
                      if (["enabled", "rate_limit_rpm", "rate_limit_rpd", "max_queries_per_session"].includes(key)) return null;
                      return (
                        <div key={key}>
                          <label className="mb-1 block text-sm font-medium text-gray-700">{key.replace(/_/g, ' ').toUpperCase()}</label>
                          <input
                            type="text"
                            value={setupConfigs[setup.channel][key] || ""}
                            onChange={(e) => setSetupConfigs(prev => ({ ...prev, [setup.channel]: { ...prev[setup.channel], [key]: e.target.value } }))}
                            className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm"
                          />
                        </div>
                      );
                    })}

                    <button
                      onClick={() => saveIntegrationConfig(setup.channel)}
                      disabled={savingSetups[setup.channel]}
                      className="mt-4 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
                    >
                      {savingSetups[setup.channel] ? "Saving..." : `Save ${setup.label}`}
                    </button>
                  </div>
                ) : (
                  <div className="animate-pulse flex h-10 w-full bg-gray-100 rounded"></div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Quick Guide */}
      <div className="rounded-xl bg-white p-6 shadow-sm">
        <h2 className="mb-4 text-lg font-semibold">Quick Setup Guide</h2>
        <ol className="list-decimal space-y-2 pl-5 text-sm text-gray-600">
          <li>Upload your institution&apos;s documents in the <strong>Documents</strong> section</li>
          <li>Configure the chatbot behaviour above and click <strong>Save Settings</strong></li>
          <li>Test the chatbot using the <strong>Test Chat</strong> page</li>
          <li>Copy the widget code and paste it on your website</li>
        </ol>
      </div>
    </div>
  );
}
