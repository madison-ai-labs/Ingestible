"use client";

import { useState } from "react";
import { useAuth } from "./auth-context";
import { api, setAuth } from "@/lib/api";

export function LoginForm() {
  const { login } = useAuth();
  const [apiUrl, setApiUrl] = useState("http://localhost:8081");
  const [apiKey, setApiKey] = useState("");
  const [error, setError] = useState("");
  const [testing, setTesting] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setTesting(true);

    try {
      // Temporarily set auth so api.health() can use it
      setAuth({ apiUrl, apiKey });
      await api.health();
      login({ apiUrl, apiKey });
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Connection failed";
      if (msg.includes("Failed to fetch") || msg.includes("NetworkError")) {
        setError(
          "Cannot reach the API. Check the URL and make sure CORS is enabled on your Ingestible instance."
        );
      } else if (msg.includes("401") || msg.includes("403")) {
        setError("Invalid API key.");
      } else {
        setError(msg);
      }
      // Clear the temporary auth
      const { clearAuth } = await import("@/lib/api");
      clearAuth();
    } finally {
      setTesting(false);
    }
  }

  return (
    <div className="flex items-center justify-center min-h-[70vh] px-4">
      <div className="w-full max-w-md">
        <div className="text-center mb-8">
          <h1 className="text-2xl font-bold text-zinc-100 mb-2">
            Connect to Ingestible
          </h1>
          <p className="text-sm text-zinc-400">
            Enter your Ingestible API endpoint and key to get started.
          </p>
        </div>

        <form
          onSubmit={handleSubmit}
          className="rounded-2xl border border-zinc-800 bg-zinc-900/60 p-6 space-y-5"
        >
          <div>
            <label
              htmlFor="apiUrl"
              className="block text-sm font-medium text-zinc-300 mb-1.5"
            >
              API URL
            </label>
            <input
              id="apiUrl"
              type="url"
              value={apiUrl}
              onChange={(e) => setApiUrl(e.target.value)}
              placeholder="http://localhost:8081"
              required
              className="w-full px-4 py-2.5 rounded-lg bg-zinc-800/50 border border-zinc-700/50 text-zinc-100 placeholder:text-zinc-500 text-sm focus:outline-none focus:ring-2 focus:ring-amber-400/50 focus:border-amber-400/50 transition-colors"
            />
          </div>

          <div>
            <label
              htmlFor="apiKey"
              className="block text-sm font-medium text-zinc-300 mb-1.5"
            >
              API Key
              <span className="text-zinc-500 font-normal ml-1">
                (optional if auth is disabled)
              </span>
            </label>
            <input
              id="apiKey"
              type="password"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder="your-api-key"
              className="w-full px-4 py-2.5 rounded-lg bg-zinc-800/50 border border-zinc-700/50 text-zinc-100 placeholder:text-zinc-500 text-sm focus:outline-none focus:ring-2 focus:ring-amber-400/50 focus:border-amber-400/50 transition-colors"
            />
          </div>

          {error && (
            <div className="rounded-lg bg-red-500/10 border border-red-500/20 px-4 py-3 text-sm text-red-400">
              {error}
            </div>
          )}

          <button
            type="submit"
            disabled={testing}
            className="w-full flex items-center justify-center gap-2 px-4 py-2.5 rounded-lg bg-amber-500 text-zinc-950 font-semibold text-sm hover:bg-amber-400 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {testing ? (
              <>
                <div className="w-4 h-4 border-2 border-zinc-950 border-t-transparent rounded-full animate-spin" />
                Testing connection...
              </>
            ) : (
              "Connect"
            )}
          </button>

          <p className="text-xs text-zinc-500 text-center">
            Your credentials are stored locally in your browser. Nothing is sent
            to our servers.
          </p>
        </form>
      </div>
    </div>
  );
}
