"use client";

import { useState, useEffect, useCallback } from "react";
import { useAuth } from "./auth-context";
import { api, DocumentSummary, SearchResult } from "@/lib/api";

export function Dashboard() {
  const { auth, logout } = useAuth();
  const [documents, setDocuments] = useState<DocumentSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [view, setView] = useState<"documents" | "search">("documents");

  const loadDocuments = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const docs = await api.listDocuments();
      setDocuments(Array.isArray(docs) ? docs : []);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to load documents");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadDocuments();
  }, [loadDocuments]);

  return (
    <div className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
      {/* Header */}
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-2xl font-bold text-zinc-100">Dashboard</h1>
          <p className="text-sm text-zinc-500 mt-1">
            Connected to{" "}
            <span className="text-zinc-400 font-mono text-xs">
              {auth?.apiUrl}
            </span>
          </p>
        </div>
        <button
          onClick={logout}
          className="text-sm text-zinc-400 hover:text-zinc-200 transition-colors px-3 py-1.5 rounded-lg border border-zinc-800 hover:border-zinc-700"
        >
          Disconnect
        </button>
      </div>

      {/* Tab navigation */}
      <div className="flex gap-1 mb-6 border-b border-zinc-800">
        <TabButton
          active={view === "documents"}
          onClick={() => setView("documents")}
        >
          Documents
        </TabButton>
        <TabButton
          active={view === "search"}
          onClick={() => setView("search")}
        >
          Search
        </TabButton>
      </div>

      {error && (
        <div className="rounded-lg bg-red-500/10 border border-red-500/20 px-4 py-3 text-sm text-red-400 mb-6">
          {error}
        </div>
      )}

      {view === "documents" ? (
        <DocumentsView
          documents={documents}
          loading={loading}
          onRefresh={loadDocuments}
        />
      ) : (
        <SearchView documents={documents} />
      )}
    </div>
  );
}

function TabButton({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      className={`px-4 py-2.5 text-sm font-medium transition-colors border-b-2 -mb-px ${
        active
          ? "text-amber-400 border-amber-400"
          : "text-zinc-400 border-transparent hover:text-zinc-200"
      }`}
    >
      {children}
    </button>
  );
}

// ── Documents View ──

