"use client";

import { useEffect, useState, useCallback } from "react";
import { getSupabase } from "@/lib/supabase-browser";
import type { User } from "@supabase/supabase-js";
import Link from "next/link";


interface NotificationSettings {
  notify_quota_warning: boolean;
  notify_quota_exceeded: boolean;
  notify_weekly_digest: boolean;
}

interface Webhook {
  id: string;
  url: string;
  events: string[];
  active: boolean;
  secret?: string;
  last_triggered_at: string | null;
  failure_count: number;
  created_at: string;
}

interface WebhookDelivery {
  id: string;
  event: string;
  status_code: number;
  response_time_ms: number;
  success: boolean;
  created_at: string;
  error?: string;
}

const WEBHOOK_EVENTS = [
  { value: "ingestion.complete", label: "Ingestion complete" },
  { value: "key.revoked", label: "API key revoked" },
  { value: "quota.warning", label: "Quota warning" },
  { value: "quota.exceeded", label: "Quota exceeded" },
];

export default function SettingsPage() {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const supabase = getSupabase();

  useEffect(() => {
    supabase.auth
      .getUser()
      .then(({ data }: { data: { user: User | null } }) => {
        setUser(data.user);
        setLoading(false);
      });

    const {
      data: { subscription },
    } = supabase.auth.onAuthStateChange(
      (_event: string, session: any) => {
        setUser(session?.user ?? null);
      }
    );

    return () => subscription.unsubscribe();
  }, []);

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <div className="w-6 h-6 border-2 border-amber-400 border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  if (!user) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <p className="text-zinc-400 text-sm">
          Please{" "}
          <Link href="/dashboard" className="text-amber-400 hover:underline">
            sign in
          </Link>{" "}
          to access settings.
        </p>
      </div>
    );
  }

  return <SettingsContent user={user} />;
}

/* ── Settings Content ── */

function SettingsContent({ user }: { user: User }) {
  const supabase = getSupabase();

  return (
    <div className="max-w-3xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
      {/* Back link */}
      <Link
        href="/dashboard"
        className="inline-flex items-center gap-1 text-sm text-zinc-400 hover:text-zinc-200 transition-colors mb-6"
      >
        <svg
          className="w-4 h-4"
          fill="none"
          viewBox="0 0 24 24"
          strokeWidth={2}
          stroke="currentColor"
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            d="M15.75 19.5L8.25 12l7.5-7.5"
          />
        </svg>
        Dashboard
      </Link>

      <h1 className="text-2xl font-bold text-zinc-100 mb-8">Settings</h1>

      <div className="space-y-6">
        <ProfileSection user={user} supabase={supabase} />
        <NotificationSection supabase={supabase} />
        <WebhooksSection supabase={supabase} />
        <DangerZone supabase={supabase} />
      </div>
    </div>
  );
}

/* ── Profile Section ── */

