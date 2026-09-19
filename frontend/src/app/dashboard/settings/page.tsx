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

export default function SettingsPage() {
  const [clientId, setClientId] = useState("");
  const [backendUrl, setBackendUrl] = useState("http://localhost:8000");
  const [copied, setCopied] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState<"persona" | "menu_graph" | "context_images" | "web_config" | "channels">("persona");

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
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-gray-200 pb-4">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Institution Configuration</h1>
          <p className="text-xs text-gray-500 mt-1">Manage AI personality, dynamic menu state machine, web widget script, and multi-channel parameters.</p>
        </div>
        <span className="text-sm text-gray-500 bg-gray-100 px-3 py-1 rounded-lg border border-gray-200 font-mono">
          Client ID: <span className="font-bold text-blue-600">{clientId}</span>
        </span>
      </div>

      {/* Modern Configuration Tabs */}
      <div className="flex flex-wrap gap-2 border-b border-gray-200 pb-2">
        <button
          onClick={() => setActiveTab("persona")}
          className={`flex items-center gap-2 px-4 py-2.5 rounded-xl text-xs font-semibold transition ${
            activeTab === "persona"
              ? "bg-blue-600 text-white shadow-sm"
              : "bg-white text-gray-600 hover:bg-gray-100 hover:text-gray-900 border border-gray-200"
          }`}
        >
          <span>🤖</span> AI Persona &amp; Behaviour
        </button>

        <button
          onClick={() => setActiveTab("menu_graph")}
          className={`flex items-center gap-2 px-4 py-2.5 rounded-xl text-xs font-semibold transition ${
            activeTab === "menu_graph"
              ? "bg-blue-600 text-white shadow-sm"
              : "bg-white text-gray-600 hover:bg-gray-100 hover:text-gray-900 border border-gray-200"
          }`}
        >
          <span>⚡</span> Menu Graph State Machine
        </button>

        <button
          onClick={() => setActiveTab("context_images")}
          className={`flex items-center gap-2 px-4 py-2.5 rounded-xl text-xs font-semibold transition ${
            activeTab === "context_images"
              ? "bg-blue-600 text-white shadow-sm"
              : "bg-white text-gray-600 hover:bg-gray-100 hover:text-gray-900 border border-gray-200"
          }`}
        >
          <span>🖼️</span> Context Images &amp; Media
        </button>

        <button
          onClick={() => setActiveTab("web_config")}
          className={`flex items-center gap-2 px-4 py-2.5 rounded-xl text-xs font-semibold transition ${
            activeTab === "web_config"
              ? "bg-blue-600 text-white shadow-sm"
              : "bg-white text-gray-600 hover:bg-gray-100 hover:text-gray-900 border border-gray-200"
          }`}
        >
          <span>🌐</span> Web Widget &amp; Integration Code
        </button>

        <button
          onClick={() => setActiveTab("channels")}
          className={`flex items-center gap-2 px-4 py-2.5 rounded-xl text-xs font-semibold transition ${
            activeTab === "channels"
              ? "bg-blue-600 text-white shadow-sm"
              : "bg-white text-gray-600 hover:bg-gray-100 hover:text-gray-900 border border-gray-200"
          }`}
        >
          <span>💬</span> WhatsApp &amp; Channel Credentials
        </button>
      </div>

      {/* Tab 1: AI Persona & Chatbot Behaviour */}
      {activeTab === "persona" && (
        <div className="rounded-2xl bg-white p-6 shadow-sm border border-gray-200 space-y-6">
          <div>
            <h2 className="text-lg font-semibold text-gray-900">Chatbot Personality &amp; Persona</h2>
            <p className="text-xs text-gray-500 mt-0.5">
              Configure how the AI introduces itself, speaks, and responds during grounded fallback or RAG queries.
            </p>
          </div>

          <div className="space-y-5">
            <div>
              <label className="mb-1 block text-sm font-medium text-gray-700">
                Welcome Message
              </label>
              <p className="mb-2 text-xs text-gray-400">
                The default greeting presented when a visitor opens the chat widget.
              </p>
              <textarea
                value={settings.welcome_message}
                onChange={(e) =>
                  setSettings((s) => ({ ...s, welcome_message: e.target.value }))
                }
                rows={4}
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                placeholder={"Hello! 👋\nWelcome to our institution.\nHow can I assist you today?"}
              />
            </div>

            <div>
              <label className="mb-1 block text-sm font-medium text-gray-700">
                Chatbot Title
              </label>
              <p className="mb-2 text-xs text-gray-400">
                Header text shown in the widget header.
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
                System prompt defining the assistant&apos;s persona, tone, rules, and grounding parameters.
              </p>
              <textarea
                value={settings.system_prompt}
                onChange={(e) =>
                  setSettings((s) => ({ ...s, system_prompt: e.target.value }))
                }
                rows={6}
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm font-mono focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                placeholder="You are a helpful assistant for..."
              />
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
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
                  Number of past dialogue turns maintained in history.
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

            {/* Context-Adaptive RAG */}
            <div className="rounded-xl border border-indigo-100 bg-indigo-50/50 p-5 space-y-4">
              <div>
                <h3 className="text-sm font-semibold text-indigo-950 flex items-center gap-2">
                  <span>🧠 Context-Adaptive RAG &amp; Multi-Turn Memory</span>
                  <span className={`px-2 py-0.5 rounded-full text-[11px] font-medium ${
                    settings.context_mode === "adaptive" ? "bg-indigo-200 text-indigo-900" :
                    settings.context_mode === "full" ? "bg-purple-200 text-purple-900" : "bg-gray-200 text-gray-700"
                  }`}>
                    {(settings.context_mode || "none").toUpperCase()}
                  </span>
                </h3>
                <p className="text-xs text-indigo-700 mt-0.5">
                  Resolves pronouns (&quot;it&quot;, &quot;its fee&quot;) into explicit queries before vector similarity search.
                </p>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div>
                  <label className="mb-1 block text-xs font-semibold text-gray-700">
                    Context Mode
                  </label>
                  <select
                    value={settings.context_mode || "none"}
                    onChange={(e) => setSettings((s) => ({ ...s, context_mode: e.target.value }))}
                    className="w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
                  >
                    <option value="none">None (Standard / Standalone Retrieval)</option>
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
                  Tracked Entities &amp; Directives
                </label>
                <textarea
                  rows={2}
                  value={settings.context_instructions || ""}
                  onChange={(e) => setSettings((s) => ({ ...s, context_instructions: e.target.value }))}
                  placeholder="e.g., Track course_name, branch, fee_structure, eligibility_criteria."
                  className="w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-xs font-mono focus:border-blue-500 focus:outline-none"
                />
              </div>
            </div>
          </div>

          {error && <p className="mt-3 text-sm text-red-600">{error}</p>}

          <div className="flex items-center gap-3 pt-2">
            <button
              onClick={saveSettings}
              disabled={saving}
              className="rounded-lg bg-blue-600 px-5 py-2.5 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
            >
              {saving ? "Saving..." : "Save AI Persona Settings"}
            </button>
            {saved && <span className="text-sm text-green-600">Settings saved!</span>}
          </div>
        </div>
      )}

      {/* Tab 2: Menu Graph State Machine */}
      {activeTab === "menu_graph" && (
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
      )}

      {/* Tab 3: Context Images & Media Registry */}
      {activeTab === "context_images" && (
        <div className="rounded-2xl bg-white p-6 shadow-sm border border-gray-200 space-y-6">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
            <div>
              <div className="flex items-center gap-2">
                <span className="text-xl">🖼️</span>
                <h2 className="text-lg font-semibold text-gray-900">Context Images &amp; Media Registry</h2>
              </div>
              <p className="text-xs text-gray-500 mt-1">
                Attach images (brochures, fee charts, campus maps) that automatically send when user context/intent matches, or once per session.
              </p>
            </div>
            <button
              onClick={() => {
                const newImg: ContextImage = {
                  id: crypto.randomUUID(),
                  title: "New Context Image",
                  image_path: "https://example.com/image.jpg",
                  descriptor_tag: "When user asks about course fees, brochure, or campus details",
                  caption: "Official Program Brochure & Details",
                  frequency: "on_intent",
                };
                setSettings(s => ({
                  ...s,
                  context_images: [...(s.context_images || []), newImg]
                }));
              }}
              className="flex items-center gap-1.5 rounded-xl bg-emerald-600 px-4 py-2 text-xs font-semibold text-white hover:bg-emerald-700 transition"
            >
              <span>+</span> Add Context Image
            </button>
          </div>

          <div className="rounded-xl bg-indigo-50/60 border border-indigo-100 p-4 text-xs text-indigo-950 space-y-1.5">
            <p className="font-semibold text-indigo-900">💡 Context Delivery Rules:</p>
            <p>• <strong>Trigger on Context / Intent Match (<code className="bg-indigo-100 px-1 rounded font-mono">on_intent</code>):</strong> Evaluates the user query against the trigger descriptor tag. If it matches, the assistant includes this image in the response.</p>
            <p>• <strong>Display Once per Session (<code className="bg-indigo-100 px-1 rounded font-mono">only_once</code>):</strong> Sends the image the first time intent matches during a session, suppressing repeat sends for the rest of the conversation.</p>
          </div>

          <div className="space-y-4">
            {(!settings.context_images || settings.context_images.length === 0) ? (
              <div className="rounded-xl border border-dashed border-gray-300 p-8 text-center text-sm text-gray-500">
                No context images configured. Click &quot;Add Context Image&quot; above to add one.
              </div>
            ) : (
              settings.context_images.map((img, idx) => (
                <div key={img.id || idx} className="rounded-xl border border-gray-200 bg-white p-4 space-y-3">
                  <div className="flex items-center justify-between gap-3">
                    <span className="text-xs font-bold px-2 py-0.5 rounded bg-emerald-100 text-emerald-800">
                      Context Image #{idx + 1}
                    </span>
                    <button
                      onClick={() => {
                        const updated = (settings.context_images || []).filter((_, i) => i !== idx);
                        setSettings(s => ({ ...s, context_images: updated }));
                      }}
                      className="text-xs text-red-500 hover:text-red-700 font-medium hover:underline"
                    >
                      Delete Image
                    </button>
                  </div>

                  <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                    <div>
                      <label className="block text-xs font-medium text-gray-700 mb-1">
                        Image Title
                      </label>
                      <input
                        type="text"
                        value={img.title || ""}
                        onChange={(e) => {
                          const next = [...(settings.context_images || [])];
                          next[idx] = { ...img, title: e.target.value };
                          setSettings(s => ({ ...s, context_images: next }));
                        }}
                        placeholder="e.g. Fee Structure Chart"
                        className="w-full rounded-lg border border-gray-300 px-3 py-2 text-xs focus:border-blue-500 focus:outline-none"
                      />
                    </div>

                    <div>
                      <label className="block text-xs font-medium text-gray-700 mb-1">
                        Image Path or Public URL
                      </label>
                      <input
                        type="text"
                        value={img.image_path || ""}
                        onChange={(e) => {
                          const next = [...(settings.context_images || [])];
                          next[idx] = { ...img, image_path: e.target.value };
                          setSettings(s => ({ ...s, context_images: next }));
                        }}
                        placeholder="e.g. https://example.com/fees.png or /images/brochure.jpg"
                        className="w-full rounded-lg border border-gray-300 px-3 py-2 text-xs font-mono focus:border-blue-500 focus:outline-none"
                      />
                    </div>
                  </div>

                  <div className="border-t border-gray-100 pt-3">
                    <div>
                      <label className="block text-xs font-medium text-gray-700 mb-1">
                        🏷️ Trigger Context &amp; State Directive <span className="text-gray-400 font-normal">(Prompt rule interpreting when &amp; how often to display this image)</span>
                      </label>
                      <input
                        type="text"
                        value={img.descriptor_tag || ""}
                        onChange={(e) => {
                          const next = [...(settings.context_images || [])];
                          next[idx] = { ...img, descriptor_tag: e.target.value };
                          setSettings(s => ({ ...s, context_images: next }));
                        }}
                        placeholder="e.g. Display at start of conversation, OR once per session when user inquires about fee breakdown / brochure"
                        className="w-full rounded-lg border border-gray-300 px-3 py-2 text-xs focus:border-blue-500 focus:outline-none"
                      />
                    </div>
                  </div>

                  <div>
                    <label className="block text-xs font-medium text-gray-700 mb-1">
                      Image Caption (optional)
                    </label>
                    <input
                      type="text"
                      value={img.caption || ""}
                      onChange={(e) => {
                        const next = [...(settings.context_images || [])];
                        next[idx] = { ...img, caption: e.target.value };
                        setSettings(s => ({ ...s, context_images: next }));
                      }}
                      placeholder="e.g. Complete SV Professional Fee Breakdown Chart"
                      className="w-full rounded-lg border border-gray-300 px-3 py-2 text-xs focus:border-blue-500 focus:outline-none"
                    />
                  </div>
                </div>
              ))
            )}
          </div>

          {error && <p className="text-sm text-red-600">{error}</p>}

          <div className="flex items-center gap-3 pt-2">
            <button
              onClick={saveSettings}
              disabled={saving}
              className="rounded-lg bg-blue-600 px-5 py-2.5 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
            >
              {saving ? "Saving..." : "Save Context Images Settings"}
            </button>
            {saved && <span className="text-sm text-green-600">Context Images Saved!</span>}
          </div>
        </div>
      )}

      {/* Tab 4: Web Widget Configuration */}
      {activeTab === "web_config" && (
        <div className="rounded-2xl bg-white p-6 shadow-sm border border-gray-200 space-y-6">
          <div>
            <div className="flex items-center gap-2">
              <span className="text-xl">🌐</span>
              <h2 className="text-lg font-semibold text-gray-900">Web Widget &amp; Integration Script</h2>
            </div>
            <p className="text-xs text-gray-500 mt-1">
              Configure embed settings and copy the light JavaScript script tag for your web application.
            </p>
          </div>

          <div className="space-y-4">
            <div>
              <label className="mb-1 block text-sm font-medium text-gray-700">
                Backend API Domain URL
              </label>
              <input
                value={backendUrl}
                onChange={(e) => setBackendUrl(e.target.value)}
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm font-mono"
                placeholder="https://your-backend.onrender.com"
              />
            </div>

            <div>
              <label className="mb-1 block text-sm font-medium text-gray-700">
                Production Script Embed Code
              </label>
              <p className="mb-2 text-xs text-gray-400">
                Paste this script snippet before the closing <code>&lt;/body&gt;</code> tag of your HTML.
              </p>
              <div className="relative">
                <pre className="overflow-x-auto rounded-xl bg-gray-900 p-4 text-xs font-mono text-emerald-400">
                  {widgetCode}
                </pre>
                <button
                  onClick={copyCode}
                  className="absolute right-3 top-3 rounded-md bg-gray-700 px-3 py-1.5 text-xs font-semibold text-white hover:bg-gray-600 transition"
                >
                  {copied ? "Copied!" : "📋 Copy Code"}
                </button>
              </div>
            </div>

            <div className="rounded-xl border border-blue-100 bg-blue-50/50 p-4 space-y-2">
              <h3 className="text-xs font-bold text-blue-900 uppercase tracking-wider">Web Application Features:</h3>
              <ul className="list-disc pl-5 text-xs text-blue-800 space-y-1">
                <li>Option buttons rendered as clean UI button groups / chips.</li>
                <li>Bypasses WhatsApp media image attachments for lightweight payload delivery.</li>
                <li>Allows unconstrained long-form text and markdown.</li>
                <li>Socket sequence deduplication for client web sessions.</li>
              </ul>
            </div>
          </div>
        </div>
      )}

      {/* Tab 4: WhatsApp & Channels Credentials */}
      {activeTab === "channels" && (
        <div className="rounded-2xl bg-white p-6 shadow-sm border border-gray-200 space-y-6">
          <div>
            <div className="flex items-center gap-2">
              <span className="text-xl">💬</span>
              <h2 className="text-lg font-semibold text-gray-900">WhatsApp &amp; Channel Integrations</h2>
            </div>
            <p className="text-xs text-gray-500 mt-1">
              Configure credentials for WhatsApp Cloud API and active external messaging channels.
            </p>
          </div>

          <div className="space-y-6">
            {/* WhatsApp Webhook Endpoint Info */}
            <div className="rounded-xl border border-emerald-200 bg-emerald-50/40 p-4 space-y-2">
              <h3 className="text-xs font-bold text-emerald-900 uppercase tracking-wider">WhatsApp Cloud API Webhook URL:</h3>
              <p className="font-mono text-xs text-emerald-800 bg-white p-2 rounded border border-emerald-200 select-all">
                {`${backendUrl}/api/adapters/whatsapp/webhook`}
              </p>
            </div>

            {setups.filter(s => s.enabled && s.channel !== "widget" && s.channel !== "web_api").length > 0 ? (
              setups.filter(s => s.enabled && s.channel !== "widget" && s.channel !== "web_api").map(setup => (
                <div key={setup.channel} className="rounded-xl border border-gray-200 p-5 space-y-4">
                  <div className="flex items-center gap-2">
                    <span className="text-xl">{setup.emoji}</span>
                    <h3 className="font-semibold text-gray-800">{setup.label} Configuration</h3>
                  </div>

                  {setupConfigs[setup.channel] ? (
                    <div className="space-y-4">
                      {setup.channel === "whatsapp" && (
                        <>
                          <div>
                            <label className="mb-1 block text-sm font-medium text-gray-700">Phone Number ID</label>
                            <input
                              type="text"
                              value={setupConfigs[setup.channel].phone_number_id || ""}
                              onChange={(e) => setSetupConfigs(prev => ({ ...prev, [setup.channel]: { ...prev[setup.channel], phone_number_id: e.target.value } }))}
                              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm font-mono"
                              placeholder="e.g. 109827364512398"
                            />
                          </div>
                          <div>
                            <label className="mb-1 block text-sm font-medium text-gray-700">Meta Access Token</label>
                            <input
                              type="password"
                              value={setupConfigs[setup.channel].access_token || ""}
                              onChange={(e) => setSetupConfigs(prev => ({ ...prev, [setup.channel]: { ...prev[setup.channel], access_token: e.target.value } }))}
                              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm font-mono"
                              placeholder={setupConfigs[setup.channel].access_token === "••••••••••••••••" ? "••••••••••••••••" : "EAAG..."}
                            />
                          </div>
                          <div>
                            <label className="mb-1 block text-sm font-medium text-gray-700">Webhook Verify Token</label>
                            <input
                              type="password"
                              value={setupConfigs[setup.channel].verify_token || ""}
                              onChange={(e) => setSetupConfigs(prev => ({ ...prev, [setup.channel]: { ...prev[setup.channel], verify_token: e.target.value } }))}
                              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm font-mono"
                              placeholder={setupConfigs[setup.channel].verify_token === "••••••••••••••••" ? "••••••••••••••••" : "custom_verify_token"}
                            />
                          </div>
                        </>
                      )}

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
                        className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
                      >
                        {savingSetups[setup.channel] ? "Saving..." : `Save ${setup.label} Configuration`}
                      </button>
                    </div>
                  ) : (
                    <div className="animate-pulse flex h-12 w-full bg-gray-100 rounded-lg"></div>
                  )}
                </div>
              ))
            ) : (
              <div className="rounded-xl border border-dashed border-gray-300 p-6 text-center text-xs text-gray-500">
                No third-party channels currently active. Enable channels under Institution Setups to configure credentials.
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
