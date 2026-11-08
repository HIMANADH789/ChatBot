"use client";

import { useEffect, useState, useCallback, useRef } from "react";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type {
  WebhookLog,
  ClientRecord,
  UserConversationSummary,
  UserChatThread,
  ChatThreadMessage,
} from "@/types";

const CHANNEL_INFO: Record<string, { label: string; emoji: string; badgeColor: string }> = {
  whatsapp: { label: "WhatsApp", emoji: "💬", badgeColor: "bg-green-100 text-green-800 border-green-200" },
  widget:   { label: "Website Widget", emoji: "🌐", badgeColor: "bg-blue-100 text-blue-800 border-blue-200" },
  web_api:  { label: "REST API", emoji: "⚡", badgeColor: "bg-purple-100 text-purple-800 border-purple-200" },
  facebook: { label: "Facebook", emoji: "💙", badgeColor: "bg-sky-100 text-sky-800 border-sky-200" },
  telegram: { label: "Telegram", emoji: "✈️", badgeColor: "bg-cyan-100 text-cyan-800 border-cyan-200" },
  slack:    { label: "Slack", emoji: "🟣", badgeColor: "bg-violet-100 text-violet-800 border-violet-200" },
};

function getStatusBadge(status: string) {
  if (status === "response_sent" || status === "delivered" || status === "ok") {
    return <span className="inline-flex items-center gap-1 rounded-full bg-emerald-50 px-2 py-0.5 text-xs font-semibold text-emerald-700 border border-emerald-200">● Replied</span>;
  }
  if (status.startsWith("receipt_")) {
    const sub = status.replace("receipt_", "");
    return <span className="inline-flex items-center gap-1 rounded-full bg-gray-100 px-2 py-0.5 text-xs font-medium text-gray-600 border border-gray-200">✓ {sub}</span>;
  }
  if (status === "message_received") {
    return <span className="inline-flex items-center gap-1 rounded-full bg-blue-50 px-2 py-0.5 text-xs font-medium text-blue-700 border border-blue-200">📥 Inbound</span>;
  }
  if (status.includes("error") || status.includes("failed")) {
    return <span className="inline-flex items-center gap-1 rounded-full bg-red-50 px-2 py-0.5 text-xs font-bold text-red-700 border border-red-200">⚠️ Error</span>;
  }
  return <span className="inline-flex items-center gap-1 rounded-full bg-gray-100 px-2 py-0.5 text-xs font-medium text-gray-700 border border-gray-200">{status}</span>;
}

function formatDateGroup(dateStr: string) {
  try {
    const d = new Date(dateStr);
    const today = new Date();
    if (d.toDateString() === today.toDateString()) return "Today";
    const yesterday = new Date();
    yesterday.setDate(today.getDate() - 1);
    if (d.toDateString() === yesterday.toDateString()) return "Yesterday";
    return d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
  } catch {
    return dateStr;
  }
}