function ProfileSection({
  user,
  supabase,
}: {
  user: User;
  supabase: any;
}) {
  const [name, setName] = useState(
    user.user_metadata?.full_name || user.user_metadata?.name || ""
  );
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState("");

  const avatarUrl =
    user.user_metadata?.avatar_url || user.user_metadata?.picture;
  const email = user.email || "";

  async function handleSave(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError("");
    setSaved(false);

    const { error: err } = await supabase.auth.updateUser({
      data: { full_name: name, name },
    });

    if (err) {
      setError(err.message);
    } else {
      setSaved(true);
      setTimeout(() => setSaved(false), 3000);
    }
    setSaving(false);
  }

  return (
    <div className="rounded-2xl border border-zinc-800 bg-zinc-900/60 p-6">
      <h2 className="text-lg font-semibold text-zinc-100 mb-4">Profile</h2>

      <div className="flex items-center gap-4 mb-6">
        {avatarUrl ? (
          <img
            src={avatarUrl}
            alt="Avatar"
            className="w-12 h-12 rounded-full border border-zinc-700"
          />
        ) : (
          <div className="w-12 h-12 rounded-full bg-zinc-800 border border-zinc-700 flex items-center justify-center">
            <span className="text-zinc-400 text-lg font-medium">
              {(name || email).charAt(0).toUpperCase()}
            </span>
          </div>
        )}
        <div>
          <p className="text-sm font-medium text-zinc-100">
            {name || "No name set"}
          </p>
          <p className="text-xs text-zinc-500">{email}</p>
        </div>
      </div>

      <form onSubmit={handleSave} className="space-y-4">
        <div>
          <label className="block text-sm text-zinc-400 mb-1.5">
            Display name
          </label>
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Your name"
            className="w-full px-4 py-2.5 rounded-lg bg-zinc-800/50 border border-zinc-700/50 text-zinc-100 placeholder:text-zinc-500 text-sm focus:outline-none focus:ring-2 focus:ring-amber-400/50"
          />
        </div>

        <div>
          <label className="block text-sm text-zinc-400 mb-1.5">Email</label>
          <input
            type="email"
            value={email}
            disabled
            className="w-full px-4 py-2.5 rounded-lg bg-zinc-800/30 border border-zinc-700/30 text-zinc-500 text-sm cursor-not-allowed"
          />
        </div>

        {error && (
          <div className="rounded-lg bg-red-500/10 border border-red-500/20 px-4 py-2.5 text-sm text-red-400">
            {error}
          </div>
        )}

        <div className="flex items-center gap-3">
          <button
            type="submit"
            disabled={saving}
            className="px-5 py-2.5 rounded-lg bg-amber-500 text-zinc-950 font-semibold text-sm hover:bg-amber-400 disabled:opacity-50 transition-colors"
          >
            {saving ? (
              <span className="flex items-center gap-2">
                <span className="w-4 h-4 border-2 border-zinc-900 border-t-transparent rounded-full animate-spin" />
                Saving
              </span>
            ) : (
              "Save changes"
            )}
          </button>
          {saved && (
            <span className="text-sm text-emerald-400">Saved</span>
          )}
        </div>
      </form>
    </div>
  );
}

/* ── Notification Preferences ── */

