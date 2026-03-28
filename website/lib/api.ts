const STORAGE_KEY = "ingestible_auth";

export interface AuthConfig {
  apiUrl: string;
  apiKey: string;
}

export function getAuth(): AuthConfig | null {
  if (typeof window === "undefined") return null;
  const stored = localStorage.getItem(STORAGE_KEY);
  if (!stored) return null;
  try {
    return JSON.parse(stored);
  } catch {
    return null;
  }
}

export function setAuth(config: AuthConfig) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(config));
}

export function clearAuth() {
  localStorage.removeItem(STORAGE_KEY);
}

async function request<T>(
  path: string,
  options: RequestInit = {}
): Promise<T> {
  const auth = getAuth();
  if (!auth) throw new Error("Not authenticated");

  const url = `${auth.apiUrl.replace(/\/$/, "")}${path}`;
  const headers: Record<string, string> = {
    ...(options.headers as Record<string, string>),
  };

  if (auth.apiKey) {
    headers["Authorization"] = `Bearer ${auth.apiKey}`;
  }

  // Don't set Content-Type for FormData
  if (!(options.body instanceof FormData)) {
    headers["Content-Type"] = "application/json";
  }

  const res = await fetch(url, { ...options, headers });

  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`${res.status}: ${text || res.statusText}`);
  }

  return res.json();
}

// ── API methods ──

export interface DocumentSummary {
  doc_id: string;
  title: string;
  total_pages: number;
  total_chunks: number;
  source_format: string;
  ingested_at: string;
  schema_version?: number;
}

export interface DocumentDetail {
  doc_id: string;
  title: string;
  total_pages: number;
  total_chunks: number;
  source_format: string;
  l0_summary?: string;
  l0_toc?: string;
  enriched: boolean;
  ingested_at: string;
}

export interface SearchResult {
  chunk_id: string;
  content: string;
  summary?: string;
  score: number;
  level: string;
  page_number?: number;
  match_sources?: string[];
}

export interface SearchResponse {
  query: string;
  doc_id: string;
  results: SearchResult[];
}

export interface IngestResponse {
  doc_id: string;
  title: string;
  total_pages: number;
  total_chunks: number;
  l0_tokens: number;
  enriched: boolean;
}

export interface TokenEconomics {
  doc_id: string;
  full_document_tokens: number;
  per_query_tokens: number;
  savings_percent: number;
}

export interface HealthResponse {
  status: string;
  version?: string;
}

export const api = {
  // Health check / connection test
  health: () => request<HealthResponse>("/health/ready"),

  // Documents
  listDocuments: () => request<DocumentSummary[]>("/documents"),

  getDocument: (docId: string) =>
    request<DocumentDetail>(`/documents/${docId}`),

  deleteDocument: (docId: string) =>
    request<void>(`/documents/${docId}`, { method: "DELETE" }),

  getEconomics: (docId: string) =>
    request<TokenEconomics>(`/documents/${docId}/economics`),

  // Search
  searchDocument: (docId: string, query: string, nResults = 5) =>
    request<SearchResponse>(`/documents/${docId}/search`, {
      method: "POST",
      body: JSON.stringify({ query, n_results: nResults }),
    }),

  searchCorpus: (query: string, nResults = 5) =>
    request<SearchResponse>("/search", {
      method: "POST",
      body: JSON.stringify({ query, n_results: nResults }),
    }),

  // Ingest
  ingestFile: (file: File, skipEnrichment = false) => {
    const form = new FormData();
    form.append("file", file);
    form.append("skip_enrichment", String(skipEnrichment));
    return request<IngestResponse>("/ingest", {
      method: "POST",
      body: form,
    });
  },

  ingestUrl: (url: string, skipEnrichment = false) =>
    request<IngestResponse>("/ingest/url", {
      method: "POST",
      body: JSON.stringify({ url, skip_enrichment: skipEnrichment }),
    }),
};
