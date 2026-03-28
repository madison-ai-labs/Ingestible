"use client";

import { useEffect, useState, useCallback, Component, ReactNode } from "react";
import type { User } from "@supabase/supabase-js";
import { getSupabase } from "@/lib/supabase-browser";

class ErrorBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  constructor(props: { children: ReactNode }) {
    super(props);
    this.state = { error: null };
  }
  static getDerivedStateFromError(error: Error) {
    return { error };
  }
  render() {
    if (this.state.error) {
      return (
        <div className="max-w-2xl mx-auto px-6 py-12 text-center">
          <h2 className="text-xl font-bold text-red-400 mb-4">Something went wrong</h2>
          <pre className="text-left text-xs text-zinc-400 bg-zinc-900 border border-zinc-800 rounded-lg p-4 overflow-auto max-h-64 mb-4">
            {this.state.error.message}
            {"\n\n"}
            {this.state.error.stack}
          </pre>
          <button onClick={() => window.location.reload()} className="px-4 py-2 rounded-lg bg-amber-500 text-zinc-950 text-sm font-semibold">
            Reload
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}

interface ApiKey {
  id: string;
  key: string;
  label: string;
  created_at: string;
  last_used_at: string | null;
  revoked: boolean;
  requests_count: number;
  tokens_used: number;
  documents_ingested: number;
  searches_performed: number;
  errors_count: number;
  bytes_uploaded: number;
}

export default function DashboardPage() {
  return (
    <ErrorBoundary>
      <DashboardContent />
    </ErrorBoundary>
  );
}

function DashboardContent() {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const supabase = getSupabase();
    supabase.auth.getUser().then(({ data }: any) => {
      setUser(data.user);
      setLoading(false);
    });

    const { data: { subscription } } = supabase.auth.onAuthStateChange((_event: any, session: any) => {
      setUser(session?.user ?? null);
    });

    return () => subscription.unsubscribe();
  }, []);

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <div className="w-6 h-6 border-2 border-amber-400 border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  if (!user) return <AuthPage />;

  return <UserDashboard user={user} />;
}

/* ── Auth Page ── */

function AuthPage() {
  const [mode, setMode] = useState<"login" | "signup">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const supabase = getSupabase();

  async function handleGitHub() {
    await supabase.auth.signInWithOAuth({
      provider: "github",
      options: { redirectTo: `${window.location.origin}/auth/callback?next=/dashboard` },
    });
  }

  async function handleEmail(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setMessage("");
    setSubmitting(true);

    if (mode === "signup") {
      const { error } = await supabase.auth.signUp({
        email,
        password,
        options: { emailRedirectTo: `${window.location.origin}/auth/callback?next=/dashboard` },
      });
      if (error) setError(error.message);
      else setMessage("Check your email for a confirmation link.");
    } else {
      const { error } = await supabase.auth.signInWithPassword({ email, password });
      if (error) setError(error.message);
    }

    setSubmitting(false);
  }

  return (
    <div className="flex items-center justify-center min-h-[70vh] px-4">
      <div className="w-full max-w-sm">
        <div className="text-center mb-8">
          <h1 className="text-2xl font-bold text-zinc-100 mb-2">
            {mode === "login" ? "Sign in" : "Create account"}
          </h1>
          <p className="text-sm text-zinc-400">
            {mode === "login"
              ? "Access your Ingestible dashboard"
              : "Get started with Ingestible"}
          </p>
        </div>

        <div className="rounded-2xl border border-zinc-800 bg-zinc-900/60 p-6 space-y-5">
          {/* GitHub OAuth */}
          <button
            onClick={handleGitHub}
            className="w-full flex items-center justify-center gap-2.5 px-4 py-2.5 rounded-lg border border-zinc-700 text-zinc-200 text-sm font-medium hover:bg-zinc-800 transition-colors"
          >
            <svg className="w-5 h-5" fill="currentColor" viewBox="0 0 24 24">
              <path fillRule="evenodd" d="M12 2C6.477 2 2 6.484 2 12.017c0 4.425 2.865 8.18 6.839 9.504.5.092.682-.217.682-.483 0-.237-.008-.868-.013-1.703-2.782.605-3.369-1.343-3.369-1.343-.454-1.158-1.11-1.466-1.11-1.466-.908-.62.069-.608.069-.608 1.003.07 1.531 1.032 1.531 1.032.892 1.53 2.341 1.088 2.91.832.092-.647.35-1.088.636-1.338-2.22-.253-4.555-1.113-4.555-4.951 0-1.093.39-1.988 1.029-2.688-.103-.253-.446-1.272.098-2.65 0 0 .84-.27 2.75 1.026A9.564 9.564 0 0112 6.844c.85.004 1.705.115 2.504.337 1.909-1.296 2.747-1.027 2.747-1.027.546 1.379.202 2.398.1 2.651.64.7 1.028 1.595 1.028 2.688 0 3.848-2.339 4.695-4.566 4.943.359.309.678.92.678 1.855 0 1.338-.012 2.419-.012 2.747 0 .268.18.58.688.482A10.019 10.019 0 0022 12.017C22 6.484 17.522 2 12 2z" clipRule="evenodd" />
            </svg>
            Continue with GitHub
          </button>

          {/* Divider */}
          <div className="flex items-center gap-3">
            <div className="flex-1 h-px bg-zinc-800" />
            <span className="text-xs text-zinc-500">or</span>
            <div className="flex-1 h-px bg-zinc-800" />
          </div>

          {/* Email form */}
          <form onSubmit={handleEmail} className="space-y-4">
            <div>
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="Email"
                required
                className="w-full px-4 py-2.5 rounded-lg bg-zinc-800/50 border border-zinc-700/50 text-zinc-100 placeholder:text-zinc-500 text-sm focus:outline-none focus:ring-2 focus:ring-amber-400/50"
              />
            </div>
            <div>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="Password"
                required
                minLength={6}
                className="w-full px-4 py-2.5 rounded-lg bg-zinc-800/50 border border-zinc-700/50 text-zinc-100 placeholder:text-zinc-500 text-sm focus:outline-none focus:ring-2 focus:ring-amber-400/50"
              />
            </div>

            {error && (
              <div className="rounded-lg bg-red-500/10 border border-red-500/20 px-4 py-2.5 text-sm text-red-400">
                {error}
              </div>
            )}
            {message && (
              <div className="rounded-lg bg-emerald-500/10 border border-emerald-500/20 px-4 py-2.5 text-sm text-emerald-400">
                {message}
              </div>
            )}

            <button
              type="submit"
              disabled={submitting}
              className="w-full px-4 py-2.5 rounded-lg bg-amber-500 text-zinc-950 font-semibold text-sm hover:bg-amber-400 disabled:opacity-50 transition-colors"
            >
              {submitting ? "..." : mode === "login" ? "Sign in" : "Create account"}
            </button>
          </form>

          <p className="text-xs text-zinc-500 text-center">
            {mode === "login" ? (
              <>
                No account?{" "}
                <button onClick={() => { setMode("signup"); setError(""); setMessage(""); }} className="text-amber-400 hover:underline">
                  Sign up
                </button>
              </>
            ) : (
              <>
                Already have an account?{" "}
                <button onClick={() => { setMode("login"); setError(""); setMessage(""); }} className="text-amber-400 hover:underline">
                  Sign in
                </button>
              </>
            )}
          </p>
        </div>
      </div>
    </div>
  );
}

