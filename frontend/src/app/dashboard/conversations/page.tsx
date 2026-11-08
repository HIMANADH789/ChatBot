"use client";

import { useEffect, useState, useCallback, useRef } from "react";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type {
  ClientRecord,
  UserConversationSummary,
  UserChatThread,
  ChatThreadMessage,
} from "@/types";

/* ─── Channel display metadata ──────────────────────────────────────────────── */
const CHANNEL_INFO: Record<string, { label: string; emoji: string; color: string; bg: string; border: string }> = {
  whatsapp: { label: "WhatsApp", emoji: "💬", color: "text-green-700", bg: "bg-green-50", border: "border-green-200" },
  widget:   { label: "Web Widget", emoji: "🌐", color: "text-blue-700", bg: "bg-blue-50", border: "border-blue-200" },
  web_api:  { label: "REST API", emoji: "⚡", color: "text-purple-700", bg: "bg-purple-50", border: "border-purple-200" },
  facebook: { label: "Facebook", emoji: "💙", color: "text-sky-700", bg: "bg-sky-50", border: "border-sky-200" },
  telegram: { label: "Telegram", emoji: "✈️", color: "text-cyan-700", bg: "bg-cyan-50", border: "border-cyan-200" },
  slack:    { label: "Slack", emoji: "🟣", color: "text-violet-700", bg: "bg-violet-50", border: "border-violet-200" },
};

/* ─── Helpers ────────────────────────────────────────────────────────────────── */
function timeAgo(dateStr: string): string {
  try {
    const d = new Date(dateStr);
    const now = new Date();
    const diffMs = now.getTime() - d.getTime();
    const diffMin = Math.floor(diffMs / 60000);
    if (diffMin < 1) return "Just now";
    if (diffMin < 60) return `${diffMin}m ago`;
    const diffHrs = Math.floor(diffMin / 60);
    if (diffHrs < 24) return `${diffHrs}h ago`;
    const diffDays = Math.floor(diffHrs / 24);
    if (diffDays === 1) return "Yesterday";
    if (diffDays < 7) return `${diffDays}d ago`;
    return d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
  } catch { return "—"; }
}

function formatTime(dateStr: string): string {
  try { return new Date(dateStr).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }); }
  catch { return ""; }
}

function formatDateGroup(dateStr: string): string {
  try {
    const d = new Date(dateStr);
    const today = new Date();
    if (d.toDateString() === today.toDateString()) return "Today";
    const yesterday = new Date(); yesterday.setDate(today.getDate() - 1);
    if (d.toDateString() === yesterday.toDateString()) return "Yesterday";
    return d.toLocaleDateString("en-US", { weekday: "long", month: "short", day: "numeric", year: "numeric" });
  } catch { return dateStr; }
}

function getInitials(name: string, senderId: string): string {
  if (name && name !== "Visitor") {
    return name.split(" ").map(w => w[0]).join("").slice(0, 2).toUpperCase();
  }
  return (senderId || "U").charAt(0).toUpperCase();
}

function getAvatarColor(id: string): string {
  const colors = [
    "from-emerald-500 to-teal-600",
    "from-blue-500 to-indigo-600",
    "from-purple-500 to-violet-600",
    "from-orange-500 to-amber-600",
    "from-pink-500 to-rose-600",
    "from-cyan-500 to-sky-600",
    "from-lime-500 to-green-600",
    "from-fuchsia-500 to-purple-600",
  ];
  let hash = 0;
  for (let i = 0; i < id.length; i++) hash = id.charCodeAt(i) + ((hash << 5) - hash);
  return colors[Math.abs(hash) % colors.length];
}

function formatPhoneDisplay(senderId: string): string {
  if (/^\d{10,15}$/.test(senderId)) {
    return `+${senderId}`;
  }
  return senderId;
}

/* ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ */
export default function ConversationsPage() {
  const { role, clientId: userClientId } = useAuth();
  const isSuperAdmin = role === "super_admin";

  /* ── Clients list (super admin dropdown) ─────────────────────────────────── */
  const [clients, setClients] = useState<ClientRecord[]>([]);
  const [selectedClientId, setSelectedClientId] = useState<string>("all");

  /* ── Contact list state ──────────────────────────────────────────────────── */
  const [users, setUsers] = useState<UserConversationSummary[]>([]);
  const [usersTotal, setUsersTotal] = useState(0);
  const [usersPage, setUsersPage] = useState(1);
  const [usersLoading, setUsersLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState("");
  const [channelFilter, setChannelFilter] = useState("all");

  /* ── Active chat thread state ────────────────────────────────────────────── */
  const [activeUser, setActiveUser] = useState<UserConversationSummary | null>(null);
  const [thread, setThread] = useState<UserChatThread | null>(null);
  const [threadLoading, setThreadLoading] = useState(false);
  const chatEndRef = useRef<HTMLDivElement>(null);
  const chatContainerRef = useRef<HTMLDivElement>(null);

  /* ── Mobile: show chat panel ─────────────────────────────────────────────── */
  const [showChat, setShowChat] = useState(false);

  /* ── Load clients for super admin ────────────────────────────────────────── */
  useEffect(() => {
    if (isSuperAdmin) {
      api.listClients().then(res => setClients(res.clients || [])).catch(console.error);
    }
  }, [isSuperAdmin]);

  /* ── Fetch user conversations list ───────────────────────────────────────── */
  const fetchUsers = useCallback(async (silent = false) => {
    if (!silent) setUsersLoading(true);
    try {
      const res = await api.getUserConversations({
        clientId: isSuperAdmin && selectedClientId !== "all" ? selectedClientId : undefined,
        channel: channelFilter !== "all" ? channelFilter : undefined,
        search: searchQuery.trim() || undefined,
        page: usersPage,
        pageSize: 30,
      });
      setUsers(res.users || []);
      setUsersTotal(res.total || 0);
    } catch (err) { console.error("Failed to load conversations:", err); }
    finally { if (!silent) setUsersLoading(false); }
  }, [isSuperAdmin, selectedClientId, channelFilter, searchQuery, usersPage]);

  useEffect(() => { fetchUsers(); }, [fetchUsers]);

  /* ── Auto-refresh contacts every 15s ─────────────────────────────────────── */
  useEffect(() => {
    const t = setInterval(() => fetchUsers(true), 15000);
    return () => clearInterval(t);
  }, [fetchUsers]);

  /* ── Open a user's chat thread ───────────────────────────────────────────── */
  const openThread = async (user: UserConversationSummary) => {
    setActiveUser(user);
    setShowChat(true);
    setThread(null);
    setThreadLoading(true);
    try {
      const res = await api.getUserChatThread(user.sender_id, {
        clientId: isSuperAdmin && selectedClientId !== "all" ? selectedClientId : undefined,
        channel: channelFilter !== "all" ? channelFilter : undefined,
      });
      setThread(res);
      // Scroll to bottom after messages render
      setTimeout(() => chatEndRef.current?.scrollIntoView({ behavior: "instant" }), 80);
    } catch (err) { console.error("Failed to load chat thread:", err); }
    finally { setThreadLoading(false); }
  };

  /* ── Refresh active thread ───────────────────────────────────────────────── */
  const refreshThread = async () => {
    if (!activeUser) return;
    setThreadLoading(true);
    try {
      const res = await api.getUserChatThread(activeUser.sender_id, {
        clientId: isSuperAdmin && selectedClientId !== "all" ? selectedClientId : undefined,
        channel: channelFilter !== "all" ? channelFilter : undefined,
      });
      setThread(res);
      setTimeout(() => chatEndRef.current?.scrollIntoView({ behavior: "smooth" }), 80);
    } catch (err) { console.error("Failed to refresh thread:", err); }
    finally { setThreadLoading(false); }
  };

  /* ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ */
  return (
    <div className="h-[calc(100vh-7rem)] flex rounded-2xl overflow-hidden border border-gray-200 shadow-xl bg-white">

      {/* ═══════════════ LEFT: CONTACT LIST PANEL (WhatsApp Sidebar) ═══════════════ */}
      <div className={`${showChat ? "hidden lg:flex" : "flex"} flex-col w-full lg:w-[380px] lg:min-w-[340px] lg:max-w-[420px] border-r border-gray-200 bg-white`}>

        {/* ── Sidebar Header ──────────────────────────────────────────────────── */}
        <div className="bg-gradient-to-r from-[#075e54] to-[#128c7e] px-4 py-3">
          <div className="flex items-center justify-between mb-3">
            <div className="flex items-center gap-2">
              <div className="h-9 w-9 rounded-full bg-white/20 flex items-center justify-center text-white text-lg">💬</div>
              <div>
                <h1 className="text-white font-bold text-base">Conversations</h1>
                <p className="text-emerald-100/80 text-[11px]">
                  {usersTotal} contact{usersTotal !== 1 ? "s" : ""} • All channels
                </p>
              </div>
            </div>
            <button
              onClick={() => fetchUsers()}
              className="rounded-full p-2 text-white/80 hover:bg-white/10 hover:text-white transition-colors text-sm"
              title="Refresh contacts"
            >
              🔄
            </button>
          </div>

          {/* Search Bar */}
          <div className="relative">
            <span className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400 text-xs">🔍</span>
            <input
              type="text"
              value={searchQuery}
              onChange={e => setSearchQuery(e.target.value)}
              onKeyDown={e => e.key === "Enter" && fetchUsers()}
              placeholder="Search by name, phone, or message..."
              className="w-full rounded-lg bg-white/95 pl-9 pr-3 py-2 text-xs text-gray-800 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-white/40 shadow-sm"
            />
          </div>
        </div>

        {/* ── Filters Row ─────────────────────────────────────────────────────── */}
        <div className="flex items-center gap-1.5 px-3 py-2 border-b border-gray-100 bg-gray-50/80 overflow-x-auto scrollbar-none">
          {isSuperAdmin && (
            <select
              value={selectedClientId}
              onChange={e => { setSelectedClientId(e.target.value); setUsersPage(1); }}
              className="rounded-md border border-gray-200 bg-white px-2 py-1 text-[11px] font-medium text-gray-700 focus:outline-none focus:border-blue-400 min-w-0 max-w-[120px]"
            >
              <option value="all">🏫 All</option>
              {clients.map(c => (
                <option key={c.client_id} value={c.client_id}>{c.name}</option>
              ))}
            </select>
          )}

          {["all", "whatsapp", "widget", "web_api", "telegram"].map(ch => {
            const info = CHANNEL_INFO[ch];
            const isActive = channelFilter === ch;
            return (
              <button
                key={ch}
                onClick={() => { setChannelFilter(ch); setUsersPage(1); }}
                className={`flex items-center gap-1 whitespace-nowrap rounded-full px-2.5 py-1 text-[11px] font-medium transition-all ${
                  isActive
                    ? "bg-[#075e54] text-white shadow-sm"
                    : "bg-white text-gray-600 border border-gray-200 hover:bg-gray-100"
                }`}
              >
                {ch === "all" ? "All" : `${info?.emoji || "💬"} ${info?.label || ch}`}
              </button>
            );
          })}
        </div>

        {/* ── Contact List ────────────────────────────────────────────────────── */}
        <div className="flex-1 overflow-y-auto">
          {usersLoading && users.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-16 text-gray-400">
              <div className="h-8 w-8 animate-spin rounded-full border-2 border-emerald-500 border-t-transparent mb-3" />
              <p className="text-xs font-medium">Loading conversations...</p>
            </div>
          ) : users.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-16 text-gray-400 px-6">
              <span className="text-4xl mb-3">📭</span>
              <p className="text-sm font-semibold text-gray-500">No conversations found</p>
              <p className="text-xs text-gray-400 text-center mt-1">Try adjusting your search or channel filter</p>
            </div>
          ) : (
            <>
              {users.map(user => {
                const ch = CHANNEL_INFO[user.channel] || { label: user.channel, emoji: "💬", color: "text-gray-600", bg: "bg-gray-50", border: "border-gray-200" };
                const isSelected = activeUser?.sender_id === user.sender_id;
                const initials = getInitials(user.sender_name, user.sender_id);
                const avatarGradient = getAvatarColor(user.sender_id);
                const displayName = user.sender_name && user.sender_name !== "Visitor"
                  ? user.sender_name
                  : formatPhoneDisplay(user.sender_id);

                return (
                  <div
                    key={user.sender_id}
                    onClick={() => openThread(user)}
                    className={`flex items-center gap-3 px-4 py-3 cursor-pointer transition-all duration-150 border-b border-gray-50 group ${
                      isSelected
                        ? "bg-[#f0f9f4] border-l-[3px] border-l-emerald-500"
                        : "hover:bg-gray-50/80 border-l-[3px] border-l-transparent"
                    }`}
                  >
                    {/* Avatar */}
                    <div className={`relative h-12 w-12 rounded-full bg-gradient-to-br ${avatarGradient} text-white font-bold flex items-center justify-center text-sm shadow-md flex-shrink-0 group-hover:scale-105 transition-transform`}>
                      {initials}
                      {user.channel === "whatsapp" && (
                        <span className="absolute -bottom-0.5 -right-0.5 h-4 w-4 rounded-full bg-green-500 border-2 border-white flex items-center justify-center text-[8px]">✓</span>
                      )}
                    </div>

                    {/* Contact Info */}
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center justify-between gap-2">
                        <h3 className={`font-semibold text-sm truncate ${isSelected ? "text-emerald-800" : "text-gray-900"}`}>
                          {displayName}
                        </h3>
                        <span className="text-[10px] text-gray-400 whitespace-nowrap flex-shrink-0">
                          {user.last_timestamp ? timeAgo(user.last_timestamp) : "—"}
                        </span>
                      </div>

                      <div className="flex items-center justify-between gap-2 mt-0.5">
                        <p className="text-xs text-gray-500 truncate flex-1">
                          {user.last_message || "(No messages)"}
                        </p>
                        <div className="flex items-center gap-1 flex-shrink-0">
                          {user.has_errors && (
                            <span className="h-2 w-2 rounded-full bg-red-400 flex-shrink-0" title="Has errors" />
                          )}
                          {user.total_messages > 0 && (
                            <span className="inline-flex items-center justify-center h-5 min-w-[20px] rounded-full bg-[#25d366] px-1.5 text-[10px] font-bold text-white">
                              {user.total_messages}
                            </span>
                          )}
                        </div>
                      </div>

                      {/* Channel & Phone Row */}
                      <div className="flex items-center gap-1.5 mt-1">
                        <span className={`inline-flex items-center gap-0.5 rounded px-1 py-0 text-[9px] font-medium ${ch.bg} ${ch.color} border ${ch.border}`}>
                          {ch.emoji} {ch.label}
                        </span>
                        {user.sender_name && user.sender_name !== "Visitor" && /^\d{10,15}$/.test(user.sender_id) && (
                          <span className="text-[9px] text-gray-400 font-mono">+{user.sender_id}</span>
                        )}
                      </div>
                    </div>
                  </div>
                );
              })}

              {/* Pagination */}
              {usersTotal > 30 && (
                <div className="flex items-center justify-between px-4 py-3 border-t border-gray-100 bg-gray-50/60 text-[11px] text-gray-500">
                  <span>Page {usersPage} of {Math.ceil(usersTotal / 30)}</span>
                  <div className="flex gap-1.5">
                    <button
                      disabled={usersPage <= 1}
                      onClick={() => setUsersPage(p => Math.max(1, p - 1))}
                      className="rounded-md border border-gray-200 bg-white px-2.5 py-1 hover:bg-gray-100 disabled:opacity-40 font-medium"
                    >
                      ← Prev
                    </button>
                    <button
                      disabled={usersPage * 30 >= usersTotal}
                      onClick={() => setUsersPage(p => p + 1)}
                      className="rounded-md border border-gray-200 bg-white px-2.5 py-1 hover:bg-gray-100 disabled:opacity-40 font-medium"
                    >
                      Next →
                    </button>
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      </div>

      {/* ═══════════════ RIGHT: CHAT THREAD PANEL ═══════════════════════════════ */}
      <div className={`${!showChat && !activeUser ? "hidden lg:flex" : showChat ? "flex" : "hidden lg:flex"} flex-1 flex-col bg-[#efeae2] min-w-0`}>

        {!activeUser ? (
          /* ── Empty state — no conversation selected ──────────────────────── */
          <div className="flex-1 flex flex-col items-center justify-center text-gray-400 px-8"
            style={{
              backgroundColor: "#f0f2f5",
              backgroundImage: "radial-gradient(#ddd 0.5px, transparent 0.5px)",
              backgroundSize: "16px 16px",
            }}
          >
            <div className="bg-white rounded-3xl p-8 shadow-lg text-center max-w-md border border-gray-100">
              <div className="text-6xl mb-4">💬</div>
              <h2 className="text-xl font-bold text-gray-700 mb-2">Conversations Hub</h2>
              <p className="text-sm text-gray-500 leading-relaxed">
                Select a contact from the sidebar to view their full conversation history. 
                Messages are organized chronologically — just like WhatsApp.
              </p>
              <div className="mt-4 flex items-center justify-center gap-3 text-xs text-gray-400">
                <span className="flex items-center gap-1">🔒 End-to-end logged</span>
                <span>•</span>
                <span className="flex items-center gap-1">📋 Read-only view</span>
              </div>
            </div>
          </div>
        ) : (
          <>
            {/* ── Chat Header ────────────────────────────────────────────────── */}
            <div className="bg-[#075e54] text-white px-4 py-2.5 flex items-center justify-between shadow-md z-10">
              <div className="flex items-center gap-3 min-w-0">
                {/* Back button for mobile */}
                <button
                  onClick={() => { setShowChat(false); }}
                  className="lg:hidden rounded-full p-1.5 hover:bg-white/10 transition-colors text-lg"
                >
                  ←
                </button>

                <div className={`h-10 w-10 rounded-full bg-gradient-to-br ${getAvatarColor(activeUser.sender_id)} text-white font-bold flex items-center justify-center text-sm shadow-md flex-shrink-0`}>
                  {getInitials(activeUser.sender_name, activeUser.sender_id)}
                </div>

                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <h2 className="font-bold text-[15px] text-white truncate">
                      {activeUser.sender_name && activeUser.sender_name !== "Visitor"
                        ? activeUser.sender_name
                        : formatPhoneDisplay(activeUser.sender_id)}
                    </h2>
                    {(() => {
                      const ch = CHANNEL_INFO[activeUser.channel];
                      return ch ? (
                        <span className="inline-flex items-center gap-0.5 rounded bg-white/15 px-1.5 py-0.5 text-[10px] text-white/90 flex-shrink-0">
                          {ch.emoji} {ch.label}
                        </span>
                      ) : null;
                    })()}
                  </div>
                  <p className="text-xs text-emerald-100/80 font-mono truncate">
                    {formatPhoneDisplay(activeUser.sender_id)}
                    {thread?.messages && ` • ${thread.messages.length} messages`}
                    {activeUser.client_id && ` • 🏫 ${activeUser.client_id}`}
                  </p>
                </div>
              </div>

              <div className="flex items-center gap-1 flex-shrink-0">
                <button
                  onClick={refreshThread}
                  disabled={threadLoading}
                  title="Refresh conversation"
                  className="rounded-full p-2 text-white/80 hover:bg-white/10 hover:text-white transition-colors text-sm disabled:opacity-50"
                >
                  {threadLoading ? "⏳" : "🔄"}
                </button>
                <button
                  onClick={() => { navigator.clipboard.writeText(activeUser.sender_id); }}
                  title="Copy phone/ID"
                  className="rounded-full p-2 text-white/80 hover:bg-white/10 hover:text-white transition-colors text-sm"
                >
                  📋
                </button>
                <button
                  onClick={() => { setActiveUser(null); setThread(null); setShowChat(false); }}
                  title="Close conversation"
                  className="rounded-full p-2 text-white/80 hover:bg-white/10 hover:text-white transition-colors font-bold text-base"
                >
                  ✕
                </button>
              </div>
            </div>

            {/* ── Chat Messages Area ─────────────────────────────────────────── */}
            <div
              ref={chatContainerRef}
              className="flex-1 overflow-y-auto px-3 sm:px-6 py-4"
              style={{
                backgroundColor: "#efeae2",
                backgroundImage: "url(\"data:image/svg+xml,%3Csvg width='60' height='60' viewBox='0 0 60 60' xmlns='http://www.w3.org/2000/svg'%3E%3Cg fill='none' fill-rule='evenodd'%3E%3Cg fill='%23d4cdb4' fill-opacity='0.25'%3E%3Cpath d='M36 34v-4h-2v4h-4v2h4v4h2v-4h4v-2h-4zm0-30V0h-2v4h-4v2h4v4h2V6h4V4h-4zM6 34v-4H4v4H0v2h4v4h2v-4h4v-2H6zM6 4V0H4v4H0v2h4v4h2V6h4V4H6z'/%3E%3C/g%3E%3C/g%3E%3C/svg%3E\")",
              }}
            >
              {threadLoading && !thread ? (
                <div className="h-full flex flex-col items-center justify-center text-gray-500">
                  <div className="h-10 w-10 animate-spin rounded-full border-3 border-emerald-500 border-t-transparent mb-3" />
                  <p className="text-sm font-medium">Loading conversation...</p>
                  <p className="text-xs text-gray-400 mt-1">Reconstructing message thread</p>
                </div>
              ) : !thread || thread.messages.length === 0 ? (
                <div className="h-full flex flex-col items-center justify-center text-gray-500">
                  <div className="rounded-2xl bg-white/90 p-5 shadow text-center border border-gray-200/50">
                    <span className="text-3xl block mb-2">📭</span>
                    <p className="text-sm font-semibold text-gray-600">No messages recorded</p>
                    <p className="text-xs text-gray-400 mt-1">This contact has webhook events but no text exchanges yet.</p>
                  </div>
                </div>
              ) : (
                <div className="space-y-1 max-w-3xl mx-auto">
                  {(() => {
                    let lastDate = "";
                    return thread.messages.map((msg: ChatThreadMessage) => {
                      const msgDate = msg.timestamp ? formatDateGroup(msg.timestamp) : "";
                      const showDatePill = msgDate && msgDate !== lastDate;
                      if (showDatePill) lastDate = msgDate;
                      const time = msg.timestamp ? formatTime(msg.timestamp) : "";
                      const isUser = msg.role === "user";
                      const isError = msg.status === "error";

                      return (
                        <div key={msg.id}>
                          {/* Date Separator */}
                          {showDatePill && (
                            <div className="flex justify-center my-4">
                              <span className="rounded-lg bg-white/95 px-4 py-1.5 text-[11px] font-semibold text-gray-500 shadow-sm border border-gray-200/40 uppercase tracking-wider">
                                {msgDate}
                              </span>
                            </div>
                          )}

                          {/* Message Bubble */}
                          <div className={`flex ${isUser ? "justify-start" : "justify-end"} mb-1`}>
                            <div
                              className={`relative max-w-[85%] sm:max-w-[70%] rounded-xl px-3 py-2 shadow-[0_1px_0.5px_rgba(0,0,0,0.13)] ${
                                isUser
                                  ? "bg-white text-gray-900 rounded-tl-sm"
                                  : isError
                                  ? "bg-red-50 text-red-900 rounded-tr-sm border border-red-200/60"
                                  : "bg-[#d9fdd3] text-gray-900 rounded-tr-sm"
                              }`}
                            >
                              {/* Sender label (first message or role change) */}
                              <span className={`text-[10px] font-bold block mb-0.5 ${isUser ? "text-emerald-700" : "text-blue-700"}`}>
                                {isUser
                                  ? (activeUser.sender_name && activeUser.sender_name !== "Visitor" ? activeUser.sender_name : "User")
                                  : "🤖 Bot"
                                }
                              </span>

                              {/* Media attachment */}
                              {msg.media && (
                                <div className="mb-1.5 rounded-lg overflow-hidden border border-gray-200/40 bg-black/5">
                                  {msg.media.type === "image" && msg.media.url ? (
                                    <div>
                                      {/* eslint-disable-next-line @next/next/no-img-element */}
                                      <img
                                        src={msg.media.url}
                                        alt={msg.media.caption || "Attachment"}
                                        className="max-h-52 w-full object-cover"
                                        onError={e => { (e.target as HTMLElement).style.display = "none"; }}
                                      />
                                      {msg.media.caption && (
                                        <p className="p-2 text-[11px] font-medium text-gray-600 bg-white/60">{msg.media.caption}</p>
                                      )}
                                    </div>
                                  ) : (
                                    <a href={msg.media.url} target="_blank" rel="noopener noreferrer"
                                      className="flex items-center gap-2 p-2.5 bg-white/80 hover:bg-white transition-colors"
                                    >
                                      <span className="text-xl">📄</span>
                                      <span className="text-xs font-semibold text-blue-600 truncate">
                                        {msg.media.caption || "View Document"}
                                      </span>
                                    </a>
                                  )}
                                </div>
                              )}

                              {/* Message text */}
                              <div className="text-[13px] leading-relaxed whitespace-pre-wrap break-words select-text">
                                {msg.text}
                              </div>

                              {/* Time + delivery checkmarks */}
                              <div className="flex items-center justify-end gap-1 mt-0.5 -mb-0.5">
                                {!isUser && msg.latency_ms && (
                                  <span className="text-[9px] text-gray-400 font-mono mr-1">{msg.latency_ms}ms</span>
                                )}
                                <span className="text-[10px] text-gray-400">{time}</span>
                                {!isUser && (
                                  <span className="text-[10px] font-bold ml-0.5">
                                    {msg.status === "read" ? (
                                      <span className="text-[#53bdeb]" title="Read">✓✓</span>
                                    ) : msg.status === "delivered" ? (
                                      <span className="text-[#8696a0]" title="Delivered">✓✓</span>
                                    ) : msg.status === "sent" ? (
                                      <span className="text-[#8696a0]" title="Sent">✓</span>
                                    ) : msg.status === "error" ? (
                                      <span className="text-red-500" title={msg.error || "Failed"}>⚠️</span>
                                    ) : (
                                      <span className="text-gray-400">●</span>
                                    )}
                                  </span>
                                )}
                              </div>
                            </div>
                          </div>
                        </div>
                      );
                    });
                  })()}

                  {/* Scroll anchor */}
                  <div ref={chatEndRef} />
                </div>
              )}
            </div>

            {/* ── Chat Footer ────────────────────────────────────────────────── */}
            <div className="bg-[#f0f2f5] px-4 py-2 border-t border-gray-200 flex items-center justify-between">
              <div className="flex items-center gap-1.5 text-gray-400">
                <span className="text-sm">🔒</span>
                <span className="text-[11px]">End-to-end logged conversation • Read-only admin view</span>
              </div>
              <div className="flex items-center gap-2 text-[11px]">
                {thread?.user?.total_events && (
                  <span className="text-gray-400">{thread.user.total_events} events total</span>
                )}
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
