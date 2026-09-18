"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { UsageStats, SuperAdminOverview } from "@/types";

// ── Admin overview (per-institution) ─────────────────────────────────────────
function AdminOverview() {
  const [stats, setStats] = useState<UsageStats | null>(null);
  const [docCount, setDocCount] = useState(0);

  useEffect(() => {
    api.getUsage().then(setStats).catch(console.error);
    api.listDocuments().then((r) => setDocCount(r.total)).catch(console.error);
  }, []);

  const cards = [
    { title: "Total Queries", value: stats?.total_queries ?? "—", color: "bg-blue-500" },
    { title: "Queries Today", value: stats?.queries_today ?? "—", color: "bg-green-500" },
    { title: "Documents", value: docCount, color: "bg-purple-500" },
    { title: "LLM Quota Left", value: stats?.remaining_llm_quota ?? "—", color: "bg-orange-500" },
  ];

  return (
    <div>
      <h1 className="mb-6 text-2xl font-bold">Overview</h1>

      <div className="mb-8 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {cards.map((card) => (
          <div key={card.title} className="rounded-xl bg-white p-6 shadow-sm">
            <p className="text-sm font-medium text-gray-500">{card.title}</p>
            <p className="mt-2 text-3xl font-bold text-gray-900">{String(card.value)}</p>
            <div className={`mt-3 h-1 w-12 rounded-full ${card.color}`} />
          </div>
        ))}
      </div>

      {/* Quick Actions */}
      <div className="mb-8 rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
        <h2 className="mb-4 text-base font-semibold text-slate-900">Quick Actions</h2>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
          <Link
            href="/dashboard/settings"
            className="group flex flex-col justify-between rounded-xl border border-emerald-200 bg-emerald-50/50 p-4 transition hover:bg-emerald-50 hover:shadow-sm"
          >
            <div>
              <div className="flex items-center gap-2">
                <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-emerald-100 text-sm font-bold text-emerald-700">
                  ⚡
                </span>
                <h3 className="font-semibold text-sm text-slate-800 group-hover:text-emerald-800">
                  Visual Menu & Channel Builder
                </h3>
              </div>
              <p className="mt-2 text-xs text-slate-500 leading-relaxed">
                Build serial-numbered interactive menus, attach WhatsApp media headers, and configure RAG prompt triggers.
              </p>
            </div>
            <span className="mt-3 text-xs font-semibold text-emerald-700 group-hover:underline">
              Open Visual Builder &rarr;
            </span>
          </Link>

          <Link
            href="/dashboard/documents"
            className="group flex flex-col justify-between rounded-xl border border-blue-200 bg-blue-50/50 p-4 transition hover:bg-blue-50 hover:shadow-sm"
          >
            <div>
              <div className="flex items-center gap-2">
                <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-blue-100 text-sm font-bold text-blue-700">
                  📄
                </span>
                <h3 className="font-semibold text-sm text-slate-800 group-hover:text-blue-800">
                  Knowledge Documents
                </h3>
              </div>
              <p className="mt-2 text-xs text-slate-500 leading-relaxed">
                Upload PDFs, prospectuses, and brochures for semantic search and vector indexing.
              </p>
            </div>
            <span className="mt-3 text-xs font-semibold text-blue-700 group-hover:underline">
              Manage Documents &rarr;
            </span>
          </Link>

          <Link
            href="/dashboard/chat-test"
            className="group flex flex-col justify-between rounded-xl border border-purple-200 bg-purple-50/50 p-4 transition hover:bg-purple-50 hover:shadow-sm"
          >
            <div>
              <div className="flex items-center gap-2">
                <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-purple-100 text-sm font-bold text-purple-700">
                  💬
                </span>
                <h3 className="font-semibold text-sm text-slate-800 group-hover:text-purple-800">
                  Interactive Test Chat
                </h3>
              </div>
              <p className="mt-2 text-xs text-slate-500 leading-relaxed">
                Simulate conversations in real time across WhatsApp, web widget, and API channels.
              </p>
            </div>
            <span className="mt-3 text-xs font-semibold text-purple-700 group-hover:underline">
              Launch Test Sandbox &rarr;
            </span>
          </Link>
        </div>
      </div>

      {stats && stats.avg_response_time_ms > 0 && (
        <div className="rounded-xl bg-white p-6 shadow-sm">
          <h2 className="mb-2 text-lg font-semibold">Performance</h2>
          <p className="text-sm text-gray-600">
            Avg response time:{" "}
            <span className="font-semibold">{stats.avg_response_time_ms} ms</span>
          </p>
        </div>
      )}

      {stats && stats.top_queries.length > 0 && (
        <div className="mt-6 rounded-xl bg-white p-6 shadow-sm">
          <h2 className="mb-4 text-lg font-semibold">Top Questions</h2>
          <div className="space-y-2">
            {stats.top_queries.map((q, i) => (
              <div key={i} className="flex items-center justify-between rounded-lg bg-gray-50 px-4 py-2">
                <span className="text-sm text-gray-700">{q.query}</span>
                <span className="text-sm font-medium text-gray-500">{q.count}x</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// ── Super admin overview (platform-wide) ──────────────────────────────────────
function SuperAdminOverviewPage() {
  const [data, setData] = useState<SuperAdminOverview | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.superAdminOverview().then(setData).catch(console.error).finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <div className="h-8 w-8 animate-spin rounded-full border-4 border-purple-600 border-t-transparent" />
      </div>
    );
  }

  const platformCards = [
    { title: "Total Institutions", value: data?.total_clients ?? 0, color: "bg-purple-500" },
    { title: "Platform Queries", value: data?.platform_total_queries ?? 0, color: "bg-blue-500" },
    { title: "Total Input Tokens", value: data?.platform_total_input_tokens ?? 0, color: "bg-green-500" },
    { title: "Total Output Tokens", value: data?.platform_total_output_tokens ?? 0, color: "bg-orange-500" },
  ];

  return (
    <div>
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-2xl font-bold">Platform Overview</h1>
        <span className="rounded-full bg-purple-100 px-3 py-1 text-xs font-semibold text-purple-700">
          Super Admin
        </span>
      </div>

      <div className="mb-8 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {platformCards.map((card) => (
          <div key={card.title} className="rounded-xl bg-white p-6 shadow-sm">
            <p className="text-sm font-medium text-gray-500">{card.title}</p>
            <p className="mt-2 text-3xl font-bold text-gray-900">{Number(card.value).toLocaleString()}</p>
            <div className={`mt-3 h-1 w-12 rounded-full ${card.color}`} />
          </div>
        ))}
      </div>

      {/* Top institutions by queries */}
      {data && data.clients.length > 0 && (
        <div className="rounded-xl bg-white p-6 shadow-sm">
          <div className="mb-4 flex items-center justify-between">
            <h2 className="text-lg font-semibold">Institutions</h2>
            <Link href="/dashboard/super-admin" className="text-sm text-blue-600 hover:underline">
              Full usage table →
            </Link>
          </div>
          <div className="space-y-2">
            {data.clients
              .sort((a, b) => b.total_queries - a.total_queries)
              .slice(0, 5)
              .map((c) => (
                <div key={c.client_id} className="flex items-center justify-between rounded-lg bg-gray-50 px-4 py-3">
                  <div>
                    <p className="text-sm font-medium text-gray-800">{c.name}</p>
                    <p className="text-xs text-gray-400">{c.client_id}</p>
                  </div>
                  <div className="text-right">
                    <p className="text-sm font-semibold text-gray-700">{c.total_queries.toLocaleString()} queries</p>
                    <p className="text-xs text-gray-400">{c.queries_today} today</p>
                  </div>
                </div>
              ))}
          </div>
        </div>
      )}

      {data && data.clients.length === 0 && (
        <div className="rounded-xl border-2 border-dashed border-gray-200 p-12 text-center">
          <p className="text-4xl mb-3">🏫</p>
          <p className="font-medium text-gray-700">No institutions yet</p>
          <p className="mt-1 text-sm text-gray-400">Create your first institution to get started.</p>
          <Link
            href="/dashboard/super-admin/institutions"
            className="mt-4 inline-block rounded-lg bg-blue-600 px-5 py-2.5 text-sm font-medium text-white hover:bg-blue-700"
          >
            Manage Institutions
          </Link>
        </div>
      )}
    </div>
  );
}

// ── Root ──────────────────────────────────────────────────────────────────────
export default function DashboardOverview() {
  const { role } = useAuth();
  if (role === "super_admin") return <SuperAdminOverviewPage />;
  return <AdminOverview />;
}
