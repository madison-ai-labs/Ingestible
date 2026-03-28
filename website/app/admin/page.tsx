"use client";

import { useState, useEffect, useCallback, useMemo } from "react";
import { getSupabase } from "@/lib/supabase-browser";
import type { User, Session } from "@supabase/supabase-js";

interface QuotaOverrides {
  requests_per_day?: number | null;
  max_documents?: number | null;
  max_api_keys?: number | null;
  max_file_size_mb?: number | null;
}

interface UserProfile {
  id: string;
  email: string;
  name: string | null;
  avatar_url: string | null;
  role: "free" | "premium" | "admin";
  suspended: boolean;
  quota_overrides?: QuotaOverrides | null;
  created_at: string;
  usage: {
    total_keys: number;
    active_keys: number;
    total_requests: number;
    total_tokens: number;
    total_documents: number;
    total_searches: number;
    total_errors: number;
    last_used_at: string | null;
  };
}

interface GlobalMetrics {
  summary: {
    total_keys: number;
    active_keys: number;
    total_requests: number;
    total_tokens: number;
    total_documents: number;
    total_searches: number;
    total_errors: number;
    error_rate: string;
    total_bytes_uploaded: number;
    estimated_monthly_cost: string;
    total_storage_bytes: number;
  };
  daily: { date: string; requests: number; errors: number; tokens: number; bytes: number }[];
  keys: unknown[];
}

