"use client";

import { useEffect, useState, useCallback, useRef } from "react";
import { getSupabase } from "@/lib/supabase-browser";
import Link from "next/link";

/* ── Types ── */

interface ApiKeyOption {
  id: string;
  key: string;
  label: string;
  revoked: boolean;
}

interface EndpointConfig {
  id: string;
  label: string;
  method: "GET" | "POST" | "DELETE";
  path: string;
  fields: FieldDef[];
}

interface FieldDef {
  name: string;
  label: string;
  type: "text" | "number" | "file" | "checkbox";
  placeholder?: string;
  defaultValue?: string | number | boolean;
}

interface ResponseData {
  status: number;
  statusText: string;
  body: string;
  timeMs: number;
  sizeBytes: number;
}

interface HistoryItem {
  id: string;
  endpointId: string;
  endpointLabel: string;
  fields: Record<string, any>;
  status: number;
  statusText: string;
  timeMs: number;
  timestamp: number;
}

/* ── Endpoints ── */

const ENDPOINTS: EndpointConfig[] = [
  {
    id: "ingest-file",
    label: "POST /ingest",
    method: "POST",
    path: "/ingest",
    fields: [
      { name: "file", label: "File", type: "file" },
      {
        name: "skip_enrichment",
        label: "Skip enrichment",
        type: "checkbox",
        defaultValue: false,
      },
    ],
  },
  {
    id: "ingest-url",
    label: "POST /ingest/url",
    method: "POST",
    path: "/ingest/url",
    fields: [
      {
        name: "url",
        label: "URL",
        type: "text",
        placeholder: "https://example.com/document.pdf",
      },
    ],
  },
  {
    id: "list-documents",
    label: "GET /documents",
    method: "GET",
    path: "/documents",
    fields: [],
  },
  {
    id: "get-document",
    label: "GET /documents/{doc_id}",
    method: "GET",
    path: "/documents/{doc_id}",
    fields: [
      {
        name: "doc_id",
        label: "Document ID",
        type: "text",
        placeholder: "my-document-id",
      },
    ],
  },
  {
    id: "search-document",
    label: "POST /documents/{doc_id}/search",
    method: "POST",
    path: "/documents/{doc_id}/search",
    fields: [
      {
        name: "doc_id",
        label: "Document ID",
        type: "text",
        placeholder: "my-document-id",
      },
      {
        name: "query",
        label: "Query",
        type: "text",
        placeholder: "What is the main topic?",
      },
      {
        name: "n_results",
        label: "Number of results",
        type: "number",
        defaultValue: 5,
      },
    ],
  },
  {
    id: "corpus-search",
    label: "POST /search",
    method: "POST",
    path: "/search",
    fields: [
      {
        name: "query",
        label: "Query",
        type: "text",
        placeholder: "Search across all documents...",
      },
      {
        name: "n_results",
        label: "Number of results",
        type: "number",
        defaultValue: 5,
      },
    ],
  },
  {
    id: "delete-document",
    label: "DELETE /documents/{doc_id}",
    method: "DELETE",
    path: "/documents/{doc_id}",
    fields: [
      {
        name: "doc_id",
        label: "Document ID",
        type: "text",
        placeholder: "my-document-id",
      },
    ],
  },
];

/* ── Helpers ── */

function buildUrl(baseUrl: string, endpoint: EndpointConfig, fields: Record<string, any>): string {
  let path = endpoint.path;
  if (path.includes("{doc_id}") && fields.doc_id) {
    path = path.replace("{doc_id}", encodeURIComponent(fields.doc_id));
  }
  return `${baseUrl.replace(/\/+$/, "")}${path}`;
}