function NotificationSection({ supabase }: { supabase: any }) {
  const [settings, setSettings] = useState<NotificationSettings>({
    notify_quota_warning: true,
    notify_quota_exceeded: true,
    notify_weekly_digest: false,
  });
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const fetchSettings = useCallback(async () => {
    try {
      const {
        data: { session },
      } = await supabase.auth.getSession();
      const res = await fetch("/api/user/settings", {
        headers: { Authorization: `Bearer ${session?.access_token}` },
      });
      if (res.ok) {
        const data = await res.json();
        setSettings({
          notify_quota_warning: data.notify_quota_warning ?? true,
          notify_quota_exceeded: data.notify_quota_exceeded ?? true,
          notify_weekly_digest: data.notify_weekly_digest ?? false,
        });
      }
    } catch {
      // Use defaults on error
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchSettings();
  }, [fetchSettings]);

  async function updateSetting(key: keyof NotificationSettings, value: boolean) {
    const updated = { ...settings, [key]: value };
    setSettings(updated);
    setSaving(true);
    setError("");

    try {
      const {
        data: { session },
      } = await supabase.auth.getSession();
      const res = await fetch("/api/user/settings", {
        method: "PATCH",
        headers: {
          Authorization: `Bearer ${session?.access_token}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ [key]: value }),
      });
      if (!res.ok) {
        setError("Failed to update setting");
        setSettings(settings); // revert
      }
    } catch {
      setError("Failed to update setting");
      setSettings(settings); // revert
    } finally {
      setSaving(false);
    }
  }

  const toggles: { key: keyof NotificationSettings; label: string; description: string }[] = [
    {
      key: "notify_quota_warning",
      label: "Quota warning alerts",
      description: "Get notified when you reach 80% of your usage quota",
    },
    {
      key: "notify_quota_exceeded",
      label: "Quota exceeded alerts",
      description: "Get notified when your usage quota is exceeded",
    },
    {
      key: "notify_weekly_digest",
      label: "Weekly usage digest",
      description: "Receive a weekly summary of your API usage",
    },
  ];

  return (
    <div className="rounded-2xl border border-zinc-800 bg-zinc-900/60 p-6">
      <h2 className="text-lg font-semibold text-zinc-100 mb-4">
        Notifications
      </h2>

      {loading ? (
        <div className="flex justify-center py-6">
          <div className="w-5 h-5 border-2 border-amber-400 border-t-transparent rounded-full animate-spin" />
        </div>
      ) : (
        <div className="space-y-4">
          {toggles.map((t) => (
            <label
              key={t.key}
              className="flex items-center justify-between gap-4 cursor-pointer group"
            >
              <div>
                <p className="text-sm font-medium text-zinc-200 group-hover:text-zinc-100 transition-colors">
                  {t.label}
                </p>
                <p className="text-xs text-zinc-500">{t.description}</p>
              </div>
              <input
                type="checkbox"
                checked={settings[t.key]}
                onChange={(e) => updateSetting(t.key, e.target.checked)}
                disabled={saving}
                className="w-5 h-5 rounded accent-amber-500 cursor-pointer"
              />
            </label>
          ))}
          {error && (
            <div className="rounded-lg bg-red-500/10 border border-red-500/20 px-4 py-2.5 text-sm text-red-400">
              {error}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

/* ── Webhooks Section ── */

function WebhooksSection({ supabase }: { supabase: any }) {
  const [webhooks, setWebhooks] = useState<Webhook[]>([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [error, setError] = useState("");
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [logs, setLogs] = useState<Record<string, WebhookDelivery[]>>({});
  const [logsLoading, setLogsLoading] = useState<Record<string, boolean>>({});
  const [testStatus, setTestStatus] = useState<Record<string, "loading" | "success" | "error">>({});
  const [retrying, setRetrying] = useState<Record<string, boolean>>({});

  const getHeaders = useCallback(async () => {
    const {
      data: { session },
    } = await supabase.auth.getSession();
    return {
      Authorization: `Bearer ${session?.access_token}`,
      "Content-Type": "application/json",
    };
  }, []);

  const fetchWebhooks = useCallback(async () => {
    try {
      const headers = await getHeaders();
      const res = await fetch("/api/user/webhooks", { headers });
      if (res.ok) {
        const data = await res.json();
        setWebhooks(data.webhooks || data || []);
      }
    } catch {
      // ignore
    } finally {
      setLoading(false);
    }
  }, [getHeaders]);

  useEffect(() => {
    fetchWebhooks();
  }, [fetchWebhooks]);

  async function toggleWebhook(id: string, active: boolean) {
    const headers = await getHeaders();
    const res = await fetch(`/api/user/webhooks/${id}`, {
      method: "PATCH",
      headers,
      body: JSON.stringify({ active }),
    });
    if (res.ok) {
      setWebhooks((prev) =>
        prev.map((w) => (w.id === id ? { ...w, active } : w))
      );
    }
  }

  async function deleteWebhook(id: string) {
    if (!confirm("Delete this webhook?")) return;
    const headers = await getHeaders();
    const res = await fetch(`/api/user/webhooks/${id}`, {
      method: "DELETE",
      headers,
    });
    if (res.ok) {
      setWebhooks((prev) => prev.filter((w) => w.id !== id));
    }
  }

  async function testWebhook(id: string) {
    setTestStatus((prev) => ({ ...prev, [id]: "loading" }));
    try {
      const headers = await getHeaders();
      const res = await fetch(`/api/user/webhooks/${id}/test`, {
        method: "POST",
        headers,
      });
      setTestStatus((prev) => ({ ...prev, [id]: res.ok ? "success" : "error" }));
    } catch {
      setTestStatus((prev) => ({ ...prev, [id]: "error" }));
    }
    setTimeout(() => {
      setTestStatus((prev) => {
        const next = { ...prev };
        delete next[id];
        return next;
      });
    }, 3000);
  }

  async function fetchLogs(id: string) {
    setLogsLoading((prev) => ({ ...prev, [id]: true }));
    try {
      const headers = await getHeaders();
      const res = await fetch(`/api/user/webhooks/${id}/logs`, { headers });
      if (res.ok) {
        const data = await res.json();
        setLogs((prev) => ({ ...prev, [id]: data.deliveries || data || [] }));
      }
    } catch {
      // ignore
    } finally {
      setLogsLoading((prev) => ({ ...prev, [id]: false }));
    }
  }

  async function retryDelivery(webhookId: string, logId: string) {
    setRetrying((prev) => ({ ...prev, [logId]: true }));
    try {
      const headers = await getHeaders();
      const res = await fetch(`/api/user/webhooks/${webhookId}/retry/${logId}`, {
        method: "POST",
        headers,
      });
      if (res.ok) {
        await fetchLogs(webhookId);
      }
    } catch {
      // ignore
    } finally {
      setRetrying((prev) => ({ ...prev, [logId]: false }));
    }
  }

  function toggleExpand(id: string) {
    if (expandedId === id) {
      setExpandedId(null);
    } else {
      setExpandedId(id);
      if (!logs[id]) {
        fetchLogs(id);
      }
    }
  }

  return (
    <div className="rounded-2xl border border-zinc-800 bg-zinc-900/60 p-6">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-lg font-semibold text-zinc-100">Webhooks</h2>
        <button
          onClick={() => setShowForm(!showForm)}
          className="text-sm text-amber-400 hover:text-amber-300 transition-colors"
        >
          {showForm ? "Cancel" : "+ Add webhook"}
        </button>
      </div>

      {showForm && (
        <WebhookForm
          supabase={supabase}
          getHeaders={getHeaders}
          onCreated={(webhook) => {
            setWebhooks((prev) => [webhook, ...prev]);
            setShowForm(false);
          }}
        />
      )}

      {loading ? (
        <div className="flex justify-center py-6">
          <div className="w-5 h-5 border-2 border-amber-400 border-t-transparent rounded-full animate-spin" />
        </div>
      ) : webhooks.length === 0 ? (
        <p className="text-sm text-zinc-500 text-center py-6">
          No webhooks configured. Add one to receive event notifications.
        </p>
      ) : (
        <div className="space-y-3">
          {webhooks.map((w) => (
            <div
              key={w.id}
              className="rounded-xl border border-zinc-800 bg-zinc-900/40 px-5 py-3"
            >
              <div
                className="flex items-center justify-between gap-4 cursor-pointer"
                onClick={() => toggleExpand(w.id)}
              >
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-mono text-zinc-200 truncate">
                    {w.url}
                  </p>
                  <div className="flex items-center gap-3 mt-1 flex-wrap">
                    <span
                      className={`text-[10px] px-1.5 py-0.5 rounded border ${
                        w.active
                          ? "bg-emerald-500/10 text-emerald-400 border-emerald-500/20"
                          : "bg-zinc-800 text-zinc-500 border-zinc-700"
                      }`}
                    >
                      {w.active ? "active" : "inactive"}
                    </span>
                    {w.events.map((ev) => (
                      <span
                        key={ev}
                        className="text-[10px] px-1.5 py-0.5 rounded bg-zinc-800 text-zinc-400 border border-zinc-700"
                      >
                        {ev}
                      </span>
                    ))}
                    {w.last_triggered_at && (
                      <>
                        <span className="text-xs text-zinc-600">&middot;</span>
                        <span className="text-xs text-zinc-500">
                          last triggered{" "}
                          {new Date(w.last_triggered_at).toLocaleDateString()}
                        </span>
                      </>
                    )}
                    {w.failure_count > 0 && (
                      <>
                        <span className="text-xs text-zinc-600">&middot;</span>
                        <span className="text-xs text-red-400">
                          {w.failure_count} failure
                          {w.failure_count !== 1 ? "s" : ""}
                        </span>
                      </>
                    )}
                  </div>
                </div>
                <div className="flex items-center gap-2 flex-shrink-0">
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      testWebhook(w.id);
                    }}
                    disabled={testStatus[w.id] === "loading"}
                    className="text-xs text-zinc-400 hover:text-amber-400 transition-colors px-2 py-1 flex items-center gap-1"
                  >
                    {testStatus[w.id] === "loading" ? (
                      <span className="w-3 h-3 border border-zinc-400 border-t-transparent rounded-full animate-spin" />
                    ) : testStatus[w.id] === "success" ? (
                      <svg className="w-3 h-3 text-emerald-400" fill="none" viewBox="0 0 24 24" strokeWidth={2.5} stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" d="M4.5 12.75l6 6 9-13.5" />
                      </svg>
                    ) : testStatus[w.id] === "error" ? (
                      <svg className="w-3 h-3 text-red-400" fill="none" viewBox="0 0 24 24" strokeWidth={2.5} stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                      </svg>
                    ) : (
                      "Test"
                    )}
                  </button>
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      toggleWebhook(w.id, !w.active);
                    }}
                    className="text-xs text-zinc-400 hover:text-amber-400 transition-colors px-2 py-1"
                  >
                    {w.active ? "Disable" : "Enable"}
                  </button>
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      deleteWebhook(w.id);
                    }}
                    className="text-xs text-zinc-500 hover:text-red-400 transition-colors px-2 py-1"
                  >
                    Delete
                  </button>
                  <svg
                    className={`w-4 h-4 text-zinc-500 transition-transform ${expandedId === w.id ? "rotate-180" : ""}`}
                    fill="none"
                    viewBox="0 0 24 24"
                    strokeWidth={2}
                    stroke="currentColor"
                  >
                    <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 8.25l-7.5 7.5-7.5-7.5" />
                  </svg>
                </div>
              </div>

              {/* Delivery logs */}
              {expandedId === w.id && (
                <div className="mt-3 pt-3 border-t border-zinc-800">
                  <h4 className="text-xs font-medium text-zinc-400 mb-2">
                    Delivery logs
                  </h4>
                  {logsLoading[w.id] ? (
                    <div className="flex justify-center py-4">
                      <div className="w-4 h-4 border-2 border-amber-400 border-t-transparent rounded-full animate-spin" />
                    </div>
                  ) : !logs[w.id] || logs[w.id].length === 0 ? (
                    <p className="text-xs text-zinc-500 text-center py-4">
                      No deliveries yet
                    </p>
                  ) : (
                    <div className="space-y-1.5 max-h-64 overflow-y-auto">
                      {logs[w.id].map((d) => (
                        <div
                          key={d.id}
                          className="flex items-center justify-between gap-3 rounded-lg bg-zinc-800/40 px-3 py-2"
                        >
                          <div className="flex items-center gap-3 min-w-0 flex-1">
                            <span className="text-[10px] text-zinc-500 whitespace-nowrap">
                              {new Date(d.created_at).toLocaleString()}
                            </span>
                            <span className="text-[10px] px-1.5 py-0.5 rounded bg-zinc-800 text-zinc-400 border border-zinc-700">
                              {d.event}
                            </span>
                            <span
                              className={`text-xs font-mono ${
                                d.status_code >= 200 && d.status_code < 300
                                  ? "text-emerald-400"
                                  : d.status_code >= 400 && d.status_code < 500
                                  ? "text-amber-400"
                                  : "text-red-400"
                              }`}
                            >
                              {d.status_code}
                            </span>
                            <span className="text-[10px] text-zinc-500">
                              {d.response_time_ms}ms
                            </span>
                            {d.error && (
                              <span className="text-[10px] text-red-400 truncate">
                                {d.error}
                              </span>
                            )}
                          </div>
                          {!d.success && (
                            <button
                              onClick={(e) => {
                                e.stopPropagation();
                                retryDelivery(w.id, d.id);
                              }}
                              disabled={retrying[d.id]}
                              className="text-xs text-zinc-400 hover:text-amber-400 transition-colors px-2 py-0.5 flex-shrink-0"
                            >
                              {retrying[d.id] ? (
                                <span className="w-3 h-3 border border-zinc-400 border-t-transparent rounded-full animate-spin inline-block" />
                              ) : (
                                "Retry"
                              )}
                            </button>
                          )}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {error && (
        <div className="rounded-lg bg-red-500/10 border border-red-500/20 px-4 py-2.5 text-sm text-red-400 mt-3">
          {error}
        </div>
      )}
    </div>
  );
}

/* ── Webhook Form ── */

function WebhookForm({
  supabase,
  getHeaders,
  onCreated,
}: {
  supabase: any;
  getHeaders: () => Promise<Record<string, string>>;
  onCreated: (webhook: Webhook) => void;
}) {
  const [url, setUrl] = useState("");
  const [secret, setSecret] = useState("");
  const [events, setEvents] = useState<string[]>([]);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState("");

  function toggleEvent(event: string) {
    setEvents((prev) =>
      prev.includes(event) ? prev.filter((e) => e !== event) : [...prev, event]
    );
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (events.length === 0) {
      setError("Select at least one event");
      return;
    }
    setCreating(true);
    setError("");

    try {
      const headers = await getHeaders();
      const body: Record<string, any> = { url, events };
      if (secret.trim()) body.secret = secret;

      const res = await fetch("/api/user/webhooks", {
        method: "POST",
        headers,
        body: JSON.stringify(body),
      });

      if (res.ok) {
        const data = await res.json();
        onCreated(data);
        setUrl("");
        setSecret("");
        setEvents([]);
      } else {
        const data = await res.json().catch(() => null);
        setError(data?.error || "Failed to create webhook");
      }
    } catch {
      setError("Failed to create webhook");
    } finally {
      setCreating(false);
    }
  }

  return (
    <form
      onSubmit={handleSubmit}
      className="rounded-xl border border-zinc-700/50 bg-zinc-800/30 p-4 mb-4 space-y-4"
    >
      <div>
        <label className="block text-sm text-zinc-400 mb-1.5">
          Endpoint URL
        </label>
        <input
          type="url"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          placeholder="https://example.com/webhook"
          required
          className="w-full px-4 py-2.5 rounded-lg bg-zinc-800/50 border border-zinc-700/50 text-zinc-100 placeholder:text-zinc-500 text-sm focus:outline-none focus:ring-2 focus:ring-amber-400/50"
        />
      </div>

      <div>
        <label className="block text-sm text-zinc-400 mb-1.5">Events</label>
        <div className="grid grid-cols-2 gap-2">
          {WEBHOOK_EVENTS.map((ev) => (
            <label
              key={ev.value}
              className="flex items-center gap-2 cursor-pointer"
            >
              <input
                type="checkbox"
                checked={events.includes(ev.value)}
                onChange={() => toggleEvent(ev.value)}
                className="w-4 h-4 rounded accent-amber-500 cursor-pointer"
              />
              <span className="text-sm text-zinc-300">{ev.label}</span>
            </label>
          ))}
        </div>
      </div>

      <div>
        <label className="block text-sm text-zinc-400 mb-1.5">
          Secret{" "}
          <span className="text-zinc-600">(optional)</span>
        </label>
        <input
          type="text"
          value={secret}
          onChange={(e) => setSecret(e.target.value)}
          placeholder="whsec_..."
          className="w-full px-4 py-2.5 rounded-lg bg-zinc-800/50 border border-zinc-700/50 text-zinc-100 placeholder:text-zinc-500 text-sm focus:outline-none focus:ring-2 focus:ring-amber-400/50"
        />
      </div>

      {error && (
        <div className="rounded-lg bg-red-500/10 border border-red-500/20 px-4 py-2.5 text-sm text-red-400">
          {error}
        </div>
      )}

      <button
        type="submit"
        disabled={creating || !url.trim()}
        className="px-5 py-2.5 rounded-lg bg-amber-500 text-zinc-950 font-semibold text-sm hover:bg-amber-400 disabled:opacity-50 transition-colors"
      >
        {creating ? (
          <span className="flex items-center gap-2">
            <span className="w-4 h-4 border-2 border-zinc-900 border-t-transparent rounded-full animate-spin" />
            Creating
          </span>
        ) : (
          "Add webhook"
        )}
      </button>
    </form>
  );
}

/* ── Danger Zone ── */

function DangerZone({ supabase }: { supabase: any }) {
  const [showConfirm, setShowConfirm] = useState(false);
  const [confirmText, setConfirmText] = useState("");
  const [deleting, setDeleting] = useState(false);
  const [error, setError] = useState("");

  async function handleDelete() {
    if (confirmText !== "DELETE") return;
    setDeleting(true);
    setError("");

    try {
      const {
        data: { session },
      } = await supabase.auth.getSession();
      const res = await fetch("/api/user/account", {
        method: "DELETE",
        headers: {
          Authorization: `Bearer ${session?.access_token}`,
        },
      });

      if (res.ok) {
        await supabase.auth.signOut();
        window.location.href = "/";
      } else {
        const data = await res.json().catch(() => null);
        setError(data?.error || "Failed to delete account");
      }
    } catch {
      setError("Failed to delete account");
    } finally {
      setDeleting(false);
    }
  }

  return (
    <div className="rounded-2xl border border-red-500/20 bg-zinc-900/60 p-6">
      <h2 className="text-lg font-semibold text-red-400 mb-2">Danger zone</h2>
      <p className="text-sm text-zinc-400 mb-4">
        Permanently delete your account and all associated data, including API
        keys, usage history, and webhooks. This action cannot be undone.
      </p>

      {!showConfirm ? (
        <button
          onClick={() => setShowConfirm(true)}
          className="px-4 py-2.5 rounded-lg bg-red-500/10 border border-red-500/20 text-red-400 text-sm hover:bg-red-500/20 transition-colors"
        >
          Delete account
        </button>
      ) : (
        <div className="rounded-xl border border-red-500/20 bg-red-500/5 p-4 space-y-4">
          <p className="text-sm text-zinc-300">
            Type <span className="font-mono text-red-400">DELETE</span> to
            confirm account deletion.
          </p>
          <input
            type="text"
            value={confirmText}
            onChange={(e) => setConfirmText(e.target.value)}
            placeholder="Type DELETE to confirm"
            className="w-full px-4 py-2.5 rounded-lg bg-zinc-800/50 border border-zinc-700/50 text-zinc-100 placeholder:text-zinc-500 text-sm focus:outline-none focus:ring-2 focus:ring-red-400/50"
          />

          {error && (
            <div className="rounded-lg bg-red-500/10 border border-red-500/20 px-4 py-2.5 text-sm text-red-400">
              {error}
            </div>
          )}

          <div className="flex items-center gap-3">
            <button
              onClick={handleDelete}
              disabled={confirmText !== "DELETE" || deleting}
              className="px-4 py-2.5 rounded-lg bg-red-500 text-white font-semibold text-sm hover:bg-red-400 disabled:opacity-50 transition-colors"
            >
              {deleting ? (
                <span className="flex items-center gap-2">
                  <span className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
                  Deleting
                </span>
              ) : (
                "Permanently delete my account"
              )}
            </button>
            <button
              onClick={() => {
                setShowConfirm(false);
                setConfirmText("");
                setError("");
              }}
              className="text-sm text-zinc-400 hover:text-zinc-200 transition-colors px-3 py-2"
            >
              Cancel
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