function DocumentsView({
  documents,
  loading,
  onRefresh,
}: {
  documents: DocumentSummary[];
  loading: boolean;
  onRefresh: () => void;
}) {
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState("");
  const [uploadSuccess, setUploadSuccess] = useState("");
  const [skipEnrichment, setSkipEnrichment] = useState(false);
  const [deleting, setDeleting] = useState<string | null>(null);
  const [expandedDoc, setExpandedDoc] = useState<string | null>(null);

  async function handleUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;

    setUploading(true);
    setUploadError("");
    setUploadSuccess("");

    try {
      const result = await api.ingestFile(file, skipEnrichment);
      setUploadSuccess(
        `Ingested "${result.title}" — ${result.total_chunks} chunks, ${result.total_pages} pages`
      );
      onRefresh();
    } catch (err: unknown) {
      setUploadError(
        err instanceof Error ? err.message : "Upload failed"
      );
    } finally {
      setUploading(false);
      e.target.value = "";
    }
  }

  async function handleDelete(docId: string) {
    if (!confirm(`Delete "${docId}"? This cannot be undone.`)) return;
    setDeleting(docId);
    try {
      await api.deleteDocument(docId);
      onRefresh();
    } catch (err: unknown) {
      alert(err instanceof Error ? err.message : "Delete failed");
    } finally {
      setDeleting(null);
    }
  }

  return (
    <div>
      {/* Upload area */}
      <div className="rounded-2xl border border-dashed border-zinc-700 bg-zinc-900/40 p-6 mb-6">
        <div className="flex flex-col sm:flex-row items-start sm:items-center gap-4">
          <div className="flex-1">
            <h3 className="text-sm font-semibold text-zinc-200 mb-1">
              Ingest a document
            </h3>
            <p className="text-xs text-zinc-500">
              PDF, DOCX, HTML, EPUB, Markdown, and 20+ more formats
            </p>
          </div>
          <div className="flex items-center gap-3">
            <label className="flex items-center gap-2 text-xs text-zinc-400 cursor-pointer">
              <input
                type="checkbox"
                checked={skipEnrichment}
                onChange={(e) => setSkipEnrichment(e.target.checked)}
                className="rounded border-zinc-600 bg-zinc-800 text-amber-500 focus:ring-amber-400/50"
              />
              Skip enrichment
            </label>
            <label className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-amber-500 text-zinc-950 font-semibold text-sm hover:bg-amber-400 cursor-pointer transition-colors">
              {uploading ? (
                <>
                  <div className="w-4 h-4 border-2 border-zinc-950 border-t-transparent rounded-full animate-spin" />
                  Ingesting...
                </>
              ) : (
                <>
                  <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5m-13.5-9L12 3m0 0l4.5 4.5M12 3v13.5" />
                  </svg>
                  Upload
                </>
              )}
              <input
                type="file"
                onChange={handleUpload}
                disabled={uploading}
                className="hidden"
              />
            </label>
          </div>
        </div>
        {uploadError && (
          <div className="mt-3 text-sm text-red-400">{uploadError}</div>
        )}
        {uploadSuccess && (
          <div className="mt-3 text-sm text-emerald-400">{uploadSuccess}</div>
        )}
      </div>

      {/* Document list */}
      {loading ? (
        <div className="flex justify-center py-12">
          <div className="w-6 h-6 border-2 border-amber-400 border-t-transparent rounded-full animate-spin" />
        </div>
      ) : documents.length === 0 ? (
        <div className="text-center py-12 text-zinc-500">
          <p className="text-lg mb-1">No documents yet</p>
          <p className="text-sm">Upload a document to get started.</p>
        </div>
      ) : (
        <div className="space-y-3">
          <div className="flex items-center justify-between mb-2">
            <span className="text-sm text-zinc-400">
              {documents.length} document{documents.length !== 1 ? "s" : ""}
            </span>
            <button
              onClick={onRefresh}
              className="text-xs text-zinc-500 hover:text-zinc-300 transition-colors"
            >
              Refresh
            </button>
          </div>
          {documents.map((doc) => (
            <DocumentCard
              key={doc.doc_id}
              doc={doc}
              expanded={expandedDoc === doc.doc_id}
              onToggle={() =>
                setExpandedDoc(
                  expandedDoc === doc.doc_id ? null : doc.doc_id
                )
              }
              onDelete={() => handleDelete(doc.doc_id)}
              deleting={deleting === doc.doc_id}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function DocumentCard({
  doc,
  expanded,
  onToggle,
  onDelete,
  deleting,
}: {
  doc: DocumentSummary;
  expanded: boolean;
  onToggle: () => void;
  onDelete: () => void;
  deleting: boolean;
}) {
  const [docSearch, setDocSearch] = useState("");
  const [results, setResults] = useState<SearchResult[]>([]);
  const [searching, setSearching] = useState(false);

  async function handleSearch(e: React.FormEvent) {
    e.preventDefault();
    if (!docSearch.trim()) return;
    setSearching(true);
    try {
      const res = await api.searchDocument(doc.doc_id, docSearch);
      setResults(res.results || []);
    } catch {
      setResults([]);
    } finally {
      setSearching(false);
    }
  }

  return (
    <div className="rounded-xl border border-zinc-800 bg-zinc-900/40 overflow-hidden">
      <button
        onClick={onToggle}
        className="w-full flex items-center gap-4 px-5 py-4 text-left hover:bg-zinc-800/30 transition-colors"
      >
        <svg
          className={`w-4 h-4 text-zinc-500 transition-transform flex-shrink-0 ${expanded ? "rotate-90" : ""}`}
          fill="none"
          viewBox="0 0 24 24"
          strokeWidth={2}
          stroke="currentColor"
        >
          <path strokeLinecap="round" strokeLinejoin="round" d="M8.25 4.5l7.5 7.5-7.5 7.5" />
        </svg>
        <div className="flex-1 min-w-0">
          <h3 className="text-sm font-medium text-zinc-100 truncate">
            {doc.title || doc.doc_id}
          </h3>
          <div className="flex items-center gap-3 mt-1">
            <span className="text-xs text-zinc-500">
              {doc.total_pages} pages
            </span>
            <span className="text-xs text-zinc-600">&middot;</span>
            <span className="text-xs text-zinc-500">
              {doc.total_chunks} chunks
            </span>
            {doc.source_format && (
              <>
                <span className="text-xs text-zinc-600">&middot;</span>
                <span className="text-xs font-mono text-zinc-500 uppercase">
                  {doc.source_format}
                </span>
              </>
            )}
          </div>
        </div>
        <span className="text-xs font-mono text-zinc-600 hidden sm:block">
          {doc.doc_id}
        </span>
      </button>

      {expanded && (
        <div className="border-t border-zinc-800 px-5 py-4 space-y-4">
          {/* Quick search within doc */}
          <form onSubmit={handleSearch} className="flex gap-2">
            <input
              type="text"
              value={docSearch}
              onChange={(e) => setDocSearch(e.target.value)}
              placeholder={`Search "${doc.title || doc.doc_id}"...`}
              className="flex-1 px-3 py-2 rounded-lg bg-zinc-800/50 border border-zinc-700/50 text-zinc-100 placeholder:text-zinc-500 text-sm focus:outline-none focus:ring-2 focus:ring-amber-400/50"
            />
            <button
              type="submit"
              disabled={searching || !docSearch.trim()}
              className="px-4 py-2 rounded-lg bg-zinc-800 text-zinc-200 text-sm font-medium hover:bg-zinc-700 disabled:opacity-50 transition-colors"
            >
              {searching ? "..." : "Search"}
            </button>
          </form>

          {/* Search results */}
          {results.length > 0 && (
            <div className="space-y-2">
              {results.map((r, i) => (
                <div
                  key={r.chunk_id || i}
                  className="rounded-lg bg-zinc-800/40 border border-zinc-800/60 p-3"
                >
                  <div className="flex items-center gap-2 mb-1.5">
                    <span className="text-xs font-mono text-amber-400/80">
                      {r.score?.toFixed(3)}
                    </span>
                    <span className="text-xs text-zinc-600">
                      {r.chunk_id}
                    </span>
                    {r.page_number && (
                      <span className="text-xs text-zinc-600">
                        p.{r.page_number}
                      </span>
                    )}
                    {r.match_sources && (
                      <div className="flex gap-1">
                        {r.match_sources.map((s) => (
                          <span
                            key={s}
                            className="text-[10px] px-1.5 py-0.5 rounded bg-zinc-700/50 text-zinc-400"
                          >
                            {s}
                          </span>
                        ))}
                      </div>
                    )}
                  </div>
                  <p className="text-sm text-zinc-300 leading-relaxed">
                    {r.content?.slice(0, 300)}
                    {r.content && r.content.length > 300 ? "..." : ""}
                  </p>
                </div>
              ))}
            </div>
          )}

          {/* Actions */}
          <div className="flex items-center gap-3 pt-2">
            <button
              onClick={onDelete}
              disabled={deleting}
              className="text-xs text-red-400/70 hover:text-red-400 transition-colors disabled:opacity-50"
            >
              {deleting ? "Deleting..." : "Delete document"}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

// ── Search View (corpus search) ──

function SearchView({ documents }: { documents: DocumentSummary[] }) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchResult[]>([]);
  const [searching, setSearching] = useState(false);
  const [searched, setSearched] = useState(false);

  async function handleSearch(e: React.FormEvent) {
    e.preventDefault();
    if (!query.trim()) return;
    setSearching(true);
    setSearched(true);
    try {
      const res = await api.searchCorpus(query);
      setResults(res.results || []);
    } catch {
      setResults([]);
    } finally {
      setSearching(false);
    }
  }

  return (
    <div>
      <form onSubmit={handleSearch} className="mb-6">
        <div className="flex gap-3">
          <div className="relative flex-1">
            <svg
              className="absolute left-4 top-1/2 -translate-y-1/2 w-5 h-5 text-zinc-500 pointer-events-none"
              fill="none"
              viewBox="0 0 24 24"
              strokeWidth={1.5}
              stroke="currentColor"
            >
              <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 5.196a7.5 7.5 0 0010.607 10.607z" />
            </svg>
            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search across all documents..."
              className="w-full pl-12 pr-4 py-3 rounded-xl bg-zinc-900/60 border border-zinc-800 text-zinc-100 placeholder:text-zinc-500 text-sm focus:outline-none focus:ring-2 focus:ring-amber-400/50 focus:border-amber-400/50 transition-colors"
            />
          </div>
          <button
            type="submit"
            disabled={searching || !query.trim()}
            className="px-6 py-3 rounded-xl bg-amber-500 text-zinc-950 font-semibold text-sm hover:bg-amber-400 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {searching ? "Searching..." : "Search"}
          </button>
        </div>
        <p className="text-xs text-zinc-500 mt-2">
          Searches across {documents.length} document
          {documents.length !== 1 ? "s" : ""} using hybrid vector + BM25 +
          concept retrieval
        </p>
      </form>

      {searching && (
        <div className="flex justify-center py-8">
          <div className="w-6 h-6 border-2 border-amber-400 border-t-transparent rounded-full animate-spin" />
        </div>
      )}

      {!searching && searched && results.length === 0 && (
        <div className="text-center py-8 text-zinc-500 text-sm">
          No results found. Try a different query.
        </div>
      )}

      {!searching && results.length > 0 && (
        <div className="space-y-3">
          <span className="text-sm text-zinc-400">
            {results.length} result{results.length !== 1 ? "s" : ""}
          </span>
          {results.map((r, i) => (
            <div
              key={r.chunk_id || i}
              className="rounded-xl border border-zinc-800 bg-zinc-900/40 p-4"
            >
              <div className="flex items-center gap-2 mb-2">
                <span className="text-xs font-mono text-amber-400/80 font-medium">
                  {r.score?.toFixed(3)}
                </span>
                <span className="text-xs font-mono text-zinc-600">
                  {r.chunk_id}
                </span>
                {r.level && (
                  <span className="text-[10px] px-1.5 py-0.5 rounded bg-zinc-800 text-zinc-400 uppercase">
                    {r.level}
                  </span>
                )}
                {r.page_number && (
                  <span className="text-xs text-zinc-600">
                    page {r.page_number}
                  </span>
                )}
              </div>
              <p className="text-sm text-zinc-300 leading-relaxed">
                {r.content?.slice(0, 400)}
                {r.content && r.content.length > 400 ? "..." : ""}
              </p>
              {r.summary && (
                <p className="text-xs text-zinc-500 mt-2 italic">
                  {r.summary}
                </p>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