function buildCurl(
  baseUrl: string,
  endpoint: EndpointConfig,
  fields: Record<string, any>,
  apiKey: string
): string {
  const url = buildUrl(baseUrl, endpoint, fields);
  const parts = [`curl -X ${endpoint.method}`];
  parts.push(`  -H "Authorization: Bearer ${apiKey ? apiKey.slice(0, 6) + "..." : "<key>"}"`);

  if (endpoint.id === "ingest-file") {
    parts.push(`  -F "file=@${fields.file instanceof File ? fields.file.name : "<file>"}"`)
    if (fields.skip_enrichment) {
      parts.push(`  -F "skip_enrichment=true"`);
    }
  } else if (endpoint.method === "POST") {
    parts.push(`  -H "Content-Type: application/json"`);
    const body: Record<string, any> = {};
    if (fields.query) body.query = fields.query;
    if (fields.n_results) body.n_results = Number(fields.n_results);
    if (fields.url) body.url = fields.url;
    parts.push(`  -d '${JSON.stringify(body)}'`);
  }

  parts.push(`  "${url}"`);
  return parts.join(" \\\n");
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function statusColor(status: number): string {
  if (status >= 200 && status < 300) return "bg-emerald-500/15 text-emerald-400 border-emerald-500/25";
  if (status >= 400 && status < 500) return "bg-amber-500/15 text-amber-400 border-amber-500/25";
  return "bg-red-500/15 text-red-400 border-red-500/25";
}

const HISTORY_KEY = "ingestible_playground_history";
const MAX_HISTORY = 20;

function loadHistory(): HistoryItem[] {
  try {
    const raw = localStorage.getItem(HISTORY_KEY);
    return raw ? JSON.parse(raw) : [];
  } catch {
    return [];
  }
}

function saveHistory(items: HistoryItem[]) {
  localStorage.setItem(HISTORY_KEY, JSON.stringify(items.slice(0, MAX_HISTORY)));
}

function timeAgo(timestamp: number): string {
  const seconds = Math.floor((Date.now() - timestamp) / 1000);
  if (seconds < 60) return "just now";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

/* ── Page component ── */

export default function PlaygroundPage() {
  const supabase = getSupabase();

  // Auth state
  const [user, setUser] = useState<any>(null);
  const [authLoading, setAuthLoading] = useState(true);

  // API keys
  const [apiKeys, setApiKeys] = useState<ApiKeyOption[]>([]);
  const [selectedKeyId, setSelectedKeyId] = useState("");

  // Endpoint state
  const [selectedEndpointId, setSelectedEndpointId] = useState(ENDPOINTS[0].id);
  const [fields, setFields] = useState<Record<string, any>>({});
  const [baseUrl, setBaseUrl] = useState("https://ingestible.fly.dev");

  // Request state
  const [sending, setSending] = useState(false);
  const [response, setResponse] = useState<ResponseData | null>(null);
  const [error, setError] = useState("");

  // History state
  const [history, setHistory] = useState<HistoryItem[]>([]);
  const [historyOpen, setHistoryOpen] = useState(false);
  const topRef = useRef<HTMLDivElement>(null);

  const selectedEndpoint = ENDPOINTS.find((e) => e.id === selectedEndpointId)!;
  const selectedKey = apiKeys.find((k) => k.id === selectedKeyId);

  // Load history from localStorage
  useEffect(() => {
    setHistory(loadHistory());
  }, []);

  // Auth check
  useEffect(() => {
    supabase.auth.getUser().then(({ data }: any) => {
      setUser(data.user);
      setAuthLoading(false);
    });

    const {
      data: { subscription },
    } = supabase.auth.onAuthStateChange((_event: string, session: any) => {
      setUser(session?.user ?? null);
    });

    return () => subscription.unsubscribe();
  }, []);

  // Fetch API keys
  const loadKeys = useCallback(async () => {
    const { data } = await supabase
      .from("api_keys")
      .select("id, key, label, revoked")
      .eq("revoked", false);
    const keys: ApiKeyOption[] = data || [];
    setApiKeys(keys);
    if (keys.length > 0 && !selectedKeyId) {
      setSelectedKeyId(keys[0].id);
    }
  }, [selectedKeyId]);

  useEffect(() => {
    if (user) loadKeys();
  }, [user, loadKeys]);

  // Reset fields when endpoint changes
  useEffect(() => {
    const defaults: Record<string, any> = {};
    for (const field of selectedEndpoint.fields) {
      if (field.defaultValue !== undefined) {
        defaults[field.name] = field.defaultValue;
      }
    }
    setFields(defaults);
    setResponse(null);
    setError("");
  }, [selectedEndpointId]);

  function setField(name: string, value: any) {
    setFields((prev) => ({ ...prev, [name]: value }));
  }

  function addToHistory(res: ResponseData) {
    const serializedFields: Record<string, any> = {};
    for (const [key, value] of Object.entries(fields)) {
      if (!(value instanceof File)) {
        serializedFields[key] = value;
      }
    }
    const item: HistoryItem = {
      id: typeof crypto !== "undefined" && crypto.randomUUID
        ? crypto.randomUUID()
        : String(Date.now()),
      endpointId: selectedEndpointId,
      endpointLabel: selectedEndpoint.label,
      fields: serializedFields,
      status: res.status,
      statusText: res.statusText,
      timeMs: res.timeMs,
      timestamp: Date.now(),
    };
    const updated = [item, ...history].slice(0, MAX_HISTORY);
    setHistory(updated);
    saveHistory(updated);
  }

  function restoreHistoryItem(item: HistoryItem) {
    setSelectedEndpointId(item.endpointId);
    // Fields are set after endpoint change effect runs, so defer
    setTimeout(() => {
      setFields(item.fields);
    }, 0);
    topRef.current?.scrollIntoView({ behavior: "smooth" });
  }

  function clearHistory() {
    setHistory([]);
    localStorage.removeItem(HISTORY_KEY);
  }

  // Send request
  async function sendRequest() {
    if (!selectedKey) {
      setError("Select an API key first.");
      return;
    }

    setSending(true);
    setError("");
    setResponse(null);

    const startTime = performance.now();

    try {
      const url = buildUrl(baseUrl, selectedEndpoint, fields);
      const headers: Record<string, string> = {
        Authorization: `Bearer ${selectedKey.key}`,
      };

      let body: any = undefined;

      if (selectedEndpoint.id === "ingest-file") {
        const formData = new FormData();
        if (fields.file instanceof File) {
          formData.append("file", fields.file);
        } else {
          setError("Select a file to upload.");
          setSending(false);
          return;
        }
        if (fields.skip_enrichment) {
          formData.append("skip_enrichment", "true");
        }
        body = formData;
      } else if (selectedEndpoint.method === "POST") {
        headers["Content-Type"] = "application/json";
        const jsonBody: Record<string, any> = {};
        if (fields.query) jsonBody.query = fields.query;
        if (fields.n_results) jsonBody.n_results = Number(fields.n_results);
        if (fields.url) jsonBody.url = fields.url;
        body = JSON.stringify(jsonBody);
      }

      const res = await fetch(url, {
        method: selectedEndpoint.method,
        headers,
        body,
      });

      const elapsed = performance.now() - startTime;
      const text = await res.text();

      // Try to pretty-print JSON
      let formatted = text;
      try {
        formatted = JSON.stringify(JSON.parse(text), null, 2);
      } catch {
        // not JSON, keep raw
      }

      const responseData: ResponseData = {
        status: res.status,
        statusText: res.statusText,
        body: formatted,
        timeMs: elapsed,
        sizeBytes: new Blob([text]).size,
      };
      setResponse(responseData);
      addToHistory(responseData);
    } catch (err: any) {
      const elapsed = performance.now() - startTime;
      setError(
        err?.message === "Failed to fetch"
          ? "Request failed. Is your API running? Is CORS enabled?"
          : err?.message || "Request failed"
      );
    } finally {
      setSending(false);
    }
  }

  // Loading / auth gate
  if (authLoading) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <div className="w-6 h-6 border-2 border-amber-400 border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  if (!user) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <div className="text-center">
          <p className="text-zinc-400 mb-4">Sign in to use the API Playground.</p>
          <Link
            href="/dashboard"
            className="px-5 py-2.5 rounded-lg bg-amber-500 text-zinc-950 font-semibold text-sm hover:bg-amber-400"
          >
            Go to Dashboard
          </Link>
        </div>
      </div>
    );
  }

  const curlPreview = buildCurl(
    baseUrl,
    selectedEndpoint,
    fields,
    selectedKey?.key || ""
  );

  return (
    <div ref={topRef} className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
      {/* Back link */}
      <Link
        href="/dashboard"
        className="inline-flex items-center gap-1.5 text-sm text-zinc-400 hover:text-zinc-200 transition-colors mb-6"
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

      {/* Header */}
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-zinc-100">API Playground</h1>
        <p className="text-sm text-zinc-500 mt-1">
          Test your Ingestible API endpoints directly from the browser.
        </p>
      </div>

      {/* CORS notice */}
      <div className="rounded-xl border border-amber-500/20 bg-amber-500/5 px-4 py-3 mb-6 flex items-start gap-3">
        <svg
          className="w-5 h-5 text-amber-400 flex-shrink-0 mt-0.5"
          fill="none"
          viewBox="0 0 24 24"
          strokeWidth={1.5}
          stroke="currentColor"
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z"
          />
        </svg>
        <p className="text-sm text-amber-200/80">
          Requests are sent directly from your browser to your API. Make sure CORS is enabled on your Ingestible instance.
        </p>
      </div>

      {/* Main layout */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Left panel — config */}
        <div className="space-y-4">
          {/* Endpoint selector */}
          <div className="rounded-2xl border border-zinc-800 bg-zinc-900/60 p-5 space-y-4">
            <div>
              <label className="block text-sm font-medium text-zinc-300 mb-1.5">
                Endpoint
              </label>
              <select
                value={selectedEndpointId}
                onChange={(e) => setSelectedEndpointId(e.target.value)}
                className="w-full px-4 py-2.5 rounded-lg bg-zinc-800/50 border border-zinc-700/50 text-zinc-100 text-sm focus:outline-none focus:ring-2 focus:ring-amber-400/50"
              >
                {ENDPOINTS.map((ep) => (
                  <option key={ep.id} value={ep.id}>
                    {ep.label}
                  </option>
                ))}
              </select>
            </div>

            {/* Dynamic fields */}
            {selectedEndpoint.fields.map((field) => (
              <div key={field.name}>
                {field.type === "checkbox" ? (
                  <label className="flex items-center gap-2.5 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={!!fields[field.name]}
                      onChange={(e) =>
                        setField(field.name, e.target.checked)
                      }
                      className="rounded border-zinc-600 bg-zinc-800 text-amber-500 focus:ring-amber-400/50"
                    />
                    <span className="text-sm text-zinc-300">
                      {field.label}
                    </span>
                  </label>
                ) : field.type === "file" ? (
                  <div>
                    <label className="block text-sm font-medium text-zinc-300 mb-1.5">
                      {field.label}
                    </label>
                    <input
                      type="file"
                      onChange={(e) =>
                        setField(field.name, e.target.files?.[0] || null)
                      }
                      className="w-full text-sm text-zinc-400 file:mr-3 file:px-4 file:py-2 file:rounded-lg file:border-0 file:bg-zinc-800 file:text-zinc-200 file:text-sm file:font-medium file:cursor-pointer hover:file:bg-zinc-700"
                    />
                  </div>
                ) : (
                  <div>
                    <label className="block text-sm font-medium text-zinc-300 mb-1.5">
                      {field.label}
                    </label>
                    <input
                      type={field.type}
                      value={fields[field.name] ?? ""}
                      onChange={(e) => setField(field.name, e.target.value)}
                      placeholder={field.placeholder}
                      className="w-full px-4 py-2.5 rounded-lg bg-zinc-800/50 border border-zinc-700/50 text-zinc-100 placeholder:text-zinc-500 text-sm focus:outline-none focus:ring-2 focus:ring-amber-400/50"
                    />
                  </div>
                )}
              </div>
            ))}
          </div>

          {/* API key + base URL */}
          <div className="rounded-2xl border border-zinc-800 bg-zinc-900/60 p-5 space-y-4">
            <div>
              <label className="block text-sm font-medium text-zinc-300 mb-1.5">
                API Key
              </label>
              {apiKeys.length === 0 ? (
                <p className="text-sm text-zinc-500">
                  No active keys.{" "}
                  <Link
                    href="/dashboard"
                    className="text-amber-400 hover:underline"
                  >
                    Create one
                  </Link>{" "}
                  first.
                </p>
              ) : (
                <select
                  value={selectedKeyId}
                  onChange={(e) => setSelectedKeyId(e.target.value)}
                  className="w-full px-4 py-2.5 rounded-lg bg-zinc-800/50 border border-zinc-700/50 text-zinc-100 text-sm focus:outline-none focus:ring-2 focus:ring-amber-400/50"
                >
                  {apiKeys.map((k) => (
                    <option key={k.id} value={k.id}>
                      {k.label} ({k.key.slice(0, 6)}...{k.key.slice(-4)})
                    </option>
                  ))}
                </select>
              )}
            </div>

            <div>
              <label className="block text-sm font-medium text-zinc-300 mb-1.5">
                API Base URL
              </label>
              <input
                type="text"
                value={baseUrl}
                onChange={(e) => setBaseUrl(e.target.value)}
                placeholder="https://ingestible.fly.dev"
                className="w-full px-4 py-2.5 rounded-lg bg-zinc-800/50 border border-zinc-700/50 text-zinc-100 placeholder:text-zinc-500 text-sm focus:outline-none focus:ring-2 focus:ring-amber-400/50"
              />
            </div>
          </div>

          {/* Send button */}
          <button
            onClick={sendRequest}
            disabled={sending || apiKeys.length === 0}
            className="w-full px-5 py-2.5 rounded-lg bg-amber-500 text-zinc-950 font-semibold text-sm hover:bg-amber-400 disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex items-center justify-center gap-2"
          >
            {sending ? (
              <>
                <div className="w-4 h-4 border-2 border-zinc-950 border-t-transparent rounded-full animate-spin" />
                Sending...
              </>
            ) : (
              <>
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
                    d="M6 12L3.269 3.126A59.768 59.768 0 0121.485 12 59.77 59.77 0 013.27 20.876L5.999 12zm0 0h7.5"
                  />
                </svg>
                Send Request
              </>
            )}
          </button>
        </div>

        {/* Right panel — preview + response */}
        <div className="lg:col-span-2 space-y-4">
          {/* Request preview */}
          <div className="rounded-2xl border border-zinc-800 bg-zinc-900/60 p-5">
            <div className="flex items-center justify-between mb-3">
              <h2 className="text-sm font-semibold text-zinc-200">
                Request Preview
              </h2>
              <button
                onClick={() => navigator.clipboard.writeText(curlPreview)}
                className="text-xs text-zinc-500 hover:text-zinc-300 transition-colors"
              >
                Copy curl
              </button>
            </div>
            <div className="rounded-xl bg-zinc-900 border border-zinc-800 p-4 font-mono text-sm text-zinc-300 overflow-x-auto">
              <pre className="whitespace-pre-wrap break-all">{curlPreview}</pre>
            </div>
          </div>

          {/* Error */}
          {error && (
            <div className="rounded-xl border border-red-500/20 bg-red-500/5 px-4 py-3 text-sm text-red-400">
              {error}
            </div>
          )}

          {/* Response */}
          {response && (
            <div className="rounded-2xl border border-zinc-800 bg-zinc-900/60 p-5">
              <div className="flex items-center justify-between mb-3">
                <div className="flex items-center gap-3">
                  <h2 className="text-sm font-semibold text-zinc-200">
                    Response
                  </h2>
                  <span
                    className={`text-xs font-mono px-2 py-0.5 rounded border ${statusColor(response.status)}`}
                  >
                    {response.status} {response.statusText}
                  </span>
                </div>
                <div className="flex items-center gap-3 text-xs text-zinc-500">
                  <span>{Math.round(response.timeMs)} ms</span>
                  <span>{formatBytes(response.sizeBytes)}</span>
                </div>
              </div>
              <div className="rounded-xl bg-zinc-900 border border-zinc-800 p-4 font-mono text-sm text-zinc-300 overflow-x-auto max-h-[600px] overflow-y-auto">
                <pre className="whitespace-pre-wrap break-all">
                  {response.body}
                </pre>
              </div>
            </div>
          )}

          {/* Empty state */}
          {!response && !error && !sending && (
            <div className="rounded-2xl border border-zinc-800 bg-zinc-900/60 p-12 text-center">
              <svg
                className="w-10 h-10 text-zinc-700 mx-auto mb-3"
                fill="none"
                viewBox="0 0 24 24"
                strokeWidth={1}
                stroke="currentColor"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  d="M17.25 6.75L22.5 12l-5.25 5.25m-10.5 0L1.5 12l5.25-5.25m7.5-3l-4.5 16.5"
                />
              </svg>
              <p className="text-sm text-zinc-500">
                Configure your request and hit Send to see the response here.
              </p>
            </div>
          )}

          {/* History panel */}
          {history.length > 0 && (
            <div className="rounded-2xl border border-zinc-800 bg-zinc-900/60">
              <div className="flex items-center justify-between px-5 py-3">
                <button
                  onClick={() => setHistoryOpen(!historyOpen)}
                  className="flex items-center gap-2 text-sm font-semibold text-zinc-200 hover:text-zinc-100 transition-colors"
                >
                  <svg
                    className={`w-4 h-4 text-zinc-500 transition-transform ${historyOpen ? "rotate-90" : ""}`}
                    fill="none"
                    viewBox="0 0 24 24"
                    strokeWidth={2}
                    stroke="currentColor"
                  >
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      d="M8.25 4.5l7.5 7.5-7.5 7.5"
                    />
                  </svg>
                  History ({history.length})
                </button>
                {historyOpen && (
                  <button
                    onClick={clearHistory}
                    className="text-xs text-zinc-500 hover:text-red-400 transition-colors"
                  >
                    Clear history
                  </button>
                )}
              </div>
              {historyOpen && (
                <div className="border-t border-zinc-800 divide-y divide-zinc-800/50 max-h-[400px] overflow-y-auto">
                  {history.map((item) => (
                    <button
                      key={item.id}
                      onClick={() => restoreHistoryItem(item)}
                      className="w-full px-5 py-3 flex items-center justify-between gap-3 hover:bg-zinc-800/40 transition-colors text-left"
                    >
                      <div className="flex items-center gap-3 min-w-0">
                        <span className="text-sm text-zinc-300 truncate">
                          {item.endpointLabel}
                        </span>
                        <span
                          className={`text-xs font-mono px-1.5 py-0.5 rounded border flex-shrink-0 ${statusColor(item.status)}`}
                        >
                          {item.status}
                        </span>
                      </div>
                      <div className="flex items-center gap-3 text-xs text-zinc-500 flex-shrink-0">
                        <span>{Math.round(item.timeMs)} ms</span>
                        <span>{timeAgo(item.timestamp)}</span>
                      </div>
                    </button>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
