"use client";

import React, { useState, useEffect } from "react";
import type { MenuGraphNode, NodeOption, MenuGraphValidationResult } from "@/types";
import { api } from "@/lib/api";

interface MenuGraphBuilderProps {
  clientId: string;
  nodes: MenuGraphNode[];
  rootNodeId?: string;
  onChange: (nodes: MenuGraphNode[], rootNodeId: string) => void;
  onSaved?: () => void;
}

export function MenuGraphBuilder({
  clientId,
  nodes: initialNodes,
  rootNodeId: initialRootId,
  onChange,
  onSaved,
}: MenuGraphBuilderProps) {
  const [nodes, setNodes] = useState<MenuGraphNode[]>(initialNodes || []);
  const [rootNodeId, setRootNodeId] = useState<string>(
    initialRootId || (initialNodes && initialNodes[0]?.node_id) || "MENU_ROOT"
  );
  const [activeNodeId, setActiveNodeId] = useState<string>(
    initialRootId || (initialNodes && initialNodes[0]?.node_id) || ""
  );
  const [previewChannel, setPreviewChannel] = useState<"whatsapp" | "web">("whatsapp");
  const [validation, setValidation] = useState<MenuGraphValidationResult | null>(null);
  const [validating, setValidating] = useState(false);
  const [publishing, setPublishing] = useState(false);
  const [publishMessage, setPublishMessage] = useState<string | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  useEffect(() => {
    if (initialNodes && initialNodes.length > 0) {
      setNodes(initialNodes);
      if (!activeNodeId) {
        setActiveNodeId(initialRootId || initialNodes[0].node_id);
      }
    }
  }, [initialNodes, initialRootId]);

  // Sync back to parent when nodes or root change
  const updateNodes = (newNodes: MenuGraphNode[], newRootId?: string) => {
    setNodes(newNodes);
    const effectiveRoot = newRootId !== undefined ? newRootId : rootNodeId;
    if (newRootId !== undefined) {
      setRootNodeId(newRootId);
    }
    onChange(newNodes, effectiveRoot);
  };

  const activeNode = nodes.find((n) => n.node_id === activeNodeId) || nodes[0];

  const handleAddNode = () => {
    const seq = nodes.length + 1;
    const newNodeId = `MENU_${100 + seq * 10}`;
    const newNode: MenuGraphNode = {
      node_id: newNodeId,
      menu_number: `1.${seq}`,
      title: `Menu Option ${seq}`,
      whatsapp_media: {
        image_url: "",
        caption: "",
      },
      options: [
        {
          option_number: "1",
          button_text: "More Details",
          target_type: "TRIGGER_RAG",
          rag_prompt: `Provide full details regarding Menu Option ${seq}`,
        },
      ],
      frequency: "always",
    };
    const updated = [...nodes, newNode];
    const newRoot = nodes.length === 0 ? newNodeId : rootNodeId;
    updateNodes(updated, newRoot);
    setActiveNodeId(newNodeId);
  };

  const handleDeleteNode = (nodeId: string) => {
    if (nodes.length <= 1) {
      alert("At least one menu node is required.");
      return;
    }
    const updated = nodes.filter((n) => n.node_id !== nodeId);
    let nextRoot = rootNodeId;
    if (rootNodeId === nodeId) {
      nextRoot = updated[0]?.node_id || "";
    }
    updateNodes(updated, nextRoot);
    if (activeNodeId === nodeId) {
      setActiveNodeId(updated[0]?.node_id || "");
    }
  };

  const handleUpdateActiveNode = (patch: Partial<MenuGraphNode>) => {
    if (!activeNode) return;
    const updated = nodes.map((n) =>
      n.node_id === activeNode.node_id ? { ...n, ...patch } : n
    );
    updateNodes(updated);
  };

  const handleAddOption = () => {
    if (!activeNode) return;
    const nextNum = (activeNode.options.length + 1).toString();
    const newOption: NodeOption = {
      option_number: nextNum,
      button_text: `Option ${nextNum}`,
      target_type: "TRIGGER_RAG",
      rag_prompt: "Provide information for this selection",
    };
    const nextOptions = [...activeNode.options, newOption];
    handleUpdateActiveNode({ options: nextOptions });
  };

  const handleUpdateOption = (index: number, patch: Partial<NodeOption>) => {
    if (!activeNode) return;
    const nextOptions = activeNode.options.map((opt, i) =>
      i === index ? { ...opt, ...patch } : opt
    );
    handleUpdateActiveNode({ options: nextOptions });
  };

  const handleDeleteOption = (index: number) => {
    if (!activeNode) return;
    const nextOptions = activeNode.options.filter((_, i) => i !== index);
    handleUpdateActiveNode({ options: nextOptions });
  };

  const runValidation = async () => {
    if (!clientId) return;
    setValidating(true);
    setErrorMsg(null);
    try {
      const res = await api.validateMenuGraph(clientId, nodes, rootNodeId);
      setValidation(res);
    } catch (e: any) {
      setErrorMsg(e.message || "Failed to validate menu graph");
    } finally {
      setValidating(false);
    }
  };

  const handlePublish = async () => {
    if (!clientId) return;
    setPublishing(true);
    setErrorMsg(null);
    setPublishMessage(null);
    try {
      const res = await api.publishMenuGraph(clientId, nodes, rootNodeId);
      setPublishMessage(res.message);
      setValidation(res.validation);
      if (onSaved) onSaved();
      setTimeout(() => setPublishMessage(null), 4000);
    } catch (e: any) {
      setErrorMsg(e.message || "Failed to publish menu graph");
    } finally {
      setPublishing(false);
    }
  };

  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm space-y-6">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-slate-100 pb-5">
        <div>
          <div className="flex items-center gap-2">
            <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-emerald-100 text-emerald-700 text-lg font-bold">
              ⚡
            </span>
            <h2 className="text-xl font-bold text-slate-900">
              Visual Menu & Channel Builder
            </h2>
            <span className="rounded-full bg-blue-50 px-2.5 py-0.5 text-xs font-semibold text-blue-700 border border-blue-200">
              Hybrid State Machine
            </span>
          </div>
          <p className="mt-1 text-sm text-slate-500">
            Build serial-numbered dynamic menu graphs with channel-isolated media and deterministic navigation.
          </p>
        </div>

        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={runValidation}
            disabled={validating}
            className="rounded-lg border border-slate-300 bg-white px-3.5 py-2 text-xs font-semibold text-slate-700 hover:bg-slate-50 hover:text-slate-900 transition disabled:opacity-50"
          >
            {validating ? "Validating..." : "🔍 Validate Graph"}
          </button>
          <button
            type="button"
            onClick={handlePublish}
            disabled={publishing}
            className="rounded-lg bg-emerald-600 px-4 py-2 text-xs font-semibold text-white shadow-sm hover:bg-emerald-700 transition disabled:opacity-50 flex items-center gap-1.5"
          >
            {publishing ? (
              <span className="inline-block h-3.5 w-3.5 animate-spin rounded-full border-2 border-white border-t-transparent" />
            ) : (
              <span>🚀</span>
            )}
            {publishing ? "Publishing..." : "Publish & Pre-Compile"}
          </button>
        </div>
      </div>

      {/* Status Alerts */}
      {publishMessage && (
        <div className="rounded-xl border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-800 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span>✅</span>
            <span className="font-medium">{publishMessage}</span>
          </div>
        </div>
      )}

      {errorMsg && (
        <div className="rounded-xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-800">
          <div className="flex items-center gap-2 font-semibold">
            <span>⚠️</span>
            <span>Validation Error</span>
          </div>
          <p className="mt-1 text-xs">{errorMsg}</p>
        </div>
      )}

      {validation && (
        <div
          className={`rounded-xl border p-4 text-xs ${
            validation.valid
              ? "border-emerald-200 bg-emerald-50/50 text-emerald-900"
              : "border-rose-200 bg-rose-50/50 text-rose-900"
          }`}
        >
          <div className="flex items-center justify-between font-semibold">
            <span>
              {validation.valid
                ? `Graph Valid: ${validation.node_count} nodes indexed (Root: ${validation.root_node_id})`
                : "Graph contains validation issues"}
            </span>
            <span className="text-[11px] opacity-75">Click Validate to refresh</span>
          </div>
          {validation.errors.length > 0 && (
            <ul className="mt-2 list-inside list-disc space-y-1 text-rose-700">
              {validation.errors.map((err, i) => (
                <li key={i}>{err}</li>
              ))}
            </ul>
          )}
          {validation.warnings.length > 0 && (
            <ul className="mt-2 list-inside list-disc space-y-1 text-amber-700">
              {validation.warnings.map((warn, i) => (
                <li key={i}>{warn}</li>
              ))}
            </ul>
          )}
        </div>
      )}

      {/* Main Builder Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        {/* Left Column: Node Navigator */}
        <div className="lg:col-span-4 space-y-3">
          <div className="flex items-center justify-between">
            <span className="text-xs font-bold uppercase tracking-wider text-slate-500">
              Menu Nodes ({nodes.length})
            </span>
            <button
              type="button"
              onClick={handleAddNode}
              className="rounded-md bg-blue-50 px-2.5 py-1 text-xs font-semibold text-blue-700 hover:bg-blue-100 transition"
            >
              + Add Node
            </button>
          </div>

          <div className="space-y-2 max-h-[580px] overflow-y-auto pr-1">
            {nodes.map((node) => {
              const isActive = node.node_id === activeNode?.node_id;
              const isRoot = node.node_id === rootNodeId;
              return (
                <div
                  key={node.node_id}
                  onClick={() => setActiveNodeId(node.node_id)}
                  className={`group cursor-pointer rounded-xl border p-3 transition ${
                    isActive
                      ? "border-blue-500 bg-blue-50/60 shadow-sm ring-1 ring-blue-500"
                      : "border-slate-200 bg-white hover:border-slate-300 hover:bg-slate-50"
                  }`}
                >
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <span className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-[11px] font-bold text-slate-700">
                        {node.menu_number || "—"}
                      </span>
                      <span className="font-semibold text-sm text-slate-800 truncate max-w-[140px]">
                        {node.title || "Untitled Node"}
                      </span>
                    </div>

                    {isRoot && (
                      <span className="rounded-full bg-emerald-100 px-2 py-0.5 text-[10px] font-bold text-emerald-800">
                        ROOT
                      </span>
                    )}
                  </div>

                  <div className="mt-2 flex items-center justify-between text-xs text-slate-500">
                    <span className="font-mono text-[11px] text-slate-400">
                      {node.node_id}
                    </span>
                    <div className="flex items-center gap-2">
                      {node.whatsapp_media?.image_url && (
                        <span title="Contains WhatsApp Image">🖼️</span>
                      )}
                      <span className="rounded bg-slate-200/70 px-1.5 py-0.2 text-[10px]">
                        {node.options.length} opt
                      </span>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* Center Column: Node Editor */}
        <div className="lg:col-span-5 space-y-5 rounded-xl border border-slate-200 bg-slate-50/40 p-4">
          {activeNode ? (
            <>
              {/* Node Header Info */}
              <div className="flex items-center justify-between border-b border-slate-200 pb-3">
                <div className="flex items-center gap-2">
                  <span className="text-xs font-bold text-slate-700">
                    Editing Node:
                  </span>
                  <span className="font-mono text-xs font-semibold text-blue-700">
                    {activeNode.node_id}
                  </span>
                </div>

                <div className="flex items-center gap-2">
                  {activeNode.node_id !== rootNodeId && (
                    <button
                      type="button"
                      onClick={() => setRootNodeId(activeNode.node_id)}
                      className="rounded text-[11px] font-medium text-emerald-700 hover:text-emerald-900 underline"
                    >
                      Make Root
                    </button>
                  )}
                  <button
                    type="button"
                    onClick={() => handleDeleteNode(activeNode.node_id)}
                    className="rounded text-[11px] font-medium text-rose-600 hover:text-rose-800 underline"
                  >
                    Delete Node
                  </button>
                </div>
              </div>

              {/* Node Basic Fields */}
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-semibold text-slate-700 mb-1">
                    Node ID
                  </label>
                  <input
                    type="text"
                    value={activeNode.node_id}
                    onChange={(e) =>
                      handleUpdateActiveNode({ node_id: e.target.value.trim() })
                    }
                    className="w-full rounded-lg border border-slate-300 bg-white px-2.5 py-1.5 font-mono text-xs focus:border-blue-500 focus:outline-none"
                    placeholder="MENU_100"
                  />
                </div>

                <div>
                  <label className="block text-xs font-semibold text-slate-700 mb-1">
                    Menu Serial (e.g. 1.0, 1.1)
                  </label>
                  <input
                    type="text"
                    value={activeNode.menu_number}
                    onChange={(e) =>
                      handleUpdateActiveNode({ menu_number: e.target.value.trim() })
                    }
                    className="w-full rounded-lg border border-slate-300 bg-white px-2.5 py-1.5 text-xs font-mono focus:border-blue-500 focus:outline-none"
                    placeholder="1.0"
                  />
                </div>
              </div>

              <div>
                <label className="block text-xs font-semibold text-slate-700 mb-1">
                  Menu Title / Header
                </label>
                <input
                  type="text"
                  value={activeNode.title}
                  onChange={(e) =>
                    handleUpdateActiveNode({ title: e.target.value })
                  }
                  className="w-full rounded-lg border border-slate-300 bg-white px-2.5 py-1.5 text-xs focus:border-blue-500 focus:outline-none"
                  placeholder="Welcome & Select Program Stream"
                />
              </div>

              {/* WhatsApp Media & Frequency Panel */}
              <div className="rounded-xl border border-emerald-200 bg-emerald-50/40 p-3.5 space-y-3">
                <div className="flex items-center justify-between">
                  <span className="flex items-center gap-1.5 text-xs font-bold text-emerald-900">
                    <span>📱</span> WhatsApp Media Header
                  </span>
                  <div className="flex items-center gap-1.5">
                    <label className="text-[11px] font-medium text-emerald-800">
                      Frequency:
                    </label>
                    <select
                      value={activeNode.frequency || "always"}
                      onChange={(e) =>
                        handleUpdateActiveNode({
                          frequency: e.target.value as "always" | "only_once",
                        })
                      }
                      className="rounded border border-emerald-300 bg-white px-2 py-0.5 text-xs font-medium text-emerald-900 focus:outline-none"
                    >
                      <option value="always">Always Display</option>
                      <option value="only_once">Display Once per Session</option>
                    </select>
                  </div>
                </div>

                <div className="space-y-2">
                  <input
                    type="text"
                    value={activeNode.whatsapp_media?.image_url || ""}
                    onChange={(e) =>
                      handleUpdateActiveNode({
                        whatsapp_media: {
                          ...activeNode.whatsapp_media,
                          image_url: e.target.value.trim(),
                        },
                      })
                    }
                    placeholder="Image URL (e.g. https://cdn.institution.edu/banner.jpg)"
                    className="w-full rounded-lg border border-slate-300 bg-white px-2.5 py-1.5 font-mono text-xs focus:border-emerald-500 focus:outline-none"
                  />
                  <input
                    type="text"
                    value={activeNode.whatsapp_media?.caption || ""}
                    onChange={(e) =>
                      handleUpdateActiveNode({
                        whatsapp_media: {
                          ...activeNode.whatsapp_media,
                          caption: e.target.value,
                        },
                      })
                    }
                    placeholder="Optional image caption"
                    className="w-full rounded-lg border border-slate-300 bg-white px-2.5 py-1.5 text-xs focus:border-emerald-500 focus:outline-none"
                  />
                </div>
              </div>

              {/* Options Section */}
              <div className="space-y-3 pt-2">
                <div className="flex items-center justify-between">
                  <span className="text-xs font-bold uppercase tracking-wider text-slate-600">
                    Selectable Options ({activeNode.options.length})
                  </span>
                  <button
                    type="button"
                    onClick={handleAddOption}
                    className="rounded bg-blue-600 px-2.5 py-1 text-xs font-semibold text-white hover:bg-blue-700 transition"
                  >
                    + Add Option
                  </button>
                </div>

                <div className="space-y-3">
                  {activeNode.options.map((opt, optIdx) => {
                    const isOverButtonLimit = opt.button_text.length > 20;
                    return (
                      <div
                        key={optIdx}
                        className="rounded-xl border border-slate-200 bg-white p-3 space-y-2.5 shadow-2xs"
                      >
                        <div className="flex items-center justify-between">
                          <div className="flex items-center gap-2">
                            <span className="flex h-5 w-5 items-center justify-center rounded-full bg-slate-100 text-[11px] font-bold text-slate-700">
                              {optIdx + 1}
                            </span>
                            <span className="text-xs font-semibold text-slate-800">
                              Option #{opt.option_number || optIdx + 1}
                            </span>
                          </div>
                          <button
                            type="button"
                            onClick={() => handleDeleteOption(optIdx)}
                            className="text-xs text-rose-500 hover:text-rose-700"
                          >
                            ✕ Remove
                          </button>
                        </div>

                        <div className="grid grid-cols-12 gap-2">
                          <div className="col-span-3">
                            <label className="block text-[10px] font-semibold text-slate-500 mb-0.5">
                              Option #
                            </label>
                            <input
                              type="text"
                              value={opt.option_number}
                              onChange={(e) =>
                                handleUpdateOption(optIdx, {
                                  option_number: e.target.value.trim(),
                                })
                              }
                              className="w-full rounded border border-slate-300 px-2 py-1 font-mono text-xs"
                              placeholder="1"
                            />
                          </div>

                          <div className="col-span-9">
                            <div className="flex items-center justify-between mb-0.5">
                              <label className="block text-[10px] font-semibold text-slate-500">
                                Button Label
                              </label>
                              <span
                                className={`text-[10px] font-mono ${
                                  isOverButtonLimit
                                    ? "text-amber-600 font-bold"
                                    : "text-slate-400"
                                }`}
                              >
                                {opt.button_text.length}/20 chars
                              </span>
                            </div>
                            <input
                              type="text"
                              value={opt.button_text}
                              onChange={(e) =>
                                handleUpdateOption(optIdx, {
                                  button_text: e.target.value,
                                })
                              }
                              className="w-full rounded border border-slate-300 px-2 py-1 text-xs"
                              placeholder="e.g. CA / Commerce"
                            />
                          </div>
                        </div>

                        {/* Routing Type & Target */}
                        <div className="grid grid-cols-12 gap-2 border-t border-slate-100 pt-2">
                          <div className="col-span-5">
                            <label className="block text-[10px] font-semibold text-slate-500 mb-0.5">
                              Action Type
                            </label>
                            <select
                              value={opt.target_type}
                              onChange={(e) =>
                                handleUpdateOption(optIdx, {
                                  target_type: e.target.value as
                                    | "NAVIGATE_MENU"
                                    | "TRIGGER_RAG",
                                })
                              }
                              className="w-full rounded border border-slate-300 bg-white px-2 py-1 text-xs font-medium text-slate-800"
                            >
                              <option value="NAVIGATE_MENU">
                                🔀 Navigate Submenu
                              </option>
                              <option value="TRIGGER_RAG">
                                🧠 Trigger RAG Query
                              </option>
                            </select>
                          </div>

                          <div className="col-span-7">
                            {opt.target_type === "NAVIGATE_MENU" ? (
                              <div>
                                <label className="block text-[10px] font-semibold text-slate-500 mb-0.5">
                                  Target Node
                                </label>
                                <select
                                  value={opt.target_id || ""}
                                  onChange={(e) =>
                                    handleUpdateOption(optIdx, {
                                      target_id: e.target.value,
                                    })
                                  }
                                  className="w-full rounded border border-slate-300 bg-white px-2 py-1 text-xs font-mono"
                                >
                                  <option value="">-- Select Child Node --</option>
                                  {nodes
                                    .filter((n) => n.node_id !== activeNode.node_id)
                                    .map((n) => (
                                      <option key={n.node_id} value={n.node_id}>
                                        {n.menu_number} - {n.title} ({n.node_id})
                                      </option>
                                    ))}
                                </select>
                              </div>
                            ) : (
                              <div>
                                <label className="block text-[10px] font-semibold text-slate-500 mb-0.5">
                                  RAG Question / Prompt
                                </label>
                                <input
                                  type="text"
                                  value={opt.rag_prompt || ""}
                                  onChange={(e) =>
                                    handleUpdateOption(optIdx, {
                                      rag_prompt: e.target.value,
                                    })
                                  }
                                  placeholder="e.g., What are the eligibility and fees?"
                                  className="w-full rounded border border-slate-300 px-2 py-1 text-xs"
                                />
                              </div>
                            )}
                          </div>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            </>
          ) : (
            <div className="py-12 text-center text-xs text-slate-400">
              Select or add a node to begin editing.
            </div>
          )}
        </div>

        {/* Right Column: Live Device / Channel Preview */}
        <div className="lg:col-span-3 space-y-3">
          <div className="flex items-center justify-between">
            <span className="text-xs font-bold uppercase tracking-wider text-slate-500">
              Live Preview
            </span>
            <div className="flex rounded-lg bg-slate-100 p-0.5 text-xs font-medium">
              <button
                type="button"
                onClick={() => setPreviewChannel("whatsapp")}
                className={`rounded-md px-2.5 py-1 transition ${
                  previewChannel === "whatsapp"
                    ? "bg-white font-bold text-emerald-800 shadow-2xs"
                    : "text-slate-600 hover:text-slate-900"
                }`}
              >
                WhatsApp
              </button>
              <button
                type="button"
                onClick={() => setPreviewChannel("web")}
                className={`rounded-md px-2.5 py-1 transition ${
                  previewChannel === "web"
                    ? "bg-white font-bold text-blue-800 shadow-2xs"
                    : "text-slate-600 hover:text-slate-900"
                }`}
              >
                Web Widget
              </button>
            </div>
          </div>

          {/* Device Mockup */}
          {previewChannel === "whatsapp" ? (
            <div className="rounded-2xl border-4 border-slate-800 bg-[#E5DDD5] p-3 shadow-md min-h-[460px] flex flex-col justify-end">
              <div className="mb-auto rounded-lg bg-[#075E54] p-2 text-center text-[10px] font-bold text-white shadow">
                WhatsApp Business Gateway
              </div>

              {activeNode ? (
                <div className="space-y-2 mt-4">
                  {/* WhatsApp Image Bubble */}
                  {activeNode.whatsapp_media?.image_url && (
                    <div className="rounded-lg bg-white p-1.5 shadow-xs max-w-[90%] space-y-1">
                      <div className="relative h-28 w-full overflow-hidden rounded bg-slate-100">
                        {/* eslint-disable-next-line @next/next/no-img-element */}
                        <img
                          src={activeNode.whatsapp_media.image_url}
                          alt="Preview"
                          className="h-full w-full object-cover"
                          onError={(e) => {
                            (e.target as HTMLElement).style.display = "none";
                          }}
                        />
                      </div>
                      {activeNode.whatsapp_media.caption && (
                        <p className="text-[11px] text-slate-700 px-1">
                          {activeNode.whatsapp_media.caption}
                        </p>
                      )}
                    </div>
                  )}

                  {/* WhatsApp Menu Text & Interactive Buttons */}
                  <div className="rounded-lg bg-white p-3 shadow-xs max-w-[90%] space-y-2">
                    <p className="text-xs font-medium text-slate-900">
                      {activeNode.title || "Menu Title"}
                    </p>
                    <p className="text-[10px] text-slate-400">
                      Reply with number or tap an option below:
                    </p>
                  </div>

                  {/* Buttons / List format */}
                  <div className="space-y-1.5 max-w-[90%]">
                    {activeNode.options.slice(0, 3).map((opt, i) => (
                      <div
                        key={i}
                        className="rounded-lg bg-white py-2 px-3 text-center text-xs font-semibold text-[#00A884] shadow-xs border border-slate-100 flex items-center justify-between"
                      >
                        <span className="font-mono text-[10px] text-slate-400">
                          {opt.option_number}.
                        </span>
                        <span className="truncate">{opt.button_text}</span>
                        <span className="text-[10px] text-slate-400">
                          {opt.target_type === "NAVIGATE_MENU" ? "›" : "⚡"}
                        </span>
                      </div>
                    ))}
                    {activeNode.options.length > 3 && (
                      <div className="rounded-lg bg-white/80 py-1.5 text-center text-[10px] font-semibold text-slate-600">
                        + {activeNode.options.length - 3} more options (List Picker)
                      </div>
                    )}
                  </div>
                </div>
              ) : (
                <div className="text-center text-xs text-slate-500 py-12">
                  No active node selected.
                </div>
              )}
            </div>
          ) : (
            /* Web Widget Mockup */
            <div className="rounded-2xl border-4 border-slate-800 bg-slate-900 p-3 shadow-md min-h-[460px] flex flex-col justify-end text-white">
              <div className="mb-auto rounded-lg bg-blue-600 p-2 text-center text-[10px] font-bold text-white shadow">
                Web Chat Widget (Clean Text)
              </div>

              {activeNode ? (
                <div className="space-y-3 mt-4">
                  {/* Notice: No media is rendered for Web Channel */}
                  <div className="rounded-xl bg-slate-800 p-3 text-xs space-y-1">
                    <p className="font-medium text-slate-100">
                      {activeNode.title || "Menu Title"}
                    </p>
                    <p className="text-[10px] text-slate-400">
                      Please select an option:
                    </p>
                  </div>

                  <div className="space-y-1.5">
                    {activeNode.options.map((opt, i) => (
                      <button
                        key={i}
                        type="button"
                        className="w-full rounded-lg bg-blue-600/30 border border-blue-500/50 py-2 px-3 text-left text-xs font-medium text-blue-200 hover:bg-blue-600/50 transition flex items-center justify-between"
                      >
                        <span>{opt.button_text}</span>
                        <span className="font-mono text-[10px] text-blue-400">
                          {opt.target_type === "NAVIGATE_MENU" ? "Menu ›" : "RAG"}
                        </span>
                      </button>
                    ))}
                  </div>
                </div>
              ) : (
                <div className="text-center text-xs text-slate-400 py-12">
                  No active node selected.
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