/* ── Types ── */

type Tab = "overview" | "keys" | "playground" | "settings";

interface UserSettings {
  tier: string;
  tier_description?: string;
  limits: {
    requests_per_day: number;
    max_documents: number;
    max_keys: number;
  };
  usage: {
    requests_today: number;
    documents: number;
    keys: number;
  };
}

interface UsageDay {
  date: string;
  requests: number;
}

interface ActivityItem {
  type: "key_created" | "document_ingested" | "search_performed" | "key_revoked";
  label: string;
  timestamp: string;
}

interface InsightMessage {
  type: "warning" | "error" | "info" | "success";
  message: string;
  action?: string;
  actionTab?: Tab;
}

/* ── Helper Functions ── */

function timeAgo(date: string): string {
  const seconds = Math.floor((Date.now() - new Date(date).getTime()) / 1000);
  if (seconds < 60) return "just now";
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  if (seconds < 604800) return `${Math.floor(seconds / 86400)}d ago`;
  return new Date(date).toLocaleDateString();
}

function calculateHealthScore(
  settings: UserSettings | null,
  keys: ApiKey[],
  usage: UsageDay[],
): number {
  let score = 100;

  // Quota usage penalty (up to -30)
  if (settings?.usage && settings?.limits) {
    const quotaPct = settings.limits.requests_per_day > 0
      ? settings.usage.requests_today / settings.limits.requests_per_day
      : 0;
    score -= Math.min(quotaPct * 30, 30);
  }

  // Error rate penalty (up to -25)
  const totalRequests = keys.reduce((s, k) => s + k.requests_count, 0);
  const totalErrors = keys.reduce((s, k) => s + k.errors_count, 0);
  if (totalRequests > 0) {
    const errorRate = totalErrors / totalRequests;
    score -= Math.min(errorRate * 500, 25);
  }

  // Activity recency penalty (up to -25)
  const lastUsedDates = keys
    .filter((k) => k.last_used_at)
    .map((k) => new Date(k.last_used_at!).getTime());
  if (lastUsedDates.length > 0) {
    const mostRecent = Math.max(...lastUsedDates);
    const daysSince = (Date.now() - mostRecent) / (1000 * 60 * 60 * 24);
    score -= Math.min(daysSince * 2, 25);
  } else if (keys.length > 0) {
    score -= 15;
  }

  // Document count bonus/penalty (up to -20)
  if (settings?.usage && settings?.limits) {
    const docPct = settings.limits.max_documents > 0
      ? settings.usage.documents / settings.limits.max_documents
      : 0;
    score -= Math.min(docPct * 20, 20);
  }

  return Math.max(0, Math.min(100, Math.round(score)));
}

function getSmartInsight(
  settings: UserSettings | null,
  keys: ApiKey[],
  usage: UsageDay[],
): InsightMessage {
  // Check quota > 80%
  if (settings?.usage && settings?.limits) {
    const quotaPct = settings.limits.requests_per_day > 0
      ? (settings.usage.requests_today / settings.limits.requests_per_day) * 100
      : 0;
    if (quotaPct >= 80) {
      return {
        type: "warning",
        message: `You're at ${Math.round(quotaPct)}% of your daily request limit. Consider upgrading to Premium.`,
        action: "View Plans",
        actionTab: "settings",
      };
    }
  }

  // Check error rate > 5%
  const totalRequests = keys.reduce((s, k) => s + k.requests_count, 0);
  const totalErrors = keys.reduce((s, k) => s + k.errors_count, 0);
  if (totalRequests > 0 && totalErrors / totalRequests > 0.05) {
    return {
      type: "error",
      message: `Your error rate is ${((totalErrors / totalRequests) * 100).toFixed(1)}%. Check your API integration.`,
      action: "View Keys",
      actionTab: "keys",
    };
  }

  // Check no activity in 7+ days
  const lastUsedDates = keys
    .filter((k) => k.last_used_at)
    .map((k) => new Date(k.last_used_at!).getTime());
  if (lastUsedDates.length > 0) {
    const mostRecent = Math.max(...lastUsedDates);
    const daysSince = (Date.now() - mostRecent) / (1000 * 60 * 60 * 24);
    if (daysSince >= 7) {
      return {
        type: "info",
        message: "Your API has been idle for over a week. Need help getting started?",
        action: "Open Playground",
        actionTab: "playground",
      };
    }
  }

  // Documents but no searches
  const totalDocuments = keys.reduce((s, k) => s + k.documents_ingested, 0);
  const totalSearches = keys.reduce((s, k) => s + k.searches_performed, 0);
  if (totalDocuments > 0 && totalSearches === 0) {
    return {
      type: "info",
      message: "You have documents ingested but haven't searched yet. Try the Playground.",
      action: "Open Playground",
      actionTab: "playground",
    };
  }

  // All healthy
  const requestsToday = settings?.usage?.requests_today ?? 0;
  return {
    type: "success",
    message: `All systems nominal. ${requestsToday.toLocaleString()} request${requestsToday !== 1 ? "s" : ""} processed today.`,
  };
}

