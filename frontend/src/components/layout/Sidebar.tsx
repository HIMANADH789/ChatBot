"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useAuth } from "@/lib/auth";



const adminNavItems = [
  { href: "/dashboard", label: "Overview", icon: "📊" },
  { href: "/dashboard/conversations", label: "Conversations", icon: "💬" },
  { href: "/dashboard/documents", label: "Documents", icon: "📄" },
  { href: "/dashboard/chat-test", label: "Test Chat", icon: "🧪" },
  { href: "/dashboard/logs", label: "Request Logs", icon: "📋" },
  { href: "/dashboard/analytics", label: "Analytics", icon: "📈" },
  { href: "/dashboard/settings", label: "Settings", icon: "⚙️" },
];

const superAdminNavItems = [
  { href: "/dashboard", label: "Overview", icon: "📊" },
  { href: "/dashboard/super-admin/institutions", label: "Manage Institutions", icon: "🏫" },
  { href: "/dashboard/conversations", label: "Conversations", icon: "💬" },
  { href: "/dashboard/logs", label: "Request Logs", icon: "📋" },
  { href: "/dashboard/super-admin", label: "Usage & Analytics", icon: "📈" },
  { href: "/dashboard/super-admin/settings", label: "Settings", icon: "⚙️" },
];

export default function Sidebar() {
  const pathname = usePathname();
  const { role } = useAuth();

  const isSuperAdmin = role === "super_admin";

  const navItems = isSuperAdmin ? superAdminNavItems : adminNavItems;

  return (
    <aside className="flex h-screen w-64 flex-col border-r border-gray-200 bg-white">
      <div className="border-b border-gray-200 p-6">
        <h1 className="text-lg font-bold text-blue-600">AI Front Desk</h1>
        <p className="text-xs text-gray-400">
          {isSuperAdmin ? "Super Admin" : "Admin Panel"}
        </p>
      </div>

      <nav className="flex-1 space-y-1 p-4">
        {navItems.map((item) => {
          const isActive =
            pathname === item.href ||
            (item.href !== "/dashboard" && pathname.startsWith(item.href));
          return (
            <Link
              key={item.href}
              href={item.href}
              className={`flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-colors ${
                isActive
                  ? "bg-blue-50 text-blue-700"
                  : "text-gray-600 hover:bg-gray-50 hover:text-gray-900"
              }`}
            >
              <span>{item.icon}</span>
              {item.label}
            </Link>
          );
        })}
      </nav>

      {isSuperAdmin && (
        <div className="border-t border-gray-200 p-4">
          <span className="inline-flex items-center rounded-full bg-purple-100 px-2.5 py-0.5 text-xs font-medium text-purple-700">
            Super Admin
          </span>
        </div>
      )}
    </aside>
  );
}