export default function RequestLogsPage() {
  const { role, clientId: userClientId } = useAuth();
  const isSuperAdmin = role === "super_admin";

  const [clients, setClients] = useState<ClientRecord[]>([]);
  const [selectedClientId, setSelectedClientId] = useState<string>("all");

  // Stream logs state
  const [logs, setLogs] = useState<WebhookLog[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [selectedLog, setSelectedLog] = useState<WebhookLog | null>(null);
  const [activeTab, setActiveTab] = useState<"overview" | "raw" | "outgoing" | "error">("overview");
  const [copiedKey, setCopiedKey] = useState<string | null>(null);

  // Filters
  const [channelFilter, setChannelFilter] = useState("all");
  const [statusFilter, setStatusFilter] = useState("all"); // 'all' | 'messages' | 'receipts' | 'errors' | 'segregated'
  const [searchQuery, setSearchQuery] = useState("");
  const [autoRefreshInterval, setAutoRefreshInterval] = useState<number>(10); // in seconds (0 = off)

  // Segregated User Conversations State
  const [userConversations, setUserConversations] = useState<UserConversationSummary[]>([]);
  const [userConversationsTotal, setUserConversationsTotal] = useState(0);
  const [userConversationsPage, setUserConversationsPage] = useState(1);
  const [userConversationsLoading, setUserConversationsLoading] = useState(false);

  // Active WhatsApp thread modal state
  const [selectedUser, setSelectedUser] = useState<UserConversationSummary | null>(null);
  const [chatThread, setChatThread] = useState<UserChatThread | null>(null);
  const [chatThreadLoading, setChatThreadLoading] = useState(false);
  const chatScrollRef = useRef<HTMLDivElement>(null);

  const isSegregatedView = statusFilter === "segregated";

  // Load clients list for super admin dropdown
  useEffect(() => {
    if (isSuperAdmin) {
      api.listClients().then((res) => {
        setClients(res.clients || []);
      }).catch(console.error);
    }
  }, [isSuperAdmin]);

  // Fetch stream webhook logs
  const fetchLogs = useCallback(async (isSilent = false) => {
    if (isSegregatedView) return;
    if (!isSilent) setLoading(true);
    try {
      const res = await api.getWebhookLogs({
        clientId: isSuperAdmin && selectedClientId !== "all" ? selectedClientId : undefined,
        page,
        pageSize: 25,
        channel: channelFilter !== "all" ? channelFilter : undefined,
        status: statusFilter !== "all" ? statusFilter : undefined,
        search: searchQuery.trim() || undefined,
      });
      setLogs(res.logs || []);
      setTotal(res.total || 0);
    } catch (err) {
      console.error("Failed to load webhook logs:", err);
    } finally {
      if (!isSilent) setLoading(false);
    }
  }, [page, channelFilter, statusFilter, searchQuery, isSuperAdmin, selectedClientId, isSegregatedView]);

  // Fetch segregated user conversations
  const fetchUserConversations = useCallback(async (isSilent = false) => {
    if (!isSilent) setUserConversationsLoading(true);
    try {
      const res = await api.getUserConversations({
        clientId: isSuperAdmin && selectedClientId !== "all" ? selectedClientId : undefined,
        channel: channelFilter !== "all" ? channelFilter : undefined,
        search: searchQuery.trim() || undefined,
        page: userConversationsPage,
        pageSize: 25,
      });
      setUserConversations(res.users || []);
      setUserConversationsTotal(res.total || 0);
    } catch (err) {
      console.error("Failed to load user conversations:", err);
    } finally {
      if (!isSilent) setUserConversationsLoading(false);
    }
  }, [userConversationsPage, channelFilter, searchQuery, isSuperAdmin, selectedClientId]);

  // Load data based on current view
  useEffect(() => {
    if (isSegregatedView) {
      fetchUserConversations();
    } else {
      fetchLogs();
    }
  }, [isSegregatedView, fetchLogs, fetchUserConversations]);

  // Auto-refresh timer
  useEffect(() => {
    if (autoRefreshInterval <= 0) return;
    const timer = setInterval(() => {
      if (isSegregatedView) {
        fetchUserConversations(true);
      } else {
        fetchLogs(true);
      }
    }, autoRefreshInterval * 1000);
    return () => clearInterval(timer);
  }, [autoRefreshInterval, isSegregatedView, fetchLogs, fetchUserConversations]);

  // Fetch user WhatsApp chat thread
  const openChatThread = async (user: UserConversationSummary) => {
    setSelectedUser(user);
    setChatThread(null);
    setChatThreadLoading(true);
    try {
      const res = await api.getUserChatThread(user.sender_id, {
        clientId: isSuperAdmin && selectedClientId !== "all" ? selectedClientId : undefined,
        channel: channelFilter !== "all" ? channelFilter : undefined,
      });
      setChatThread(res);
      // Auto-scroll chat to bottom after render
      setTimeout(() => {
        if (chatScrollRef.current) {
          chatScrollRef.current.scrollTop = chatScrollRef.current.scrollHeight;
        }
      }, 150);
    } catch (err) {
      console.error("Failed to load user chat thread:", err);
    } finally {
      setChatThreadLoading(false);
    }
  };

  const refreshChatThread = async () => {
    if (!selectedUser) return;
    setChatThreadLoading(true);
    try {
      const res = await api.getUserChatThread(selectedUser.sender_id, {
        clientId: isSuperAdmin && selectedClientId !== "all" ? selectedClientId : undefined,
        channel: channelFilter !== "all" ? channelFilter : undefined,
      });
      setChatThread(res);
      setTimeout(() => {
        if (chatScrollRef.current) {
          chatScrollRef.current.scrollTop = chatScrollRef.current.scrollHeight;
        }
      }, 100);
    } catch (err) {
      console.error("Failed to refresh thread:", err);
    } finally {
      setChatThreadLoading(false);
    }
  };

  const copyToClipboard = (text: string, key: string) => {
    navigator.clipboard.writeText(text);
    setCopiedKey(key);
    setTimeout(() => setCopiedKey(null), 2000);
  };

  return (
    <div className="space-y-6 max-w-7xl mx-auto">
      {/* Page Header */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Request &amp; Webhook Logs</h1>
          <p className="text-sm text-gray-500">
            Real-time inspection of incoming messages, Meta WhatsApp webhooks, responses, and user-wise chat threads.
          </p>
        </div>

        {/* Live Refresh Controls & View Toggle */}
        <div className="flex flex-wrap items-center gap-3">
          <div className="flex items-center gap-2 rounded-lg border border-gray-200 bg-white px-3 py-1.5 shadow-sm text-xs">
            <span className={`h-2 w-2 rounded-full ${autoRefreshInterval > 0 ? "bg-green-500 animate-pulse" : "bg-gray-300"}`} />
            <span className="text-gray-600 font-medium">Auto-refresh:</span>
            <select
              value={autoRefreshInterval}
              onChange={(e) => setAutoRefreshInterval(Number(e.target.value))}
              className="bg-transparent font-semibold text-blue-600 focus:outline-none cursor-pointer"
            >
              <option value={0}>Off</option>
              <option value={5}>Every 5s</option>
              <option value={10}>Every 10s</option>
              <option value={30}>Every 30s</option>
            </select>
          </div>

          <button
            onClick={() => isSegregatedView ? fetchUserConversations() : fetchLogs()}
            className="flex items-center gap-1.5 rounded-lg bg-blue-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-blue-700 shadow-sm transition-colors"
          >
            <span>🔄</span> Refresh
          </button>
        </div>
      </div>

      {/* Filter Bar */}
      <div className="rounded-xl border border-gray-200 bg-white p-4 shadow-sm space-y-3">
        <div className="flex flex-wrap items-center gap-3">
          {/* Institution Selector for Super Admin */}
          {isSuperAdmin ? (
            <div className="flex items-center gap-2">
              <span className="text-xs font-medium text-gray-500">Institution:</span>
              <select
                value={selectedClientId}
                onChange={(e) => { setSelectedClientId(e.target.value); setPage(1); setUserConversationsPage(1); }}
                className="rounded-lg border border-blue-200 bg-blue-50/50 px-3 py-1.5 text-xs font-semibold text-blue-800 focus:border-blue-500 focus:outline-none"
              >
                <option value="all">🏫 All Institutions</option>
                {clients.map((c) => (
                  <option key={c.client_id} value={c.client_id}>
                    {c.name} ({c.client_id})
                  </option>
                ))}
              </select>
            </div>
          ) : userClientId ? (
            <div className="inline-flex items-center gap-1.5 rounded-lg bg-gray-50 border border-gray-200 px-3 py-1.5 text-xs font-medium text-gray-700">
              <span>🏫 Institution:</span>
              <span className="font-bold text-blue-700">{userClientId}</span>
            </div>
          ) : null}

          {/* View Mode Toggle: Log Stream vs Segregated Users */}
          <div className="flex items-center gap-1 rounded-lg border border-gray-200 p-1 bg-gray-50 text-xs font-medium">
            <button
              onClick={() => { setStatusFilter("all"); setPage(1); }}
              className={`flex items-center gap-1.5 rounded-md px-3 py-1 transition-colors ${!isSegregatedView ? "bg-white text-blue-700 shadow-sm font-semibold" : "text-gray-600 hover:text-gray-900"}`}
            >
              <span>📋</span>
              <span>All Logs Stream</span>
            </button>
            <button
              onClick={() => { setStatusFilter("segregated"); setUserConversationsPage(1); }}
              className={`flex items-center gap-1.5 rounded-md px-3 py-1 transition-colors ${isSegregatedView ? "bg-emerald-600 text-white shadow-sm font-semibold" : "text-gray-600 hover:text-gray-900"}`}
            >
              <span>💬</span>
              <span>Segregated by User</span>
            </button>
          </div>

          {/* Channel Selector */}
          <div className="flex items-center gap-1 rounded-lg border border-gray-200 p-1 bg-gray-50 text-xs font-medium">
            <button
              onClick={() => { setChannelFilter("all"); setPage(1); setUserConversationsPage(1); }}
              className={`rounded-md px-2.5 py-1 transition-colors ${channelFilter === "all" ? "bg-white text-blue-600 shadow-sm font-semibold" : "text-gray-600 hover:text-gray-900"}`}
            >
              All Channels
            </button>
            <button
              onClick={() => { setChannelFilter("whatsapp"); setPage(1); setUserConversationsPage(1); }}
              className={`rounded-md px-2.5 py-1 transition-colors ${channelFilter === "whatsapp" ? "bg-white text-green-700 shadow-sm font-semibold" : "text-gray-600 hover:text-gray-900"}`}
            >
              💬 WhatsApp
            </button>
            <button
              onClick={() => { setChannelFilter("widget"); setPage(1); setUserConversationsPage(1); }}
              className={`rounded-md px-2.5 py-1 transition-colors ${channelFilter === "widget" ? "bg-white text-blue-700 shadow-sm font-semibold" : "text-gray-600 hover:text-gray-900"}`}
            >
              🌐 Widget
            </button>
            <button
              onClick={() => { setChannelFilter("web_api"); setPage(1); setUserConversationsPage(1); }}
              className={`rounded-md px-2.5 py-1 transition-colors ${channelFilter === "web_api" ? "bg-white text-purple-700 shadow-sm font-semibold" : "text-gray-600 hover:text-gray-900"}`}
            >
              ⚡ Web API
            </button>
          </div>

          {/* Filter Dropdown (Including Segregated by User Option) */}
          <select
            value={statusFilter}
            onChange={(e) => {
              setStatusFilter(e.target.value);
              setPage(1);
              setUserConversationsPage(1);
            }}
            className="rounded-lg border border-gray-200 bg-white px-3 py-1.5 text-xs text-gray-700 focus:border-blue-500 focus:outline-none font-medium"
          >
            <option value="all">All Events</option>
            <option value="messages">💬 User Messages &amp; Replies</option>
            <option value="receipts">📬 Delivery Receipts</option>
            <option value="errors">⚠️ Errors &amp; Failures</option>
            <option value="segregated">👥 Segregated by User (Conversations)</option>
          </select>

          {/* Search Input */}
          <div className="flex-1 min-w-[200px]">
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && (isSegregatedView ? fetchUserConversations() : fetchLogs())}
              placeholder={isSegregatedView ? "Search user phone, name, or message snippet..." : "Search by phone, name, query, or error..."}
              className="w-full rounded-lg border border-gray-200 px-3 py-1.5 text-xs focus:border-blue-500 focus:outline-none"
            />
          </div>

          <button
            onClick={() => isSegregatedView ? fetchUserConversations() : fetchLogs()}
            className="rounded-lg bg-gray-100 hover:bg-gray-200 px-3 py-1.5 text-xs font-medium text-gray-700 transition-colors"
          >
            Search
          </button>
        </div>
      </div>

      {/* VIEW 1: SEGREGATED BY USER VIEW */}
      {isSegregatedView ? (
        <div className="space-y-4">
          <div className="flex items-center justify-between text-xs text-gray-500 px-1">
            <span>
              Showing <strong className="text-gray-800">{userConversations.length}</strong> unique users ({userConversationsTotal} total contacts logged)
            </span>
            <span className="text-[11px] text-emerald-700 font-medium bg-emerald-50 border border-emerald-200 rounded-md px-2 py-0.5">
              💡 Click any user to open their WhatsApp-style conversation thread
            </span>
          </div>

          <div className="rounded-xl border border-gray-200 bg-white shadow-sm overflow-hidden">
            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-gray-200 text-left text-xs">
                <thead className="bg-gray-50 text-gray-500 font-semibold uppercase tracking-wider">
                  <tr>
                    <th className="px-4 py-3">User Contact / Phone</th>
                    <th className="px-4 py-3">Channel &amp; Institution</th>
                    <th className="px-4 py-3">Activity &amp; Messages</th>
                    <th className="px-4 py-3">Latest Message Snippet</th>
                    <th className="px-4 py-3">Last Active</th>
                    <th className="px-4 py-3 text-center">Action</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100 text-gray-700">
                  {userConversationsLoading && userConversations.length === 0 ? (
                    <tr>
                      <td colSpan={6} className="px-4 py-12 text-center text-gray-400">
                        <div className="inline-block h-6 w-6 animate-spin rounded-full border-2 border-emerald-600 border-t-transparent" />
                        <p className="mt-2 text-xs">Loading segregated user conversations...</p>
                      </td>
                    </tr>
                  ) : userConversations.length === 0 ? (
                    <tr>
                      <td colSpan={6} className="px-4 py-12 text-center text-gray-400">
                        No user conversations found matching your search.
                      </td>
                    </tr>
                  ) : (
                    userConversations.map((user) => {
                      const channel = CHANNEL_INFO[user.channel] || { label: user.channel, emoji: "💬", badgeColor: "bg-gray-100 text-gray-700 border-gray-200" };
                      const lastTimeFormatted = user.last_timestamp ? formatDateGroup(user.last_timestamp) + " " + new Date(user.last_timestamp).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "—";
                      const initial = (user.sender_name || user.sender_id || "U").charAt(0).toUpperCase();

                      return (
                        <tr
                          key={user.sender_id}
                          onClick={() => openChatThread(user)}
                          className="hover:bg-emerald-50/50 cursor-pointer transition-colors group"
                        >
                          {/* User Contact */}
                          <td className="px-4 py-3 whitespace-nowrap">
                            <div className="flex items-center gap-3">
                              <div className="h-9 w-9 rounded-full bg-emerald-600 text-white font-bold flex items-center justify-center text-sm shadow-sm group-hover:scale-105 transition-transform">
                                {initial}
                              </div>
                              <div>
                                <p className="font-bold text-gray-900 group-hover:text-emerald-700 transition-colors">
                                  {user.sender_name && user.sender_name !== "Visitor" ? user.sender_name : (user.sender_id.startsWith("91") ? `+${user.sender_id}` : user.sender_id)}
                                </p>
                                <p className="text-[11px] text-gray-400 font-mono">
                                  {user.sender_id.startsWith("91") ? `+${user.sender_id}` : user.sender_id}
                                </p>
                              </div>
                            </div>
                          </td>

                          {/* Channel & Institution */}
                          <td className="px-4 py-3 whitespace-nowrap">
                            <div className="flex flex-col gap-1 items-start">
                              <span className={`inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[11px] font-medium border ${channel.badgeColor}`}>
                                <span>{channel.emoji}</span>
                                <span>{channel.label}</span>
                              </span>
                              {user.client_id && (
                                <span className="text-[10px] text-gray-500 font-medium">
                                  🏫 {user.client_id}
                                </span>
                              )}
                            </div>
                          </td>

                          {/* Messages & Status */}
                          <td className="px-4 py-3 whitespace-nowrap">
                            <div className="flex items-center gap-2">
                              <span className="inline-flex items-center rounded-full bg-blue-50 px-2 py-0.5 text-xs font-semibold text-blue-700 border border-blue-200">
                                💬 {user.total_messages} messages
                              </span>
                              {user.has_errors ? (
                                <span className="inline-flex items-center rounded-full bg-red-50 px-1.5 py-0.5 text-[10px] font-bold text-red-600 border border-red-200">
                                  ⚠️ Error
                                </span>
                              ) : (
                                <span className="inline-flex items-center rounded-full bg-emerald-50 px-1.5 py-0.5 text-[10px] font-medium text-emerald-700 border border-emerald-200">
                                  ✓ Active
                                </span>
                              )}
                            </div>
                            <p className="mt-0.5 text-[10px] text-gray-400">Total events: {user.total_events}</p>
                          </td>

                          {/* Latest Snippet */}
                          <td className="px-4 py-3 max-w-[260px] truncate">
                            <span className="font-medium text-gray-700 text-xs">
                              {user.last_message}
                            </span>
                          </td>

                          {/* Last Active */}
                          <td className="px-4 py-3 whitespace-nowrap text-gray-500 text-xs font-medium">
                            {lastTimeFormatted}
                          </td>

                          {/* Action Button */}
                          <td className="px-4 py-3 whitespace-nowrap text-center">
                            <button
                              onClick={(e) => { e.stopPropagation(); openChatThread(user); }}
                              className="inline-flex items-center gap-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-700 text-white px-3 py-1.5 text-xs font-semibold shadow-sm transition-all group-hover:shadow"
                            >
                              <span>💬</span>
                              <span>Open Chat</span>
                            </button>
                          </td>
                        </tr>
                      );
                    })
                  )}
                </tbody>
              </table>
            </div>

            {/* Pagination for User Conversations */}
            {userConversationsTotal > 25 && (
              <div className="flex items-center justify-between border-t border-gray-200 px-4 py-3 bg-gray-50 text-xs text-gray-600">
                <span>
                  Page {userConversationsPage} of {Math.ceil(userConversationsTotal / 25)} ({userConversationsTotal} total users)
                </span>
                <div className="flex items-center gap-2">
                  <button
                    disabled={userConversationsPage <= 1}
                    onClick={() => setUserConversationsPage((p) => Math.max(1, p - 1))}
                    className="rounded-md border border-gray-200 bg-white px-2.5 py-1 hover:bg-gray-100 disabled:opacity-40"
                  >
                    Previous
                  </button>
                  <button
                    disabled={userConversationsPage * 25 >= userConversationsTotal}
                    onClick={() => setUserConversationsPage((p) => p + 1)}
                    className="rounded-md border border-gray-200 bg-white px-2.5 py-1 hover:bg-gray-100 disabled:opacity-40"
                  >
                    Next
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
      ) : (
        /* VIEW 2: STREAM LOGS TABLE */
        <div className="rounded-xl border border-gray-200 bg-white shadow-sm overflow-hidden">
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200 text-left text-xs">
              <thead className="bg-gray-50 text-gray-500 font-semibold uppercase tracking-wider">
                <tr>
                  <th className="px-4 py-3">Time &amp; Channel</th>
                  <th className="px-4 py-3">Sender / Contact</th>
                  <th className="px-4 py-3">Status</th>
                  <th className="px-4 py-3">User Query</th>
                  <th className="px-4 py-3">Assistant Response</th>
                  <th className="px-4 py-3 text-right">Latency</th>
                  <th className="px-4 py-3 text-center">Inspect</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100 text-gray-700">
                {loading && logs.length === 0 ? (
                  <tr>
                    <td colSpan={7} className="px-4 py-12 text-center text-gray-400">
                      <div className="inline-block h-6 w-6 animate-spin rounded-full border-2 border-blue-600 border-t-transparent" />
                      <p className="mt-2 text-xs">Loading logs...</p>
                    </td>
                  </tr>
                ) : logs.length === 0 ? (
                  <tr>
                    <td colSpan={7} className="px-4 py-12 text-center text-gray-400">
                      No logs found matching the selected filters.
                    </td>
                  </tr>
                ) : (
                  logs.map((log) => {
                    const channel = CHANNEL_INFO[log.channel] || { label: log.channel, emoji: "💬", badgeColor: "bg-gray-100 text-gray-700 border-gray-200" };
                    const timeFormatted = log.timestamp ? new Date(log.timestamp).toLocaleTimeString() : "—";
                    const dateFormatted = log.timestamp ? new Date(log.timestamp).toLocaleDateString() : "";

                    return (
                      <tr
                        key={log.id}
                        onClick={() => { setSelectedLog(log); setActiveTab("overview"); }}
                        className="hover:bg-blue-50/50 cursor-pointer transition-colors"
                      >
                        {/* Time & Channel */}
                        <td className="px-4 py-3 whitespace-nowrap">
                          <div className="flex items-center gap-2">
                            <span className={`inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[11px] font-medium border ${channel.badgeColor}`}>
                              <span>{channel.emoji}</span>
                              <span>{channel.label}</span>
                            </span>
                          </div>
                          <p className="mt-0.5 text-[10px] text-gray-400">{dateFormatted} {timeFormatted}</p>
                        </td>

                        {/* Sender */}
                        <td className="px-4 py-3 whitespace-nowrap">
                          <p className="font-semibold text-gray-900">{log.sender_name || log.sender_id || "Anonymous"}</p>
                          {log.sender_name && log.sender_id && (
                            <p className="text-[10px] text-gray-400 font-mono">{log.sender_id}</p>
                          )}
                        </td>

                        {/* Status */}
                        <td className="px-4 py-3 whitespace-nowrap">
                          {getStatusBadge(log.status)}
                        </td>

                        {/* User Query */}
                        <td className="px-4 py-3 max-w-[200px] truncate">
                          {log.message_in ? (
                            <span className="font-medium text-gray-800">{log.message_in}</span>
                          ) : (
                            <span className="italic text-gray-400">(webhook event)</span>
                          )}
                        </td>

                        {/* Assistant Response */}
                        <td className="px-4 py-3 max-w-[260px] truncate">
                          {log.response_out ? (
                            <span className="text-gray-700">{log.response_out}</span>
                          ) : log.error ? (
                            <span className="text-red-600 font-medium">⚠️ {log.error}</span>
                          ) : (
                            <span className="text-gray-400 italic">—</span>
                          )}
                        </td>

                        {/* Latency */}
                        <td className="px-4 py-3 whitespace-nowrap text-right font-mono text-gray-500">
                          {log.response_time_ms ? `${log.response_time_ms}ms` : "—"}
                        </td>

                        {/* Inspect Action */}
                        <td className="px-4 py-3 whitespace-nowrap text-center">
                          <button
                            onClick={(e) => { e.stopPropagation(); setSelectedLog(log); setActiveTab("overview"); }}
                            className="rounded-md bg-gray-100 hover:bg-blue-50 hover:text-blue-600 px-2 py-1 text-[11px] font-medium text-gray-600 transition-colors"
                          >
                            🔍 Inspect
                          </button>
                        </td>
                      </tr>
                    );
                  })
                )}
              </tbody>
            </table>
          </div>

          {/* Pagination for Stream Logs */}
          <div className="flex items-center justify-between border-t border-gray-200 px-4 py-3 bg-gray-50 text-xs text-gray-600">
            <span>
              Page {page} of {Math.ceil(total / 25) || 1} ({total} total logs)
            </span>
            <div className="flex items-center gap-2">
              <button
                disabled={page <= 1}
                onClick={() => setPage((p) => Math.max(1, p - 1))}
                className="rounded-md border border-gray-200 bg-white px-2.5 py-1 hover:bg-gray-100 disabled:opacity-40"
              >
                Previous
              </button>
              <button
                disabled={page * 25 >= total}
                onClick={() => setPage((p) => p + 1)}
                className="rounded-md border border-gray-200 bg-white px-2.5 py-1 hover:bg-gray-100 disabled:opacity-40"
              >
                Next
              </button>
            </div>
          </div>
        </div>
      )}

      {/* WHATSAPP CONVERSATION MODAL (INTERACTIVE USER-WISE CHAT INTERFACE) */}
      {selectedUser && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-2 sm:p-4 animate-in fade-in duration-200">
          <div className="w-full max-w-2xl h-[92vh] max-h-[780px] flex flex-col rounded-2xl shadow-2xl overflow-hidden border border-emerald-900/20 bg-[#efeae2]">
            {/* Authentic WhatsApp Green Header */}
            <div className="bg-[#075e54] text-white px-4 py-3 flex items-center justify-between shadow-md">
              <div className="flex items-center gap-3">
                <div className="h-10 w-10 rounded-full bg-[#128c7e] text-white font-bold flex items-center justify-center text-sm shadow">
                  {(selectedUser.sender_name || selectedUser.sender_id || "U").charAt(0).toUpperCase()}
                </div>
                <div>
                  <div className="flex items-center gap-2">
                    <h2 className="font-bold text-base text-white">
                      {selectedUser.sender_name && selectedUser.sender_name !== "Visitor" ? selectedUser.sender_name : (selectedUser.sender_id.startsWith("91") ? `+${selectedUser.sender_id}` : selectedUser.sender_id)}
                    </h2>
                    <span className="inline-flex items-center gap-1 rounded bg-emerald-800/80 px-1.5 py-0.5 text-[10px] text-emerald-100">
                      💬 WhatsApp
                    </span>
                  </div>
                  <p className="text-xs text-emerald-100/90 font-mono">
                    {selectedUser.sender_id.startsWith("91") ? `+${selectedUser.sender_id}` : selectedUser.sender_id}
                    {chatThread?.messages && ` • ${chatThread.messages.length} messages logged`}
                  </p>
                </div>
              </div>

              {/* Action Buttons */}
              <div className="flex items-center gap-2">
                <button
                  onClick={refreshChatThread}
                  title="Refresh conversation"
                  className="rounded-full p-2 text-emerald-100 hover:bg-white/10 transition-colors"
                >
                  🔄
                </button>
                <button
                  onClick={() => copyToClipboard(selectedUser.sender_id, "phone")}
                  title="Copy phone number"
                  className="rounded-full p-2 text-emerald-100 hover:bg-white/10 transition-colors text-xs"
                >
                  {copiedKey === "phone" ? "✓" : "📋"}
                </button>
                <button
                  onClick={() => setSelectedUser(null)}
                  title="Close chat"
                  className="rounded-full p-2 text-emerald-100 hover:bg-white/20 transition-colors font-bold text-base"
                >
                  ✕
                </button>
              </div>
            </div>

            {/* Scrollable WhatsApp Chat Window Canvas */}
            <div
              ref={chatScrollRef}
              className="flex-1 overflow-y-auto p-4 space-y-3 relative"
              style={{
                backgroundColor: "#efeae2",
                backgroundImage: "radial-gradient(#d4cdb4 0.75px, transparent 0.75px)",
                backgroundSize: "20px 20px",
              }}
            >
              {chatThreadLoading && !chatThread ? (
                <div className="h-full flex flex-col items-center justify-center text-gray-500 py-12">
                  <div className="h-8 w-8 animate-spin rounded-full border-3 border-emerald-600 border-t-transparent" />
                  <p className="mt-3 text-xs font-medium">Reconstructing WhatsApp thread...</p>
                </div>
              ) : !chatThread || chatThread.messages.length === 0 ? (
                <div className="h-full flex flex-col items-center justify-center text-gray-500 py-12">
                  <div className="rounded-full bg-white p-3 shadow-sm text-2xl mb-2">💬</div>
                  <p className="text-sm font-semibold text-gray-700">No chat turns recorded yet</p>
                  <p className="text-xs text-gray-500 mt-1">This user has incoming webhook events but no text exchanges.</p>
                </div>
              ) : (
                (() => {
                  let lastDate = "";
                  return chatThread.messages.map((msg: ChatThreadMessage) => {
                    const msgDate = msg.timestamp ? formatDateGroup(msg.timestamp) : "";
                    const showDatePill = msgDate && msgDate !== lastDate;
                    if (showDatePill) lastDate = msgDate;

                    const timeFormatted = msg.timestamp
                      ? new Date(msg.timestamp).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
                      : "";

                    const isUser = msg.role === "user";

                    return (
                      <div key={msg.id} className="space-y-3">
                        {/* Date Divider Pill */}
                        {showDatePill && (
                          <div className="flex justify-center my-3">
                            <span className="rounded-lg bg-white/90 px-3 py-1 text-[11px] font-semibold text-gray-600 shadow-sm border border-gray-200/60 uppercase tracking-wider">
                              {msgDate}
                            </span>
                          </div>
                        )}

                        {/* Chat Speech Bubble */}
                        <div className={`flex ${isUser ? "justify-start" : "justify-end"}`}>
                          <div
                            className={`relative max-w-[85%] sm:max-w-[75%] rounded-2xl p-3 shadow-[0_1px_0.5px_rgba(0,0,0,0.13)] ${
                              isUser
                                ? "bg-white text-gray-900 rounded-tl-none border border-gray-200/50"
                                : msg.status === "error"
                                ? "bg-red-50 text-red-900 rounded-tr-none border border-red-200"
                                : "bg-[#d9fdd3] text-gray-900 rounded-tr-none border border-[#c4f3be]"
                            }`}
                          >
                            {/* Role / Sender Tag */}
                            <div className="flex items-center justify-between gap-2 mb-1">
                              <span className={`text-[10px] font-bold ${isUser ? "text-emerald-700" : "text-blue-700"}`}>
                                {isUser ? (selectedUser.sender_name || "Visitor / User") : "SV Professionals (Bot)"}
                              </span>
                              {msg.latency_ms && !isUser && (
                                <span className="text-[9px] text-gray-400 font-mono">
                                  {msg.latency_ms}ms
                                </span>
                              )}
                            </div>

                            {/* Media Attachment if Present */}
                            {msg.media && (
                              <div className="mb-2 rounded-lg overflow-hidden border border-gray-200/60 bg-black/5">
                                {msg.media.type === "image" && msg.media.url ? (
                                  <div>
                                    {/* eslint-disable-next-line @next/next/no-img-element */}
                                    <img
                                      src={msg.media.url}
                                      alt={msg.media.caption || "Attached brochure"}
                                      className="max-h-48 w-full object-cover rounded-t-lg"
                                      onError={(e) => {
                                        (e.target as HTMLElement).style.display = "none";
                                      }}
                                    />
                                    {msg.media.caption && (
                                      <p className="p-2 text-xs font-medium text-gray-700 bg-white/60">
                                        {msg.media.caption}
                                      </p>
                                    )}
                                  </div>
                                ) : (
                                  <div className="p-2.5 flex items-center gap-2 bg-white/80">
                                    <span className="text-xl">📄</span>
                                    <div className="flex-1 truncate">
                                      <a
                                        href={msg.media.url}
                                        target="_blank"
                                        rel="noopener noreferrer"
                                        className="text-xs font-semibold text-blue-600 hover:underline truncate block"
                                      >
                                        {msg.media.caption || "View Attached Document"}
                                      </a>
                                    </div>
                                  </div>
                                )}
                              </div>
                            )}

                            {/* Message Text Body */}
                            <div className="text-xs leading-relaxed whitespace-pre-wrap break-words select-text">
                              {msg.text}
                            </div>

                            {/* Time & WhatsApp Delivery Checkmarks */}
                            <div className="flex items-center justify-end gap-1 mt-1 text-[10px] text-gray-400 select-none">
                              <span>{timeFormatted}</span>
                              {!isUser && (
                                <span className="font-bold">
                                  {msg.status === "read" ? (
                                    <span className="text-[#53bdeb] tracking-tighter" title="Read by user">✓✓</span>
                                  ) : msg.status === "delivered" ? (
                                    <span className="text-[#8696a0] tracking-tighter" title="Delivered to device">✓✓</span>
                                  ) : msg.status === "sent" ? (
                                    <span className="text-[#8696a0]" title="Sent">✓</span>
                                  ) : msg.status === "error" ? (
                                    <span className="text-red-600" title={msg.error || "Delivery failed"}>⚠️</span>
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
                })()
              )}
            </div>

            {/* Authentic WhatsApp Footer Status */}
            <div className="bg-[#f0f2f5] px-4 py-2.5 border-t border-gray-200 flex items-center justify-between text-xs text-gray-500">
              <div className="flex items-center gap-1.5">
                <span>🔒</span>
                <span className="text-[11px]">
                  End-to-end conversation logged via Meta Cloud API. Read-only view.
                </span>
              </div>
              <button
                onClick={() => setSelectedUser(null)}
                className="rounded-lg bg-gray-200 hover:bg-gray-300 px-3 py-1 text-xs font-semibold text-gray-700 transition-colors"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}

      {/* STREAM LOG INSPECTOR MODAL (EXISTING RAW JSON INSPECTOR) */}
      {selectedLog && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
          <div className="w-full max-w-4xl max-h-[90vh] rounded-2xl bg-white shadow-2xl flex flex-col overflow-hidden border border-gray-200">
            {/* Modal Header */}
            <div className="flex items-center justify-between border-b border-gray-200 px-6 py-4 bg-gray-50">
              <div className="flex items-center gap-3">
                <span className="text-xl">
                  {CHANNEL_INFO[selectedLog.channel]?.emoji || "📋"}
                </span>
                <div>
                  <div className="flex items-center gap-2">
                    <h2 className="text-base font-bold text-gray-900">
                      Log Details: {selectedLog.sender_name || selectedLog.sender_id || selectedLog.channel}
                    </h2>
                    {getStatusBadge(selectedLog.status)}
                  </div>
                  <p className="text-xs text-gray-400 font-mono">
                    ID: {selectedLog.id} • {selectedLog.timestamp ? new Date(selectedLog.timestamp).toLocaleString() : ""}
                  </p>
                </div>
              </div>

              <button
                onClick={() => setSelectedLog(null)}
                className="rounded-lg p-1.5 text-gray-400 hover:bg-gray-200 hover:text-gray-700 transition-colors"
              >
                ✕
              </button>
            </div>

            {/* Modal Tabs */}
            <div className="flex items-center gap-4 border-b border-gray-200 px-6 text-xs font-semibold">
              <button
                onClick={() => setActiveTab("overview")}
                className={`py-3 border-b-2 transition-colors ${activeTab === "overview" ? "border-blue-600 text-blue-600" : "border-transparent text-gray-500 hover:text-gray-800"}`}
              >
                Overview &amp; Messages
              </button>
              <button
                onClick={() => setActiveTab("raw")}
                className={`py-3 border-b-2 transition-colors ${activeTab === "raw" ? "border-blue-600 text-blue-600" : "border-transparent text-gray-500 hover:text-gray-800"}`}
              >
                Incoming Payload (JSON)
              </button>
              <button
                onClick={() => setActiveTab("outgoing")}
                className={`py-3 border-b-2 transition-colors ${activeTab === "outgoing" ? "border-blue-600 text-blue-600" : "border-transparent text-gray-500 hover:text-gray-800"}`}
              >
                Outgoing Payload (JSON)
              </button>
              {selectedLog.error && (
                <button
                  onClick={() => setActiveTab("error")}
                  className={`py-3 border-b-2 transition-colors ${activeTab === "error" ? "border-red-600 text-red-600" : "border-transparent text-red-500 hover:text-red-700"}`}
                >
                  ⚠️ Error &amp; Traceback
                </button>
              )}
            </div>

            {/* Modal Body */}
            <div className="flex-1 overflow-y-auto p-6 space-y-4">
              {/* Tab 1: Overview */}
              {activeTab === "overview" && (
                <div className="space-y-4 text-xs">
                  <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                    <div className="rounded-xl border border-gray-100 bg-gray-50 p-3">
                      <p className="text-gray-400 font-medium">Channel</p>
                      <p className="font-bold text-gray-900 mt-0.5">{selectedLog.channel}</p>
                    </div>
                    <div className="rounded-xl border border-gray-100 bg-gray-50 p-3">
                      <p className="text-gray-400 font-medium">Institution</p>
                      <p className="font-bold text-gray-900 mt-0.5">{selectedLog.client_id}</p>
                    </div>
                    <div className="rounded-xl border border-gray-100 bg-gray-50 p-3">
                      <p className="text-gray-400 font-medium">Sender ID</p>
                      <p className="font-bold text-gray-900 mt-0.5 font-mono">{selectedLog.sender_id || "—"}</p>
                    </div>
                    <div className="rounded-xl border border-gray-100 bg-gray-50 p-3">
                      <p className="text-gray-400 font-medium">Latency</p>
                      <p className="font-bold text-gray-900 mt-0.5 font-mono">{selectedLog.response_time_ms ? `${selectedLog.response_time_ms}ms` : "—"}</p>
                    </div>
                  </div>

                  {/* Message In */}
                  <div>
                    <div className="flex items-center justify-between mb-1">
                      <p className="text-xs font-bold text-gray-700">User Inbound Message:</p>
                      {selectedLog.message_in && (
                        <button
                          onClick={() => copyToClipboard(selectedLog.message_in!, "in")}
                          className="text-[11px] text-blue-600 hover:underline"
                        >
                          {copiedKey === "in" ? "✓ Copied" : "Copy"}
                        </button>
                      )}
                    </div>
                    <div className="rounded-xl border border-blue-100 bg-blue-50/50 p-3.5 text-gray-800 font-medium">
                      {selectedLog.message_in || <span className="italic text-gray-400">No message text recorded</span>}
                    </div>
                  </div>

                  {/* Response Out */}
                  <div>
                    <div className="flex items-center justify-between mb-1">
                      <p className="text-xs font-bold text-gray-700">Bot Outgoing Response:</p>
                      {selectedLog.response_out && (
                        <button
                          onClick={() => copyToClipboard(selectedLog.response_out!, "out")}
                          className="text-[11px] text-blue-600 hover:underline"
                        >
                          {copiedKey === "out" ? "✓ Copied" : "Copy"}
                        </button>
                      )}
                    </div>
                    <div className="rounded-xl border border-emerald-100 bg-emerald-50/50 p-3.5 text-gray-800 whitespace-pre-wrap">
                      {selectedLog.response_out || <span className="italic text-gray-400">No response text recorded</span>}
                    </div>
                  </div>

                  {/* Metadata */}
                  {selectedLog.metadata && Object.keys(selectedLog.metadata).length > 0 && (
                    <div>
                      <p className="text-xs font-bold text-gray-700 mb-1">Metadata:</p>
                      <pre className="rounded-xl bg-gray-50 border border-gray-200 p-3 text-xs font-mono text-gray-700">
                        {JSON.stringify(selectedLog.metadata, null, 2)}
                      </pre>
                    </div>
                  )}
                </div>
              )}

              {/* Tab 2: Raw Incoming */}
              {activeTab === "raw" && (
                <div className="space-y-2">
                  <div className="flex items-center justify-between">
                    <p className="text-xs text-gray-500 font-medium">Raw Incoming JSON payload received from Webhook:</p>
                    <button
                      onClick={() => copyToClipboard(JSON.stringify(selectedLog.raw_payload, null, 2), "raw")}
                      className="rounded bg-gray-100 hover:bg-gray-200 px-2 py-1 text-[11px] font-medium text-gray-700"
                    >
                      {copiedKey === "raw" ? "✓ Copied" : "Copy JSON"}
                    </button>
                  </div>
                  <pre className="max-h-[420px] overflow-x-auto rounded-xl bg-gray-950 p-4 text-xs font-mono text-emerald-400 shadow-inner">
                    {JSON.stringify(selectedLog.raw_payload || { status: "No raw payload stored" }, null, 2)}
                  </pre>
                </div>
              )}

              {/* Tab 3: Outgoing Payload */}
              {activeTab === "outgoing" && (
                <div className="space-y-4">
                  <div>
                    <div className="flex items-center justify-between mb-1.5">
                      <p className="text-xs text-gray-500 font-medium">Payload dispatched to Meta Cloud API:</p>
                      <button
                        onClick={() => copyToClipboard(JSON.stringify(selectedLog.outgoing_payload, null, 2), "out")}
                        className="rounded bg-gray-100 hover:bg-gray-200 px-2 py-1 text-[11px] font-medium text-gray-700"
                      >
                        {copiedKey === "out" ? "✓ Copied" : "Copy JSON"}
                      </button>
                    </div>
                    <pre className="max-h-[220px] overflow-x-auto rounded-xl bg-gray-950 p-4 text-xs font-mono text-sky-300 shadow-inner">
                      {JSON.stringify(selectedLog.outgoing_payload || { status: "No outgoing payload recorded" }, null, 2)}
                    </pre>
                  </div>

                  {selectedLog.meta_response && (
                    <div>
                      <div className="flex items-center justify-between mb-1.5">
                        <p className="text-xs text-gray-500 font-medium">Response returned from Meta Graph API (Status: {selectedLog.meta_status}):</p>
                      </div>
                      <pre className="max-h-[200px] overflow-x-auto rounded-xl bg-gray-900 p-4 text-xs font-mono text-amber-300 shadow-inner">
                        {JSON.stringify(selectedLog.meta_response, null, 2)}
                      </pre>
                    </div>
                  )}
                </div>
              )}

              {/* Tab 4: Errors */}
              {activeTab === "error" && (
                <div className="space-y-3">
                  <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-red-900">
                    <p className="font-bold text-xs text-red-700 uppercase">Error Message</p>
                    <p className="mt-1 text-sm font-semibold">{selectedLog.error || "Unknown error"}</p>
                  </div>

                  {selectedLog.traceback && (
                    <div>
                      <p className="text-xs font-bold text-gray-700 mb-1">Stack Trace:</p>
                      <pre className="max-h-[350px] overflow-x-auto rounded-xl bg-gray-950 p-4 text-xs font-mono text-red-400 shadow-inner">
                        {selectedLog.traceback}
                      </pre>
                    </div>
                  )}
                </div>
              )}
            </div>

            {/* Modal Footer */}
            <div className="flex items-center justify-end border-t border-gray-200 px-6 py-3 bg-gray-50">
              <button
                onClick={() => setSelectedLog(null)}
                className="rounded-lg bg-gray-800 hover:bg-gray-900 px-4 py-2 text-xs font-semibold text-white transition-colors"
              >
                Close Inspector
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