function buildRecentActivity(keys: ApiKey[]): ActivityItem[] {
  const items: ActivityItem[] = [];

  for (const k of keys) {
    items.push({
      type: "key_created",
      label: `API key "${k.label}" created`,
      timestamp: k.created_at,
    });

    if (k.revoked) {
      items.push({
        type: "key_revoked",
        label: `API key "${k.label}" revoked`,
        timestamp: k.created_at,
      });
    }

    if (k.last_used_at) {
      if (k.documents_ingested > 0) {
        items.push({
          type: "document_ingested",
          label: `${k.documents_ingested} document${k.documents_ingested !== 1 ? "s" : ""} ingested via "${k.label}"`,
          timestamp: k.last_used_at,
        });
      }
      if (k.searches_performed > 0) {
        items.push({
          type: "search_performed",
          label: `${k.searches_performed} search${k.searches_performed !== 1 ? "es" : ""} via "${k.label}"`,
          timestamp: k.last_used_at,
        });
      }
    }
  }

  items.sort((a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime());
  return items.slice(0, 5);
}

/* ── Sub-components ── */

function QuotaBar({ label, current, max, showProjection }: { label: string; current: number; max: number; showProjection?: boolean }) {
  const pct = max > 0 ? Math.min((current / max) * 100, 100) : 0;
  const color = pct >= 100 ? "bg-red-500" : pct >= 80 ? "bg-orange-500" : "bg-amber-400";

  // Projection: estimate when limit is hit based on current usage rate
  let projection: string | null = null;
  if (showProjection && current > 0 && current < max) {
    const now = new Date();
    const hoursPassed = now.getHours() + now.getMinutes() / 60 || 0.5;
    const ratePerHour = current / hoursPassed;
    const hoursToLimit = (max - current) / ratePerHour;
    if (hoursToLimit < 24 - hoursPassed) {
      const hitTime = new Date(now.getTime() + hoursToLimit * 60 * 60 * 1000);
      projection = `At this rate, you'll hit your limit by ${hitTime.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" })}`;
    }
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-1">
        <span className="text-xs text-zinc-400">{label}</span>
        <div className="flex items-center gap-2">
          <span className="text-xs font-mono text-zinc-300">{current.toLocaleString()} / {max.toLocaleString()}</span>
          <span className="text-xs font-mono text-zinc-500">{Math.round(pct)}%</span>
        </div>
      </div>
      <div className="h-2 rounded-full bg-zinc-800 overflow-hidden">
        <div className={`h-full rounded-full ${color} transition-all`} style={{ width: `${pct}%` }} />
      </div>
      {projection && (
        <p className="text-[11px] text-zinc-500 mt-1">{projection}</p>
      )}
    </div>
  );
}

function HealthScoreRing({ score }: { score: number }) {
  const radius = 44;
  const circumference = 2 * Math.PI * radius;
  const progress = (score / 100) * circumference;
  const color = score >= 70 ? "stroke-emerald-400" : score >= 40 ? "stroke-amber-400" : "stroke-red-400";
  const bgColor = score >= 70 ? "text-emerald-400" : score >= 40 ? "text-amber-400" : "text-red-400";

  return (
    <div className="rounded-xl border border-zinc-800 bg-zinc-900/40 p-5 flex items-center gap-5">
      <div className="relative w-24 h-24 flex-shrink-0">
        <svg className="w-24 h-24 -rotate-90" viewBox="0 0 100 100">
          <circle cx="50" cy="50" r={radius} fill="none" stroke="currentColor" strokeWidth="6" className="text-zinc-800" />
          <circle
            cx="50" cy="50" r={radius} fill="none" strokeWidth="6"
            className={color}
            strokeLinecap="round"
            strokeDasharray={circumference}
            strokeDashoffset={circumference - progress}
            style={{ transition: "stroke-dashoffset 0.6s ease" }}
          />
        </svg>
        <div className="absolute inset-0 flex items-center justify-center">
          <span className={`text-2xl font-bold font-mono ${bgColor}`}>{score}</span>
        </div>
      </div>
      <div>
        <h3 className="text-sm font-semibold text-zinc-200">Health Score</h3>
        <p className="text-xs text-zinc-500 mt-1">
          {score >= 70
            ? "Your account is in great shape."
            : score >= 40
              ? "Some metrics need attention."
              : "Several issues require action."}
        </p>
      </div>
    </div>
  );
}

function InsightBanner({ insight, onAction }: { insight: InsightMessage; onAction?: (tab: Tab) => void }) {
  const styles = {
    warning: "border-amber-500/30 bg-amber-500/5 text-amber-400",
    error: "border-red-500/30 bg-red-500/5 text-red-400",
    info: "border-blue-500/30 bg-blue-500/5 text-blue-400",
    success: "border-emerald-500/30 bg-emerald-500/5 text-emerald-400",
  };
  const icons = {
    warning: (
      <svg className="w-5 h-5 flex-shrink-0" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126ZM12 15.75h.007v.008H12v-.008Z" />
      </svg>
    ),
    error: (
      <svg className="w-5 h-5 flex-shrink-0" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m9-.75a9 9 0 1 1-18 0 9 9 0 0 1 18 0Zm-9 3.75h.008v.008H12v-.008Z" />
      </svg>
    ),
    info: (
      <svg className="w-5 h-5 flex-shrink-0" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" d="m11.25 11.25.041-.02a.75.75 0 0 1 1.063.852l-.708 2.836a.75.75 0 0 0 1.063.853l.041-.021M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Zm-9-3.75h.008v.008H12V8.25Z" />
      </svg>
    ),
    success: (
      <svg className="w-5 h-5 flex-shrink-0" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" d="M9 12.75 11.25 15 15 9.75M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z" />
      </svg>
    ),
  };

  return (
    <div className={`rounded-xl border p-4 flex items-center gap-3 ${styles[insight.type]}`}>
      {icons[insight.type]}
      <span className="text-sm flex-1">{insight.message}</span>
      {insight.action && insight.actionTab && onAction && (
        <button
          onClick={() => onAction(insight.actionTab!)}
          className="text-xs font-medium px-3 py-1.5 rounded-lg border border-current/20 hover:bg-white/5 transition-colors flex-shrink-0"
        >
          {insight.action}
        </button>
      )}
    </div>
  );
}

function GettingStartedChecklist({ keys, totalDocs, totalSearches, onNavigate }: {
  keys: ApiKey[];
  totalDocs: number;
  totalSearches: number;
  onNavigate: (tab: Tab) => void;
}) {
  const steps = [
    { done: keys.length > 0, label: "Create your first API key", tab: "keys" as Tab },
    { done: keys.some((k) => k.last_used_at !== null), label: "Connect to your Ingestible instance", tab: "keys" as Tab },
    { done: totalDocs > 0, label: "Ingest your first document", tab: "playground" as Tab },
    { done: totalSearches > 0, label: "Run your first search", tab: "playground" as Tab },
  ];

  const allDone = steps.every((s) => s.done);
  if (allDone) return null;

  const completed = steps.filter((s) => s.done).length;

  return (
    <div className="rounded-xl border border-zinc-800 bg-zinc-900/40 p-5">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-sm font-semibold text-zinc-200">Getting Started</h3>
        <span className="text-xs text-zinc-500">{completed}/{steps.length} completed</span>
      </div>
      <div className="space-y-2.5">
        {steps.map((step, i) => (
          <button
            key={i}
            onClick={() => !step.done && onNavigate(step.tab)}
            className={`flex items-center gap-3 w-full text-left group ${step.done ? "cursor-default" : "cursor-pointer"}`}
          >
            <div className={`w-5 h-5 rounded-full border-2 flex items-center justify-center flex-shrink-0 ${
              step.done
                ? "border-emerald-400 bg-emerald-400/10"
                : "border-zinc-600 group-hover:border-amber-400"
            }`}>
              {step.done && (
                <svg className="w-3 h-3 text-emerald-400" fill="none" viewBox="0 0 24 24" strokeWidth={3} stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M4.5 12.75l6 6 9-13.5" />
                </svg>
              )}
            </div>
            <span className={`text-sm ${step.done ? "text-zinc-500 line-through" : "text-zinc-300 group-hover:text-amber-400"}`}>
              {step.label}
            </span>
          </button>
        ))}
      </div>
    </div>
  );
}

function TrendArrow({ direction }: { direction: "up" | "down" | "flat" }) {
  if (direction === "up") {
    return (
      <svg className="w-3.5 h-3.5 text-emerald-400 inline-block ml-1.5" fill="none" viewBox="0 0 24 24" strokeWidth={2.5} stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" d="M4.5 19.5l15-15m0 0H8.25m11.25 0v11.25" />
      </svg>
    );
  }
  if (direction === "down") {
    return (
      <svg className="w-3.5 h-3.5 text-red-400 inline-block ml-1.5" fill="none" viewBox="0 0 24 24" strokeWidth={2.5} stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" d="M4.5 4.5l15 15m0 0V8.25m0 11.25H8.25" />
      </svg>
    );
  }
  return (
    <svg className="w-3.5 h-3.5 text-zinc-500 inline-block ml-1.5" fill="none" viewBox="0 0 24 24" strokeWidth={2.5} stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" d="M5 12h14" />
    </svg>
  );
}

function StatCard({ label, value, trend }: { label: string; value: string; trend?: "up" | "down" | "flat" }) {
  return (
    <div className="rounded-xl border border-zinc-800 bg-zinc-900/40 p-4">
      <p className="text-xs text-zinc-500 mb-1">{label}</p>
      <div className="flex items-baseline">
        <p className="text-xl font-bold font-mono text-zinc-100">{value}</p>
        {trend && <TrendArrow direction={trend} />}
      </div>
      {trend && (
        <p className="text-[10px] text-zinc-600 mt-0.5">vs yesterday</p>
      )}
    </div>
  );
}

function ActivityFeed({ items }: { items: ActivityItem[] }) {
  if (items.length === 0) {
    return (
      <div className="rounded-xl border border-zinc-800 bg-zinc-900/40 p-5">
        <h3 className="text-sm font-semibold text-zinc-200 mb-3">Recent Activity</h3>
        <p className="text-sm text-zinc-500 text-center py-4">No activity yet.</p>
      </div>
    );
  }

  const dotColors: Record<string, string> = {
    key_created: "bg-amber-400",
    document_ingested: "bg-emerald-400",
    search_performed: "bg-blue-400",
    key_revoked: "bg-red-400",
  };

  return (
    <div className="rounded-xl border border-zinc-800 bg-zinc-900/40 p-5">
      <h3 className="text-sm font-semibold text-zinc-200 mb-3">Recent Activity</h3>
      <div className="space-y-2.5">
        {items.map((item, i) => (
          <div key={i} className="flex items-center gap-3">
            <div className={`w-2 h-2 rounded-full flex-shrink-0 ${dotColors[item.type] || "bg-zinc-500"}`} />
            <span className="text-sm text-zinc-300 flex-1 truncate">{item.label}</span>
            <span className="text-xs text-zinc-600 flex-shrink-0">{timeAgo(item.timestamp)}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function KeyActivityBars({ apiKey }: { apiKey: ApiKey }) {
  // Simulate 7-day activity from the key's aggregate stats
  // In production this would come from a per-day breakdown API
  const total = apiKey.requests_count;
  if (total === 0) return null;

  const bars = Array.from({ length: 7 }, (_, i) => {
    // Distribute requests somewhat randomly but deterministically based on key id
    const seed = apiKey.id.charCodeAt(i % apiKey.id.length) || 1;
    return (seed % 5) + 1;
  });
  const barMax = Math.max(...bars);

  return (
    <div className="flex items-end gap-px h-4 mt-1">
      {bars.map((v, i) => (
        <div
          key={i}
          className="w-1.5 rounded-sm bg-amber-400/40"
          style={{ height: `${(v / barMax) * 100}%` }}
        />
      ))}
    </div>
  );
}

/* ── User Dashboard ── */

function UserDashboard({ user }: { user: User }) {
  const [tab, setTab] = useState<Tab>("overview");
  const [keys, setKeys] = useState<ApiKey[]>([]);
  const [keysLoading, setKeysLoading] = useState(true);
  const [newLabel, setNewLabel] = useState("");
  const [creating, setCreating] = useState(false);
  const [newlyCreated, setNewlyCreated] = useState<{ key: string; label: string } | null>(null);
  const [copied, setCopied] = useState(false);
  const [settings, setSettings] = useState<UserSettings | null>(null);
  const [settingsLoading, setSettingsLoading] = useState(true);
  const [usage, setUsage] = useState<UsageDay[]>([]);
  const [usageLoading, setUsageLoading] = useState(true);
  const supabase = getSupabase();

  // ── Load API keys ──
  const loadKeys = useCallback(async () => {
    setKeysLoading(true);
    try {
      const { data } = await supabase
        .from("api_keys")
        .select("*")
        .order("created_at", { ascending: false });
      setKeys(data || []);
    } catch {
      // graceful fallback
    } finally {
      setKeysLoading(false);
    }
  }, [supabase]);

  useEffect(() => { loadKeys(); }, [loadKeys]);

  // ── Load user settings (tier & limits) ──
  useEffect(() => {
    async function fetchSettings() {
      setSettingsLoading(true);
      try {
        const { data: { session } } = await supabase.auth.getSession();
        if (!session) return;
        const res = await fetch("/api/user/settings", {
          headers: { Authorization: `Bearer ${session.access_token}` },
        });
        if (res.ok) {
          setSettings(await res.json());
        }
      } catch {
        // silently fail — overview will show without quotas
      } finally {
        setSettingsLoading(false);
      }
    }
    fetchSettings();
  }, []);

  // ── Load usage chart data ──
  useEffect(() => {
    async function fetchUsage() {
      setUsageLoading(true);
      try {
        const { data: { session } } = await supabase.auth.getSession();
        if (!session) return;
        const res = await fetch("/api/user/usage?days=14", {
          headers: { Authorization: `Bearer ${session.access_token}` },
        });
        if (res.ok) {
          const json = await res.json();
          setUsage(json.daily || json || []);
        }
      } catch {
        // silently fail
      } finally {
        setUsageLoading(false);
      }
    }
    fetchUsage();
  }, []);

  // ── Key management ──
  async function createKey(e: React.FormEvent) {
    e.preventDefault();
    if (!newLabel.trim()) return;
    setCreating(true);

    const key = "ik_" + Array.from(crypto.getRandomValues(new Uint8Array(32)))
      .map((b) => b.toString(16).padStart(2, "0")).join("");

    const { data, error } = await supabase
      .from("api_keys")
      .insert({ user_id: user.id, key, label: newLabel })
      .select()
      .single();

    if (!error && data) {
      setNewlyCreated({ key, label: newLabel });
      setNewLabel("");
      loadKeys();
    }
    setCreating(false);
  }

  async function revokeKey(id: string) {
    await supabase.from("api_keys").update({ revoked: true }).eq("id", id);
    loadKeys();
  }

  async function reinstateKey(id: string) {
    await supabase.from("api_keys").update({ revoked: false }).eq("id", id);
    loadKeys();
  }

  async function deleteKey(id: string) {
    if (!confirm("Permanently delete this key?")) return;
    await supabase.from("api_keys").delete().eq("id", id);
    loadKeys();
  }

  async function signOut() {
    await supabase.auth.signOut();
  }

  const activeKeys = keys.filter((k) => !k.revoked);
  const revokedKeys = keys.filter((k) => k.revoked);

  // ── Aggregate stats from keys ──
  const totalRequests = keys.reduce((s, k) => s + k.requests_count, 0);
  const totalDocuments = keys.reduce((s, k) => s + k.documents_ingested, 0);
  const totalSearches = keys.reduce((s, k) => s + k.searches_performed, 0);
  const totalTokens = keys.reduce((s, k) => s + k.tokens_used, 0);

  // ── Trend calculation (compare today vs yesterday in usage data) ──
  function getTrend(metricToday: number, metricYesterday: number): "up" | "down" | "flat" {
    if (metricToday > metricYesterday) return "up";
    if (metricToday < metricYesterday) return "down";
    return "flat";
  }

  const todayUsage = usage.length > 0 ? usage[usage.length - 1]?.requests ?? 0 : 0;
  const yesterdayUsage = usage.length > 1 ? usage[usage.length - 2]?.requests ?? 0 : 0;
  const requestsTrend = getTrend(todayUsage, yesterdayUsage);

  // ── Usage chart ──
  const maxUsage = Math.max(...usage.map((d) => d.requests), 1);
  const avgUsage = usage.length > 0 ? usage.reduce((s, d) => s + d.requests, 0) / usage.length : 0;

  // ── Smart insight ──
  const insight = getSmartInsight(settings, keys, usage);

  // ── Health score ──
  const healthScore = calculateHealthScore(settings, keys, usage);

  // ── Recent activity ──
  const recentActivity = buildRecentActivity(keys);

  // ── Determine today's date string for chart highlighting ──
  const todayStr = new Date().toISOString().split("T")[0];

  const tabs: { id: Tab; label: string }[] = [
    { id: "overview", label: "Overview" },
    { id: "keys", label: "API Keys" },
    { id: "playground", label: "Playground" },
    { id: "settings", label: "Settings" },
  ];

  return (
    <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-zinc-100">Dashboard</h1>
          <p className="text-sm text-zinc-500 mt-1">
            {user.email || user.user_metadata?.name || "User"}
          </p>
        </div>
        <button onClick={signOut} className="text-sm text-zinc-400 hover:text-zinc-200 transition-colors px-3 py-1.5 rounded-lg border border-zinc-800 hover:border-zinc-700">
          Sign out
        </button>
      </div>

      {/* Tab navigation */}
      <div className="flex border-b border-zinc-800 mb-8">
        {tabs.map((t) => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={`px-4 py-2.5 text-sm font-medium transition-colors border-b-2 -mb-px ${
              tab === t.id
                ? "text-amber-400 border-amber-400"
                : "text-zinc-500 border-transparent hover:text-zinc-300 hover:border-zinc-700"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* ── Overview Tab ── */}
      {tab === "overview" && (
        <div className="space-y-6">
          {/* Smart Insight Banner */}
          {!settingsLoading && !keysLoading && (
            <InsightBanner insight={insight} onAction={(t) => setTab(t)} />
          )}

          {/* Getting Started Checklist */}
          {!keysLoading && (
            <GettingStartedChecklist
              keys={keys}
              totalDocs={totalDocuments}
              totalSearches={totalSearches}
              onNavigate={(t) => setTab(t)}
            />
          )}

          {/* Health Score + Tier */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            {!settingsLoading && !keysLoading && (
              <HealthScoreRing score={healthScore} />
            )}
            {settings && (
              <div className="rounded-xl border border-zinc-800 bg-zinc-900/40 p-5 flex flex-col justify-center">
                <span className={`text-xs font-semibold px-2.5 py-1 rounded-full self-start ${
                  settings.tier === "premium"
                    ? "bg-amber-400/10 text-amber-400 border border-amber-400/20"
                    : "bg-zinc-700/40 text-zinc-300 border border-zinc-700"
                }`}>
                  {settings.tier}
                </span>
                {settings.tier_description && (
                  <span className="text-sm text-zinc-400 mt-2">{settings.tier_description}</span>
                )}
              </div>
            )}
          </div>

          {/* Stats cards with trends */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
            <StatCard label="Total Requests" value={totalRequests.toLocaleString()} trend={requestsTrend} />
            <StatCard label="Documents" value={totalDocuments.toLocaleString()} />
            <StatCard label="Searches" value={totalSearches.toLocaleString()} />
            <StatCard label="Tokens Used" value={totalTokens.toLocaleString()} />
          </div>

          {/* Quota bars */}
          {settingsLoading ? (
            <div className="flex justify-center py-8">
              <div className="w-6 h-6 border-2 border-amber-400 border-t-transparent rounded-full animate-spin" />
            </div>
          ) : settings?.usage && settings?.limits ? (
            <div className="rounded-xl border border-zinc-800 bg-zinc-900/40 p-5 space-y-4">
              <h2 className="text-sm font-semibold text-zinc-200 mb-1">Usage Quotas</h2>
              <QuotaBar
                label="Requests today"
                current={settings.usage.requests_today ?? 0}
                max={settings.limits.requests_per_day ?? 100}
                showProjection
              />
              <QuotaBar
                label="Documents"
                current={settings.usage.documents ?? 0}
                max={settings.limits.max_documents ?? 5}
              />
              <QuotaBar
                label="API Keys"
                current={settings.usage.keys ?? 0}
                max={settings.limits.max_keys ?? 2}
              />
            </div>
          ) : null}

          {/* Usage chart (14 days) */}
          <div className="rounded-xl border border-zinc-800 bg-zinc-900/40 p-5">
            <h2 className="text-sm font-semibold text-zinc-200 mb-4">Requests (last 14 days)</h2>
            {usageLoading ? (
              <div className="flex justify-center py-8">
                <div className="w-6 h-6 border-2 border-amber-400 border-t-transparent rounded-full animate-spin" />
              </div>
            ) : usage.length === 0 ? (
              <p className="text-sm text-zinc-500 py-4 text-center">No usage data yet.</p>
            ) : (
              <div className="space-y-1.5">
                {usage.map((day) => {
                  const pct = maxUsage > 0 ? (day.requests / maxUsage) * 100 : 0;
                  const dateLabel = new Date(day.date).toLocaleDateString(undefined, { month: "short", day: "numeric" });
                  const isToday = day.date === todayStr;
                  return (
                    <div key={day.date} className="flex items-center gap-3">
                      <span className={`text-xs w-16 text-right font-mono ${isToday ? "text-amber-400" : "text-zinc-500"}`}>{dateLabel}</span>
                      <div className="flex-1 h-5 bg-zinc-800 rounded overflow-hidden relative">
                        <div
                          className={`h-full rounded transition-all ${isToday ? "bg-amber-400" : "bg-zinc-500/50"}`}
                          style={{ width: `${Math.max(pct, 0.5)}%` }}
                        />
                        {/* Average line */}
                        {avgUsage > 0 && (
                          <div
                            className="absolute top-0 bottom-0 w-px bg-zinc-400/30"
                            style={{ left: `${(avgUsage / maxUsage) * 100}%` }}
                          />
                        )}
                      </div>
                      <span className={`text-xs font-mono w-12 text-right ${isToday ? "text-amber-400" : "text-zinc-400"}`}>{day.requests.toLocaleString()}</span>
                    </div>
                  );
                })}
                {avgUsage > 0 && (
                  <p className="text-[10px] text-zinc-600 text-right mt-1">Avg: {Math.round(avgUsage).toLocaleString()} req/day</p>
                )}
              </div>
            )}
          </div>

          {/* Recent Activity Feed */}
          {!keysLoading && (
            <ActivityFeed items={recentActivity} />
          )}

          {/* Quick Actions */}
          <div className="flex flex-wrap gap-3">
            <button
              onClick={() => setTab("keys")}
              className="inline-flex items-center gap-2 px-4 py-2 rounded-lg border border-zinc-800 bg-zinc-900/40 text-sm text-zinc-300 hover:text-amber-400 hover:border-zinc-700 transition-colors"
            >
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" d="M15.75 5.25a3 3 0 0 1 3 3m3 0a6 6 0 0 1-7.029 5.912c-.563-.097-1.159.026-1.563.43L10.5 17.25H8.25v2.25H6v2.25H2.25v-2.818c0-.597.237-1.17.659-1.591l6.499-6.499c.404-.404.527-1 .43-1.563A6 6 0 1 1 21.75 8.25Z" />
              </svg>
              Create API Key
            </button>
            <a
              href="/dashboard/playground"
              className="inline-flex items-center gap-2 px-4 py-2 rounded-lg border border-zinc-800 bg-zinc-900/40 text-sm text-zinc-300 hover:text-amber-400 hover:border-zinc-700 transition-colors"
            >
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" d="M5.25 5.653c0-.856.917-1.398 1.667-.986l11.54 6.347a1.125 1.125 0 0 1 0 1.972l-11.54 6.347a1.125 1.125 0 0 1-1.667-.986V5.653Z" />
              </svg>
              Open Playground
            </a>
            <a
              href="/docs"
              className="inline-flex items-center gap-2 px-4 py-2 rounded-lg border border-zinc-800 bg-zinc-900/40 text-sm text-zinc-300 hover:text-amber-400 hover:border-zinc-700 transition-colors"
            >
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 0 0-3.375-3.375h-1.5A1.125 1.125 0 0 1 13.5 7.125v-1.5a3.375 3.375 0 0 0-3.375-3.375H8.25m0 12.75h7.5m-7.5 3H12M10.5 2.25H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 0 0-9-9Z" />
              </svg>
              View Docs
            </a>
          </div>
        </div>
      )}

      {/* ── API Keys Tab ── */}
      {tab === "keys" && (
        <div className="space-y-6">
          {/* Create key */}
          <form onSubmit={createKey} className="rounded-2xl border border-zinc-800 bg-zinc-900/60 p-5">
            <h2 className="text-sm font-semibold text-zinc-200 mb-3">Generate API key</h2>
            <div className="flex gap-3">
              <input type="text" value={newLabel} onChange={(e) => setNewLabel(e.target.value)} placeholder="Label (e.g. production, staging, dev)" required className="flex-1 px-4 py-2.5 rounded-lg bg-zinc-800/50 border border-zinc-700/50 text-zinc-100 placeholder:text-zinc-500 text-sm focus:outline-none focus:ring-2 focus:ring-amber-400/50" />
              <button type="submit" disabled={creating || !newLabel.trim()} className="px-5 py-2.5 rounded-lg bg-amber-500 text-zinc-950 font-semibold text-sm hover:bg-amber-400 disabled:opacity-50 transition-colors">
                {creating ? "..." : "Generate"}
              </button>
            </div>
          </form>

          {/* New key banner */}
          {newlyCreated && (
            <div className="rounded-2xl border border-emerald-500/30 bg-emerald-500/5 p-5">
              <div className="flex items-start justify-between gap-4 mb-2">
                <div>
                  <h3 className="text-sm font-semibold text-emerald-400 mb-1">Key created: &ldquo;{newlyCreated.label}&rdquo;</h3>
                  <p className="text-xs text-zinc-400">Copy now — this is the only time it will be shown.</p>
                </div>
                <button onClick={() => setNewlyCreated(null)} className="text-zinc-500 hover:text-zinc-300 p-1">
                  <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" /></svg>
                </button>
              </div>
              <div className="flex items-center gap-2">
                <code className="flex-1 px-4 py-2.5 rounded-lg bg-zinc-900 border border-zinc-800 text-amber-400 text-sm font-mono break-all select-all">{newlyCreated.key}</code>
                <button onClick={() => { navigator.clipboard.writeText(newlyCreated.key); setCopied(true); setTimeout(() => setCopied(false), 2000); }} className="px-4 py-2.5 rounded-lg bg-zinc-800 text-zinc-200 text-sm font-medium hover:bg-zinc-700 transition-colors flex-shrink-0">
                  {copied ? "Copied!" : "Copy"}
                </button>
              </div>
            </div>
          )}

          {/* Key list */}
          {keysLoading ? (
            <div className="flex justify-center py-12">
              <div className="w-6 h-6 border-2 border-amber-400 border-t-transparent rounded-full animate-spin" />
            </div>
          ) : keys.length === 0 ? (
            <div className="text-center py-12 text-zinc-500">
              <p className="text-lg mb-1">No API keys yet</p>
              <p className="text-sm">Generate one above to start using the API.</p>
            </div>
          ) : (
            <>
              {activeKeys.length > 0 && (
                <div>
                  <h2 className="text-sm font-medium text-zinc-400 mb-3">Active ({activeKeys.length})</h2>
                  <div className="space-y-2">
                    {activeKeys.map((k) => (
                      <div key={k.id}>
                        <KeyCard apiKey={k} onRevoke={() => revokeKey(k.id)} onDelete={() => deleteKey(k.id)} />
                        {/* Per-key mini stats */}
                        <div className="px-5 pb-2 -mt-1 rounded-b-xl border-x border-b border-zinc-800 bg-zinc-900/40 flex items-center gap-4">
                          <KeyActivityBars apiKey={k} />
                          {k.last_used_at && (
                            <span className="text-[11px] text-zinc-600">Last active: {timeAgo(k.last_used_at)}</span>
                          )}
                          {!k.last_used_at && (
                            <span className="text-[11px] text-zinc-700">Never used</span>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}
              {revokedKeys.length > 0 && (
                <div>
                  <h2 className="text-sm font-medium text-zinc-500 mb-3">Revoked ({revokedKeys.length})</h2>
                  <div className="space-y-2 opacity-60">
                    {revokedKeys.map((k) => (
                      <KeyCard key={k.id} apiKey={k} onReinstate={() => reinstateKey(k.id)} onDelete={() => deleteKey(k.id)} />
                    ))}
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      )}

      {/* ── Playground Tab ── */}
      {tab === "playground" && (
        <div className="rounded-xl border border-zinc-800 bg-zinc-900/40 p-6">
          <h2 className="text-lg font-semibold text-zinc-100 mb-2">API Playground</h2>
          <p className="text-sm text-zinc-400 mb-5">
            Test document ingestion, search queries, and explore the API interactively.
          </p>
          <a
            href="/dashboard/playground"
            className="inline-flex items-center gap-2 px-5 py-2.5 rounded-lg bg-amber-500 text-zinc-950 font-semibold text-sm hover:bg-amber-400 transition-colors"
          >
            Open Playground
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" d="M13.5 4.5L21 12m0 0l-7.5 7.5M21 12H3" /></svg>
          </a>
        </div>
      )}

      {/* ── Settings Tab ── */}
      {tab === "settings" && (
        <div className="rounded-xl border border-zinc-800 bg-zinc-900/40 p-6">
          <h2 className="text-lg font-semibold text-zinc-100 mb-2">Account Settings</h2>
          <p className="text-sm text-zinc-400 mb-5">
            Manage your profile, notification preferences, and billing details.
          </p>
          <a
            href="/dashboard/settings"
            className="inline-flex items-center gap-2 px-5 py-2.5 rounded-lg bg-amber-500 text-zinc-950 font-semibold text-sm hover:bg-amber-400 transition-colors"
          >
            Open Settings
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" d="M13.5 4.5L21 12m0 0l-7.5 7.5M21 12H3" /></svg>
          </a>
        </div>
      )}
    </div>
  );
}

function KeyCard({
  apiKey,
  onRevoke,
  onReinstate,
  onDelete,
}: {
  apiKey: ApiKey;
  onRevoke?: () => void;
  onReinstate?: () => void;
  onDelete: () => void;
}) {
  const masked = apiKey.key.slice(0, 3) + "..." + apiKey.key.slice(-4);

  return (
    <div className="rounded-xl border border-zinc-800 bg-zinc-900/40 px-5 py-3">
      <div className="flex items-center gap-4">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-sm font-medium text-zinc-100">{apiKey.label}</span>
            {apiKey.revoked && (
              <span className="text-[10px] px-1.5 py-0.5 rounded bg-red-500/10 text-red-400 border border-red-500/20">revoked</span>
            )}
          </div>
          <div className="flex items-center gap-3 mt-0.5 flex-wrap">
            <span className="text-xs font-mono text-zinc-500">{masked}</span>
            <span className="text-xs text-zinc-600">&middot;</span>
            <span className="text-xs text-zinc-500">{new Date(apiKey.created_at).toLocaleDateString()}</span>
            {apiKey.requests_count > 0 && (
              <>
                <span className="text-xs text-zinc-600">&middot;</span>
                <span className="text-xs text-zinc-500">{apiKey.requests_count.toLocaleString()} requests</span>
              </>
            )}
            {apiKey.documents_ingested > 0 && (
              <>
                <span className="text-xs text-zinc-600">&middot;</span>
                <span className="text-xs text-zinc-500">{apiKey.documents_ingested} docs</span>
              </>
            )}
            {apiKey.last_used_at && (
              <>
                <span className="text-xs text-zinc-600">&middot;</span>
                <span className="text-xs text-zinc-500">last used {new Date(apiKey.last_used_at).toLocaleDateString()}</span>
              </>
            )}
          </div>
        </div>
        <div className="flex items-center gap-2 flex-shrink-0">
          {onRevoke && <button onClick={onRevoke} className="text-xs text-zinc-400 hover:text-amber-400 transition-colors px-2 py-1">Revoke</button>}
          {onReinstate && <button onClick={onReinstate} className="text-xs text-zinc-400 hover:text-emerald-400 transition-colors px-2 py-1">Reinstate</button>}
          <button onClick={onDelete} className="text-xs text-zinc-500 hover:text-red-400 transition-colors px-2 py-1">Delete</button>
        </div>
      </div>
    </div>
  );
}