export default function AdminPage() {
  const [user, setUser] = useState<User | null>(null);
  const [session, setSession] = useState<Session | null>(null);
  const [checking, setChecking] = useState(true);
  const [denied, setDenied] = useState(false);
  const supabase = getSupabase();

  const verifyAndSetSession = useCallback(async (s: Session | null) => {
    if (s) {
      setSession(s);
      setUser(s.user);
      try {
        const res = await fetch("/api/admin/users", {
          headers: { Authorization: `Bearer ${s.access_token}` },
        });
        setDenied(res.status === 403);
      } catch {
        setDenied(true);
      }
    } else {
      setSession(null);
      setUser(null);
    }
    setChecking(false);
  }, []);

  useEffect(() => {
    const { data: { subscription } } = supabase.auth.onAuthStateChange((_event: string, s: any) => {
      verifyAndSetSession(s);
    });

    supabase.auth.getSession().then(({ data }: { data: { session: Session | null } }) => {
      verifyAndSetSession(data.session);
    });

    return () => subscription.unsubscribe();
  }, [verifyAndSetSession]);

  if (checking) {
    return (
      <div className="pt-16 flex items-center justify-center min-h-screen">
        <div className="w-6 h-6 border-2 border-amber-400 border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  if (!user || !session) {
    return (
      <div className="pt-16 flex items-center justify-center min-h-screen px-4">
        <div className="w-full max-w-sm text-center">
          <h1 className="text-2xl font-bold text-zinc-100 mb-3">Admin</h1>
          <p className="text-sm text-zinc-400 mb-6">Sign in with an authorized account.</p>
          <button
            onClick={() => supabase?.auth.signInWithOAuth({ provider: "github", options: { redirectTo: `${window.location.origin}/auth/callback?next=/admin` } })}
            className="w-full flex items-center justify-center gap-2.5 px-4 py-2.5 rounded-lg border border-zinc-700 text-zinc-200 text-sm font-medium hover:bg-zinc-800 transition-colors"
          >
            <svg className="w-5 h-5" fill="currentColor" viewBox="0 0 24 24"><path fillRule="evenodd" d="M12 2C6.477 2 2 6.484 2 12.017c0 4.425 2.865 8.18 6.839 9.504.5.092.682-.217.682-.483 0-.237-.008-.868-.013-1.703-2.782.605-3.369-1.343-3.369-1.343-.454-1.158-1.11-1.466-1.11-1.466-.908-.62.069-.608.069-.608 1.003.07 1.531 1.032 1.531 1.032.892 1.53 2.341 1.088 2.91.832.092-.647.35-1.088.636-1.338-2.22-.253-4.555-1.113-4.555-4.951 0-1.093.39-1.988 1.029-2.688-.103-.253-.446-1.272.098-2.65 0 0 .84-.27 2.75 1.026A9.564 9.564 0 0112 6.844c.85.004 1.705.115 2.504.337 1.909-1.296 2.747-1.027 2.747-1.027.546 1.379.202 2.398.1 2.651.64.7 1.028 1.595 1.028 2.688 0 3.848-2.339 4.695-4.566 4.943.359.309.678.92.678 1.855 0 1.338-.012 2.419-.012 2.747 0 .268.18.58.688.482A10.019 10.019 0 0022 12.017C22 6.484 17.522 2 12 2z" clipRule="evenodd" /></svg>
            Continue with GitHub
          </button>
        </div>
      </div>
    );
  }

  if (denied) {
    return (
      <div className="pt-16 flex items-center justify-center min-h-screen px-4">
        <div className="w-full max-w-sm text-center">
          <h1 className="text-2xl font-bold text-zinc-100 mb-3">Access Denied</h1>
          <p className="text-sm text-zinc-400 mb-6">{user.email} is not authorized for admin access.</p>
          <button onClick={() => supabase?.auth.signOut()} className="text-sm text-zinc-400 hover:text-zinc-200 transition-colors px-3 py-1.5 rounded-lg border border-zinc-800 hover:border-zinc-700">
            Sign out
          </button>
        </div>
      </div>
    );
  }

  return <AdminDashboard token={session.access_token} onLogout={() => supabase?.auth.signOut()} />;
}

/* ── Types ── */

interface AuditEvent {
  id: string;
  type: string;
  description: string;
  actor_email: string;
  ip_address: string | null;
  created_at: string;
}

interface TierConfig {
  name: string;
  requests_per_day: number;
  requests_per_minute: number;
  max_documents: number;
  max_api_keys: number;
  max_file_size_mb: number;
  enrichment_enabled: boolean;
}

/* ── Helpers ── */

function timeAgo(date: string): string {
  const seconds = Math.floor((Date.now() - new Date(date).getTime()) / 1000);
  if (seconds < 60) return "just now";
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  if (seconds < 604800) return `${Math.floor(seconds / 86400)}d ago`;
  return new Date(date).toLocaleDateString();
}

function fmt(n: number): string {
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + "M";
  if (n >= 1_000) return (n / 1_000).toFixed(1) + "K";
  return n.toString();
}

function formatBytes(b: number): string {
  if (b >= 1_073_741_824) return (b / 1_073_741_824).toFixed(1) + " GB";
  if (b >= 1_048_576) return (b / 1_048_576).toFixed(1) + " MB";
  if (b >= 1_024) return (b / 1_024).toFixed(1) + " KB";
  return b + " B";
}

function formatCost(tokens: number): string {
  // Rough estimate: $0.10/1M tokens (Gemini Flash)
  const cost = (tokens / 1_000_000) * 0.10;
  if (cost < 0.01) return "< $0.01";
  return "$" + cost.toFixed(2);
}

/* ── Admin Dashboard ── */

function AdminDashboard({ token, onLogout }: { token: string; onLogout: () => void }) {
  const [tab, setTab] = useState<"users" | "audit" | "metrics" | "settings">("users");
  const [users, setUsers] = useState<UserProfile[]>([]);
  const [metrics, setMetrics] = useState<GlobalMetrics | null>(null);
  const [loading, setLoading] = useState(true);

  // Users tab state
  const [search, setSearch] = useState("");
  const [roleFilter, setRoleFilter] = useState<"all" | "free" | "premium" | "admin" | "suspended">("all");
  const [sortBy, setSortBy] = useState<"signup" | "active" | "requests">("signup");
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [bulkLoading, setBulkLoading] = useState(false);

  // User detail / quota state
  const [expandedUserId, setExpandedUserId] = useState<string | null>(null);
  const [quotaDraft, setQuotaDraft] = useState<QuotaOverrides>({});
  const [quotaSaving, setQuotaSaving] = useState(false);

  // Audit tab state
  const [auditEvents, setAuditEvents] = useState<AuditEvent[]>([]);
  const [auditTypeFilter, setAuditTypeFilter] = useState<string>("all");
  const [auditOffset, setAuditOffset] = useState(0);
  const [auditLoading, setAuditLoading] = useState(false);
  const [auditHasMore, setAuditHasMore] = useState(true);

  // Settings tab state
  const [tiers, setTiers] = useState<TierConfig[]>([]);
  const [editingTier, setEditingTier] = useState<string | null>(null);
  const [tierDraft, setTierDraft] = useState<TierConfig | null>(null);
  const [tiersLoading, setTiersLoading] = useState(false);

  const headers = useMemo(() => ({ Authorization: `Bearer ${token}` }), [token]);

  const loadUsers = useCallback(async () => {
    try {
      const res = await fetch("/api/admin/users", { headers });
      if (res.ok) setUsers(await res.json());
    } catch {}
  }, [headers]);

  const loadMetrics = useCallback(async () => {
    try {
      const res = await fetch("/api/admin/metrics?days=30", { headers });
      if (res.ok) setMetrics(await res.json());
    } catch {}
  }, [headers]);

  useEffect(() => {
    Promise.all([loadUsers(), loadMetrics()]).then(() => setLoading(false));
  }, [loadUsers, loadMetrics]);

  // Load audit events
  const loadAudit = useCallback(async (offset: number, append: boolean = false) => {
    setAuditLoading(true);
    try {
      const res = await fetch(`/api/admin/audit?limit=50&offset=${offset}`, { headers });
      if (res.ok) {
        const data: AuditEvent[] = await res.json();
        setAuditEvents((prev) => append ? [...prev, ...data] : data);
        setAuditHasMore(data.length === 50);
      }
    } catch {}
    setAuditLoading(false);
  }, [headers]);

  // Load tiers
  const loadTiers = useCallback(async () => {
    setTiersLoading(true);
    try {
      const res = await fetch("/api/admin/tiers", { headers });
      if (res.ok) setTiers(await res.json());
    } catch {}
    setTiersLoading(false);
  }, [headers]);

  // Load data when switching tabs
  useEffect(() => {
    if (tab === "audit" && auditEvents.length === 0) {
      loadAudit(0);
    }
    if ((tab === "settings" || tab === "users") && tiers.length === 0) {
      loadTiers();
    }
  }, [tab, auditEvents.length, tiers.length, loadAudit, loadTiers]);

  async function setRole(userId: string, role: string) {
    await fetch(`/api/admin/users/${userId}`, {
      method: "PATCH",
      headers: { ...headers, "Content-Type": "application/json" },
      body: JSON.stringify({ role }),
    });
    loadUsers();
  }

  async function setSuspended(userId: string, suspended: boolean) {
    await fetch(`/api/admin/users/${userId}`, {
      method: "PATCH",
      headers: { ...headers, "Content-Type": "application/json" },
      body: JSON.stringify({ userId, suspended }),
    });
    loadUsers();
  }

  async function saveQuotaOverrides(userId: string, overrides: QuotaOverrides) {
    setQuotaSaving(true);
    await fetch(`/api/admin/users/${userId}`, {
      method: "PATCH",
      headers: { ...headers, "Content-Type": "application/json" },
      body: JSON.stringify({ userId, quota_overrides: overrides }),
    });
    setQuotaSaving(false);
    loadUsers();
  }

  // Filtered + sorted users
  const filteredUsers = useMemo(() => {
    let result = users;

    // Search filter
    if (search.trim()) {
      const q = search.toLowerCase();
      result = result.filter(
        (u) =>
          u.email.toLowerCase().includes(q) ||
          (u.name && u.name.toLowerCase().includes(q))
      );
    }

    // Role filter
    if (roleFilter === "suspended") {
      result = result.filter((u) => u.suspended);
    } else if (roleFilter !== "all") {
      result = result.filter((u) => u.role === roleFilter);
    }

    // Sort
    result = [...result].sort((a, b) => {
      if (sortBy === "signup") return new Date(b.created_at).getTime() - new Date(a.created_at).getTime();
      if (sortBy === "active") {
        const aTime = a.usage.last_used_at ? new Date(a.usage.last_used_at).getTime() : 0;
        const bTime = b.usage.last_used_at ? new Date(b.usage.last_used_at).getTime() : 0;
        return bTime - aTime;
      }
      return b.usage.total_requests - a.usage.total_requests;
    });

    return result;
  }, [users, search, roleFilter, sortBy]);

  const freeCount = users.filter((u) => u.role === "free").length;
  const premiumCount = users.filter((u) => u.role === "premium").length;

  // Selection helpers
  const allSelected = filteredUsers.length > 0 && filteredUsers.every((u) => selectedIds.has(u.id));
  const someSelected = selectedIds.size > 0;

  function toggleSelect(id: string) {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function toggleSelectAll() {
    if (allSelected) {
      setSelectedIds(new Set());
    } else {
      setSelectedIds(new Set(filteredUsers.map((u) => u.id)));
    }
  }

  async function bulkSetRole(role: string) {
    setBulkLoading(true);
    const promises = Array.from(selectedIds).map((id) =>
      fetch(`/api/admin/users/${id}`, {
        method: "PATCH",
        headers: { ...headers, "Content-Type": "application/json" },
        body: JSON.stringify({ role }),
      })
    );
    await Promise.all(promises);
    setSelectedIds(new Set());
    setBulkLoading(false);
    loadUsers();
  }

  async function bulkSetSuspended(suspended: boolean) {
    setBulkLoading(true);
    const promises = Array.from(selectedIds).map((id) =>
      fetch(`/api/admin/users/${id}`, {
        method: "PATCH",
        headers: { ...headers, "Content-Type": "application/json" },
        body: JSON.stringify({ userId: id, suspended }),
      })
    );
    await Promise.all(promises);
    setSelectedIds(new Set());
    setBulkLoading(false);
    loadUsers();
  }

  function exportSelected() {
    const selected = users.filter((u) => selectedIds.has(u.id));
    const csvHeader = "id,email,name,role,created_at,total_requests,total_documents\n";
    const csvRows = selected
      .map((u) => `${u.id},${u.email},${u.name || ""},${u.role},${u.created_at},${u.usage.total_requests},${u.usage.total_documents}`)
      .join("\n");
    const blob = new Blob([csvHeader + csvRows], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "users-export.csv";
    a.click();
    URL.revokeObjectURL(url);
  }

  async function exportAllUsers() {
    try {
      const res = await fetch("/api/admin/users/export", { headers });
      if (res.ok) {
        const blob = await res.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = "all-users-export.csv";
        a.click();
        URL.revokeObjectURL(url);
      }
    } catch {}
  }

  async function exportAuditLog() {
    try {
      const res = await fetch("/api/admin/audit/export", { headers });
      if (res.ok) {
        const blob = await res.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = "audit-log-export.csv";
        a.click();
        URL.revokeObjectURL(url);
      }
    } catch {}
  }

  async function saveTier(tier: TierConfig) {
    await fetch("/api/admin/tiers", {
      method: "PATCH",
      headers: { ...headers, "Content-Type": "application/json" },
      body: JSON.stringify(tier),
    });
    setEditingTier(null);
    setTierDraft(null);
    loadTiers();
  }

  // Audit event types for filter dropdown
  const auditEventTypes = useMemo(() => {
    const types = new Set(auditEvents.map((e) => e.type));
    return Array.from(types).sort();
  }, [auditEvents]);

  const filteredAuditEvents = useMemo(() => {
    if (auditTypeFilter === "all") return auditEvents;
    return auditEvents.filter((e) => e.type === auditTypeFilter);
  }, [auditEvents, auditTypeFilter]);

  if (loading) {
    return (
      <div className="pt-16 flex items-center justify-center min-h-[60vh]">
        <div className="w-6 h-6 border-2 border-amber-400 border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  return (
    <div className="pt-16 min-h-screen">
      <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <div className="flex items-center justify-between mb-6">
          <h1 className="text-2xl font-bold text-zinc-100">Admin</h1>
          <button onClick={onLogout} className="text-sm text-zinc-400 hover:text-zinc-200 transition-colors px-3 py-1.5 rounded-lg border border-zinc-800 hover:border-zinc-700">
            Sign out
          </button>
        </div>

        {/* Summary cards */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mb-6">
          <StatCard label="Total Users" value={users.length} />
          <StatCard label="Premium" value={premiumCount} accent="amber" />
          <StatCard label="Free" value={freeCount} />
          <StatCard label="Total Requests" value={users.reduce((s, u) => s + u.usage.total_requests, 0).toLocaleString()} />
          {metrics && (
            <>
              <StatCard label="Tokens Used" value={fmt(metrics.summary.total_tokens)} />
              <StatCard label="Est. Cost" value={formatCost(metrics.summary.total_tokens)} accent="amber" />
              <StatCard label="Storage" value={formatBytes(metrics.summary.total_bytes_uploaded)} />
            </>
          )}
        </div>

        {/* Tabs */}
        <div className="flex gap-1 mb-6 border-b border-zinc-800">
          {(["users", "audit", "metrics", "settings"] as const).map((t) => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={`px-4 py-2.5 text-sm font-medium transition-colors border-b-2 -mb-px capitalize ${
                tab === t ? "text-amber-400 border-amber-400" : "text-zinc-400 border-transparent hover:text-zinc-200"
              }`}
            >
              {t === "audit" ? "Audit Log" : t}
            </button>
          ))}
        </div>

        {/* ── Users Tab ── */}
        {tab === "users" && (
          <div className="space-y-4">
            {/* User count summary */}
            <p className="text-xs text-zinc-500">
              {users.length} users total &middot; {premiumCount} premium &middot; {freeCount} free
            </p>

            {/* Search, filter, sort, export */}
            <div className="flex flex-wrap items-center gap-3">
              <input
                type="text"
                placeholder="Search by email or name..."
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                className="flex-1 min-w-[200px] px-4 py-2.5 rounded-lg bg-zinc-800/50 border border-zinc-700/50 text-zinc-100 placeholder:text-zinc-500 text-sm focus:outline-none focus:ring-2 focus:ring-amber-400/50"
              />
              <select
                value={roleFilter}
                onChange={(e) => setRoleFilter(e.target.value as typeof roleFilter)}
                className="px-3 py-2.5 rounded-lg bg-zinc-800/50 border border-zinc-700/50 text-zinc-100 text-sm focus:outline-none focus:ring-2 focus:ring-amber-400/50"
              >
                <option value="all">All Roles</option>
                <option value="free">Free</option>
                <option value="premium">Premium</option>
                <option value="admin">Admin</option>
                <option value="suspended">Suspended</option>
              </select>
              <select
                value={sortBy}
                onChange={(e) => setSortBy(e.target.value as typeof sortBy)}
                className="px-3 py-2.5 rounded-lg bg-zinc-800/50 border border-zinc-700/50 text-zinc-100 text-sm focus:outline-none focus:ring-2 focus:ring-amber-400/50"
              >
                <option value="signup">Sort: Signup Date</option>
                <option value="active">Sort: Last Active</option>
                <option value="requests">Sort: Total Requests</option>
              </select>
              <button
                onClick={exportAllUsers}
                className="px-3 py-2.5 rounded-lg border border-zinc-700/50 text-zinc-400 text-sm hover:text-zinc-200 hover:border-zinc-600 transition-colors"
              >
                Export CSV
              </button>
            </div>

            {/* Bulk action bar */}
            {someSelected && (
              <div className="flex items-center gap-3 px-4 py-3 rounded-xl border border-amber-500/20 bg-amber-500/5">
                <span className="text-sm text-zinc-300">{selectedIds.size} selected</span>
                <div className="flex-1" />
                <button
                  onClick={() => bulkSetRole("premium")}
                  disabled={bulkLoading}
                  className="text-xs px-3 py-1.5 rounded-lg bg-amber-500/10 text-amber-400 border border-amber-500/20 hover:bg-amber-500/20 transition-colors disabled:opacity-50"
                >
                  Upgrade to Premium
                </button>
                <button
                  onClick={() => bulkSetRole("free")}
                  disabled={bulkLoading}
                  className="text-xs px-3 py-1.5 rounded-lg bg-zinc-800 text-zinc-300 border border-zinc-700 hover:bg-zinc-700 transition-colors disabled:opacity-50"
                >
                  Downgrade to Free
                </button>
                <button
                  onClick={() => bulkSetSuspended(true)}
                  disabled={bulkLoading}
                  className="text-xs px-3 py-1.5 rounded-lg bg-red-500/10 text-red-400 border border-red-500/20 hover:bg-red-500/20 transition-colors disabled:opacity-50"
                >
                  Suspend selected
                </button>
                <button
                  onClick={() => bulkSetSuspended(false)}
                  disabled={bulkLoading}
                  className="text-xs px-3 py-1.5 rounded-lg bg-green-500/10 text-green-400 border border-green-500/20 hover:bg-green-500/20 transition-colors disabled:opacity-50"
                >
                  Unsuspend selected
                </button>
                <button
                  onClick={exportSelected}
                  className="text-xs px-3 py-1.5 rounded-lg bg-zinc-800 text-zinc-300 border border-zinc-700 hover:bg-zinc-700 transition-colors"
                >
                  Export Selected
                </button>
              </div>
            )}

            {/* Select all */}
            {filteredUsers.length > 0 && (
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={allSelected}
                  onChange={toggleSelectAll}
                  className="w-4 h-4 rounded border-zinc-600 bg-zinc-800 text-amber-400 focus:ring-amber-400/50"
                />
                <span className="text-xs text-zinc-400">Select all ({filteredUsers.length})</span>
              </label>
            )}

            {/* User list */}
            {filteredUsers.length === 0 ? (
              <div className="text-center py-12 text-zinc-500">
                {users.length === 0 ? "No users yet." : "No users match your filters."}
              </div>
            ) : (
              <div className="space-y-2">
                {filteredUsers.map((u) => (
                  <UserRow
                    key={u.id}
                    user={u}
                    onSetRole={setRole}
                    onSetSuspended={setSuspended}
                    selected={selectedIds.has(u.id)}
                    onToggleSelect={() => toggleSelect(u.id)}
                    expanded={expandedUserId === u.id}
                    onToggleExpand={() => {
                      if (expandedUserId === u.id) {
                        setExpandedUserId(null);
                      } else {
                        setExpandedUserId(u.id);
                        setQuotaDraft({
                          requests_per_day: u.quota_overrides?.requests_per_day ?? null,
                          max_documents: u.quota_overrides?.max_documents ?? null,
                          max_api_keys: u.quota_overrides?.max_api_keys ?? null,
                          max_file_size_mb: u.quota_overrides?.max_file_size_mb ?? null,
                        });
                      }
                    }}
                    quotaDraft={quotaDraft}
                    onQuotaChange={(field, value) => setQuotaDraft((prev) => ({ ...prev, [field]: value }))}
                    onQuotaReset={(field) => setQuotaDraft((prev) => ({ ...prev, [field]: null }))}
                    onQuotaSave={() => saveQuotaOverrides(u.id, quotaDraft)}
                    quotaSaving={quotaSaving}
                    tiers={tiers}
                  />
                ))}
              </div>
            )}
          </div>
        )}

        {/* ── Audit Log Tab ── */}
        {tab === "audit" && (
          <div className="space-y-4">
            <div className="flex items-center gap-3">
              <select
                value={auditTypeFilter}
                onChange={(e) => setAuditTypeFilter(e.target.value)}
                className="px-3 py-2.5 rounded-lg bg-zinc-800/50 border border-zinc-700/50 text-zinc-100 text-sm focus:outline-none focus:ring-2 focus:ring-amber-400/50"
              >
                <option value="all">All Events</option>
                {auditEventTypes.map((t) => (
                  <option key={t} value={t}>{t}</option>
                ))}
              </select>
              <div className="flex-1" />
              <button
                onClick={exportAuditLog}
                className="px-3 py-2.5 rounded-lg border border-zinc-700/50 text-zinc-400 text-sm hover:text-zinc-200 hover:border-zinc-600 transition-colors"
              >
                Export CSV
              </button>
            </div>

            {auditLoading && auditEvents.length === 0 ? (
              <div className="flex items-center justify-center py-12">
                <div className="w-6 h-6 border-2 border-amber-400 border-t-transparent rounded-full animate-spin" />
              </div>
            ) : filteredAuditEvents.length === 0 ? (
              <div className="text-center py-12 text-zinc-500">No audit events found.</div>
            ) : (
              <div className="space-y-1">
                {filteredAuditEvents.map((event) => (
                  <AuditRow key={event.id} event={event} />
                ))}
              </div>
            )}

            {auditHasMore && !auditLoading && (
              <div className="flex justify-center pt-2">
                <button
                  onClick={() => {
                    const next = auditOffset + 50;
                    setAuditOffset(next);
                    loadAudit(next, true);
                  }}
                  className="px-4 py-2 rounded-lg border border-zinc-700/50 text-zinc-400 text-sm hover:text-zinc-200 hover:border-zinc-600 transition-colors"
                >
                  Load more
                </button>
              </div>
            )}
            {auditLoading && auditEvents.length > 0 && (
              <div className="flex justify-center py-4">
                <div className="w-5 h-5 border-2 border-amber-400 border-t-transparent rounded-full animate-spin" />
              </div>
            )}
          </div>
        )}

        {/* ── Metrics Tab ── */}
        {tab === "metrics" && (
          <div className="space-y-6">
            {!metrics ? (
              <div className="text-center py-12 text-zinc-500">No metrics data available.</div>
            ) : (
              <>
                {/* Summary cards */}
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
                  <StatCard label="Total Requests" value={metrics.summary.total_requests.toLocaleString()} />
                  <StatCard
                    label="Error Rate"
                    value={metrics.summary.error_rate}
                    accent={parseFloat(metrics.summary.error_rate) > 5 ? "red" : undefined}
                  />
                  <StatCard label="Total Documents" value={metrics.summary.total_documents.toLocaleString()} />
                  <StatCard label="Est. Monthly Cost" value={metrics.summary.estimated_monthly_cost} accent="amber" />
                </div>

                {/* Daily requests bar chart */}
                <div className="rounded-xl border border-zinc-800 bg-zinc-900/40 p-5">
                  <h3 className="text-sm font-semibold text-zinc-100 mb-4">Daily Requests (30 days)</h3>
                  <div className="flex items-end gap-1 h-40">
                    {metrics.daily.map((day) => {
                      const maxRequests = Math.max(...metrics.daily.map((d) => d.requests), 1);
                      const barHeight = (day.requests / maxRequests) * 100;
                      const errorHeight = day.requests > 0 ? (day.errors / maxRequests) * 100 : 0;
                      return (
                        <div key={day.date} className="flex-1 flex flex-col items-center justify-end h-full group relative">
                          {/* Tooltip */}
                          <div className="absolute bottom-full mb-2 hidden group-hover:block z-10">
                            <div className="bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 text-xs whitespace-nowrap shadow-lg">
                              <p className="text-zinc-300 font-medium">{day.date}</p>
                              <p className="text-zinc-400">{day.requests.toLocaleString()} requests</p>
                              <p className="text-red-400">{day.errors.toLocaleString()} errors</p>
                            </div>
                          </div>
                          {/* Request bar */}
                          <div className="w-full relative" style={{ height: `${barHeight}%` }}>
                            <div className="absolute inset-0 bg-amber-500/30 rounded-t" />
                            {/* Error overlay at bottom of bar */}
                            {errorHeight > 0 && (
                              <div
                                className="absolute bottom-0 left-0 right-0 bg-red-500/50 rounded-t"
                                style={{ height: `${(day.errors / day.requests) * 100}%` }}
                              />
                            )}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                  <div className="flex justify-between mt-2">
                    <span className="text-[10px] text-zinc-600">{metrics.daily[0]?.date}</span>
                    <span className="text-[10px] text-zinc-600">{metrics.daily[metrics.daily.length - 1]?.date}</span>
                  </div>
                  <div className="flex items-center gap-4 mt-3">
                    <div className="flex items-center gap-1.5">
                      <div className="w-3 h-3 rounded bg-amber-500/30" />
                      <span className="text-[10px] text-zinc-500">Requests</span>
                    </div>
                    <div className="flex items-center gap-1.5">
                      <div className="w-3 h-3 rounded bg-red-500/50" />
                      <span className="text-[10px] text-zinc-500">Errors</span>
                    </div>
                  </div>
                </div>

                {/* Top Users table */}
                <div className="rounded-xl border border-zinc-800 bg-zinc-900/40 p-5">
                  <h3 className="text-sm font-semibold text-zinc-100 mb-4">Top Users by Requests</h3>
                  <div className="space-y-1">
                    <div className="grid grid-cols-[1fr_auto_auto_auto] gap-4 px-3 py-2 text-[10px] text-zinc-500 uppercase tracking-wide">
                      <span>User</span>
                      <span className="text-right">Requests</span>
                      <span className="text-right">Documents</span>
                      <span className="text-right">Errors</span>
                    </div>
                    {[...users]
                      .sort((a, b) => b.usage.total_requests - a.usage.total_requests)
                      .slice(0, 10)
                      .map((u, i) => (
                        <div
                          key={u.id}
                          className="grid grid-cols-[1fr_auto_auto_auto] gap-4 px-3 py-2.5 rounded-lg hover:bg-zinc-800/30 transition-colors"
                        >
                          <div className="flex items-center gap-2 min-w-0">
                            <span className="text-xs text-zinc-600 font-mono w-4">{i + 1}</span>
                            <span className="text-sm text-zinc-200 truncate">{u.name || u.email}</span>
                            <RoleBadge role={u.role} />
                          </div>
                          <span className="text-sm font-mono text-zinc-100 text-right">{u.usage.total_requests.toLocaleString()}</span>
                          <span className="text-sm font-mono text-zinc-400 text-right">{u.usage.total_documents}</span>
                          <span className="text-sm font-mono text-red-400/70 text-right">{u.usage.total_errors}</span>
                        </div>
                      ))}
                  </div>
                </div>
              </>
            )}
          </div>
        )}

        {/* ── Settings Tab ── */}
        {tab === "settings" && (
          <div className="space-y-4">
            {tiersLoading ? (
              <div className="flex items-center justify-center py-12">
                <div className="w-6 h-6 border-2 border-amber-400 border-t-transparent rounded-full animate-spin" />
              </div>
            ) : tiers.length === 0 ? (
              <div className="text-center py-12 text-zinc-500">No tier configuration found.</div>
            ) : (
              <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                {tiers.map((tier) => (
                  <TierCard
                    key={tier.name}
                    tier={editingTier === tier.name && tierDraft ? tierDraft : tier}
                    editing={editingTier === tier.name}
                    onEdit={() => {
                      setEditingTier(tier.name);
                      setTierDraft({ ...tier });
                    }}
                    onCancel={() => {
                      setEditingTier(null);
                      setTierDraft(null);
                    }}
                    onSave={() => {
                      if (tierDraft) saveTier(tierDraft);
                    }}
                    onChange={(field, value) => {
                      if (tierDraft) setTierDraft({ ...tierDraft, [field]: value });
                    }}
                  />
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

/* ── Components ── */

function UserRow({
  user,
  onSetRole,
  onSetSuspended,
  selected,
  onToggleSelect,
  expanded,
  onToggleExpand,
  quotaDraft,
  onQuotaChange,
  onQuotaReset,
  onQuotaSave,
  quotaSaving,
  tiers,
}: {
  user: UserProfile;
  onSetRole: (id: string, role: string) => void;
  onSetSuspended: (id: string, suspended: boolean) => void;
  selected: boolean;
  onToggleSelect: () => void;
  expanded: boolean;
  onToggleExpand: () => void;
  quotaDraft: QuotaOverrides;
  onQuotaChange: (field: keyof QuotaOverrides, value: number | null) => void;
  onQuotaReset: (field: keyof QuotaOverrides) => void;
  onQuotaSave: () => void;
  quotaSaving: boolean;
  tiers: TierConfig[];
}) {
  const hasOverrides = user.quota_overrides &&
    Object.values(user.quota_overrides).some((v) => v !== null && v !== undefined);
  const tierDefaults = tiers.find((t) => t.name === user.role);

  return (
    <div className={`rounded-xl border bg-zinc-900/40 ${user.suspended ? "opacity-60" : ""} ${selected ? "border-amber-500/30" : "border-zinc-800"}`}>
      <div className="px-5 py-4 cursor-pointer" onClick={onToggleExpand}>
        <div className="flex items-start gap-4">
          {/* Checkbox */}
          <input
            type="checkbox"
            checked={selected}
            onChange={onToggleSelect}
            onClick={(e) => e.stopPropagation()}
            className="mt-1.5 w-4 h-4 rounded border-zinc-600 bg-zinc-800 text-amber-400 focus:ring-amber-400/50 flex-shrink-0"
          />

          {/* Avatar */}
          {user.avatar_url ? (
            <img src={user.avatar_url} alt="" className="w-9 h-9 rounded-full flex-shrink-0" />
          ) : (
            <div className="w-9 h-9 rounded-full bg-zinc-800 flex items-center justify-center flex-shrink-0">
              <span className="text-xs font-medium text-zinc-400">{(user.email || "?")[0].toUpperCase()}</span>
            </div>
          )}

          {/* Info */}
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="text-sm font-medium text-zinc-100">{user.name || user.email}</span>
              <RoleBadge role={user.role} />
              {user.suspended && (
                <span className="text-[10px] px-1.5 py-0.5 rounded border bg-red-500/10 text-red-400 border-red-500/20 uppercase font-semibold">
                  Suspended
                </span>
              )}
              {hasOverrides && (
                <span className="text-[10px] px-1.5 py-0.5 rounded border bg-violet-500/10 text-violet-400 border-violet-500/20">
                  custom
                </span>
              )}
            </div>
            {user.name && <p className="text-xs text-zinc-500 mt-0.5">{user.email}</p>}
            <div className="flex items-center gap-3 mt-1.5 flex-wrap">
              <span className="text-xs text-zinc-500">{user.usage.active_keys} key{user.usage.active_keys !== 1 ? "s" : ""}</span>
              <span className="text-xs text-zinc-600">&middot;</span>
              <span className="text-xs text-zinc-500">{user.usage.total_requests.toLocaleString()} requests</span>
              <span className="text-xs text-zinc-600">&middot;</span>
              <span className="text-xs text-zinc-500">{user.usage.total_documents} docs</span>
              <span className="text-xs text-zinc-600">&middot;</span>
              <span className="text-xs text-zinc-500">{user.usage.total_searches.toLocaleString()} searches</span>
              {user.usage.total_tokens > 0 && (
                <>
                  <span className="text-xs text-zinc-600">&middot;</span>
                  <span className="text-xs text-zinc-500">{fmt(user.usage.total_tokens)} tokens</span>
                  <span className="text-xs text-zinc-600">&middot;</span>
                  <span className="text-xs text-zinc-500">{formatCost(user.usage.total_tokens)}</span>
                </>
              )}
              <span className="text-xs text-zinc-600">&middot;</span>
              <span className="text-xs text-zinc-500">joined {new Date(user.created_at).toLocaleDateString()}</span>
              {user.usage.last_used_at && (
                <>
                  <span className="text-xs text-zinc-600">&middot;</span>
                  <span className="text-xs text-zinc-500">active {timeAgo(user.usage.last_used_at)}</span>
                </>
              )}
            </div>
          </div>

          {/* Role actions + Suspend */}
          <div className="flex items-center gap-1 flex-shrink-0" onClick={(e) => e.stopPropagation()}>
            {user.role !== "admin" && (
              <>
                {user.role === "free" && (
                  <button onClick={() => onSetRole(user.id, "premium")} className="text-xs text-amber-400/70 hover:text-amber-400 transition-colors px-2 py-1 rounded hover:bg-amber-400/5">
                    Upgrade
                  </button>
                )}
                {user.role === "premium" && (
                  <button onClick={() => onSetRole(user.id, "free")} className="text-xs text-zinc-400 hover:text-zinc-200 transition-colors px-2 py-1 rounded hover:bg-zinc-800">
                    Downgrade
                  </button>
                )}
                <button
                  onClick={() => onSetSuspended(user.id, !user.suspended)}
                  className={`text-xs px-2 py-1 rounded transition-colors ${
                    user.suspended
                      ? "text-green-400/70 hover:text-green-400 hover:bg-green-400/5"
                      : "text-red-400/70 hover:text-red-400 hover:bg-red-400/5"
                  }`}
                >
                  {user.suspended ? "Unsuspend" : "Suspend"}
                </button>
              </>
            )}
          </div>
        </div>
      </div>

      {/* Expandable details panel */}
      {expanded && (
        <div className="border-t border-zinc-800 px-5 py-4">
          <h4 className="text-xs font-semibold text-zinc-300 uppercase tracking-wide mb-3">Quota Overrides</h4>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            {(
              [
                { key: "requests_per_day" as const, label: "Requests / day" },
                { key: "max_documents" as const, label: "Max documents" },
                { key: "max_api_keys" as const, label: "Max API keys" },
                { key: "max_file_size_mb" as const, label: "Max file size (MB)" },
              ] as const
            ).map(({ key, label }) => (
              <div key={key} className="flex items-center gap-2">
                <label className="text-xs text-zinc-500 w-32 flex-shrink-0">{label}</label>
                <input
                  type="number"
                  value={quotaDraft[key] ?? ""}
                  placeholder={tierDefaults ? String(tierDefaults[key]) : "default"}
                  onChange={(e) => {
                    const val = e.target.value === "" ? null : parseInt(e.target.value);
                    onQuotaChange(key, val);
                  }}
                  className="w-28 px-2 py-1.5 rounded bg-zinc-800/50 border border-zinc-700/50 text-zinc-100 text-xs font-mono text-right focus:outline-none focus:ring-2 focus:ring-amber-400/50 placeholder:text-zinc-600"
                />
                <button
                  onClick={() => onQuotaReset(key)}
                  className="text-[10px] text-zinc-500 hover:text-zinc-300 transition-colors px-1.5 py-1 rounded hover:bg-zinc-800 whitespace-nowrap"
                >
                  Reset to tier default
                </button>
              </div>
            ))}
          </div>
          <div className="flex justify-end mt-4">
            <button
              onClick={onQuotaSave}
              disabled={quotaSaving}
              className="text-xs px-4 py-2 rounded-lg bg-amber-500/10 text-amber-400 border border-amber-500/20 hover:bg-amber-500/20 transition-colors disabled:opacity-50"
            >
              {quotaSaving ? "Saving..." : "Save Overrides"}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

function AuditRow({ event }: { event: AuditEvent }) {
  const typeStyles: Record<string, { color: string; bg: string }> = {
    login: { color: "text-green-400", bg: "bg-green-500/10" },
    signup: { color: "text-green-400", bg: "bg-green-500/10" },
    api_key_created: { color: "text-amber-400", bg: "bg-amber-500/10" },
    api_key_revoked: { color: "text-amber-400", bg: "bg-amber-500/10" },
    api_key_deleted: { color: "text-red-400", bg: "bg-red-500/10" },
    document_deleted: { color: "text-red-400", bg: "bg-red-500/10" },
    user_deleted: { color: "text-red-400", bg: "bg-red-500/10" },
    role_changed: { color: "text-violet-400", bg: "bg-violet-500/10" },
    tier_updated: { color: "text-violet-400", bg: "bg-violet-500/10" },
  };

  const style = typeStyles[event.type] || { color: "text-zinc-400", bg: "bg-zinc-800/50" };

  return (
    <div className="flex items-center gap-4 px-4 py-3 rounded-xl border border-zinc-800 bg-zinc-900/40 border-b border-zinc-800/40 hover:bg-zinc-800/20 transition-colors">
      {/* Event type indicator */}
      <div className={`w-2 h-2 rounded-full flex-shrink-0 ${style.bg} ${style.color}`}>
        <div className={`w-2 h-2 rounded-full ${style.color.replace("text-", "bg-")}`} />
      </div>

      {/* Content */}
      <div className="flex-1 min-w-0">
        <p className="text-sm text-zinc-200 truncate">{event.description}</p>
        <div className="flex items-center gap-2 mt-0.5">
          <span className="text-xs text-zinc-500">{event.actor_email}</span>
          {event.ip_address && (
            <>
              <span className="text-xs text-zinc-600">&middot;</span>
              <span className="text-xs text-zinc-600 font-mono">{event.ip_address}</span>
            </>
          )}
        </div>
      </div>

      {/* Timestamp */}
      <div className="flex flex-col items-end flex-shrink-0">
        <span className={`text-[10px] px-1.5 py-0.5 rounded ${style.bg} ${style.color}`}>{event.type}</span>
        <span className="text-xs text-zinc-500 mt-1">{timeAgo(event.created_at)}</span>
      </div>
    </div>
  );
}

function TierCard({
  tier,
  editing,
  onEdit,
  onCancel,
  onSave,
  onChange,
}: {
  tier: TierConfig;
  editing: boolean;
  onEdit: () => void;
  onCancel: () => void;
  onSave: () => void;
  onChange: (field: keyof TierConfig, value: number | boolean) => void;
}) {
  const borderColor =
    tier.name === "premium" ? "border-amber-500/30" :
    tier.name === "admin" ? "border-violet-500/30" :
    "border-zinc-800";

  const titleColor =
    tier.name === "premium" ? "text-amber-400" :
    tier.name === "admin" ? "text-violet-400" :
    "text-zinc-100";

  const fields: { key: keyof TierConfig; label: string; type: "number" | "toggle" }[] = [
    { key: "requests_per_day", label: "Requests / day", type: "number" },
    { key: "requests_per_minute", label: "Requests / min", type: "number" },
    { key: "max_documents", label: "Max documents", type: "number" },
    { key: "max_api_keys", label: "Max API keys", type: "number" },
    { key: "max_file_size_mb", label: "Max file size (MB)", type: "number" },
    { key: "enrichment_enabled", label: "Enrichment", type: "toggle" },
  ];

  return (
    <div className={`rounded-xl border ${borderColor} bg-zinc-900/40 p-5`}>
      <div className="flex items-center justify-between mb-4">
        <h3 className={`text-sm font-semibold capitalize ${titleColor}`}>{tier.name}</h3>
        {!editing ? (
          <button
            onClick={onEdit}
            className="text-xs text-zinc-400 hover:text-zinc-200 transition-colors px-2 py-1 rounded hover:bg-zinc-800"
          >
            Edit
          </button>
        ) : (
          <div className="flex gap-1">
            <button
              onClick={onCancel}
              className="text-xs text-zinc-400 hover:text-zinc-200 transition-colors px-2 py-1 rounded hover:bg-zinc-800"
            >
              Cancel
            </button>
            <button
              onClick={onSave}
              className="text-xs text-amber-400 hover:text-amber-300 transition-colors px-2 py-1 rounded hover:bg-amber-400/5"
            >
              Save
            </button>
          </div>
        )}
      </div>

      <div className="space-y-3">
        {fields.map(({ key, label, type }) => (
          <div key={key} className="flex items-center justify-between">
            <span className="text-xs text-zinc-500">{label}</span>
            {type === "toggle" ? (
              editing ? (
                <button
                  onClick={() => onChange(key, !(tier[key] as boolean))}
                  className={`w-8 h-4.5 rounded-full transition-colors relative ${
                    tier[key] ? "bg-amber-500" : "bg-zinc-700"
                  }`}
                >
                  <div
                    className={`absolute top-0.5 w-3.5 h-3.5 rounded-full bg-white transition-transform ${
                      tier[key] ? "translate-x-4" : "translate-x-0.5"
                    }`}
                  />
                </button>
              ) : (
                <span className={`text-xs font-mono ${tier[key] ? "text-green-400" : "text-zinc-600"}`}>
                  {tier[key] ? "yes" : "no"}
                </span>
              )
            ) : editing ? (
              <input
                type="number"
                value={tier[key] as number}
                onChange={(e) => onChange(key, parseInt(e.target.value) || 0)}
                className="w-24 px-2 py-1 rounded bg-zinc-800/50 border border-zinc-700/50 text-zinc-100 text-xs font-mono text-right focus:outline-none focus:ring-2 focus:ring-amber-400/50"
              />
            ) : (
              <span className="text-sm font-mono text-zinc-100">{(tier[key] as number).toLocaleString()}</span>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

function RoleBadge({ role }: { role: string }) {
  const styles: Record<string, string> = {
    admin: "bg-violet-500/10 text-violet-400 border-violet-500/20",
    premium: "bg-amber-500/10 text-amber-400 border-amber-500/20",
    free: "bg-zinc-700/30 text-zinc-400 border-zinc-700/50",
  };
  return (
    <span className={`text-[10px] px-1.5 py-0.5 rounded border ${styles[role] || styles.free}`}>
      {role}
    </span>
  );
}

function StatCard({ label, value, accent }: { label: string; value: string | number; accent?: string }) {
  const color = accent === "red" ? "text-red-400" : accent === "amber" ? "text-amber-400" : "text-zinc-100";
  return (
    <div className="rounded-xl border border-zinc-800 bg-zinc-900/40 p-4">
      <p className="text-xs text-zinc-500 mb-1">{label}</p>
      <p className={`text-xl font-bold font-mono ${color}`}>{value}</p>
    </div>
  );
}
