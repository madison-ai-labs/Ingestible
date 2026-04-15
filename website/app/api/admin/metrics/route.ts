import { NextRequest, NextResponse } from "next/server";
import { verifyAdmin } from "@/lib/admin-auth";
import { supabase } from "@/lib/supabase";

// GET /api/admin/metrics?days=30 — global metrics across all keys
export async function GET(req: NextRequest) {
  const denied = await verifyAdmin(req);
  if (denied) return denied;

  const days = parseInt(req.nextUrl.searchParams.get("days") || "30");
  const since = new Date();
  since.setDate(since.getDate() - days);
  const sinceStr = since.toISOString().split("T")[0];

  // Global daily usage
  const { data: daily, error: dailyErr } = await supabase()
    .from("api_key_usage")
    .select("date, requests, errors, tokens_used, bytes_uploaded")
    .gte("date", sinceStr)
    .order("date", { ascending: true });

  if (dailyErr) {
    return NextResponse.json({ error: dailyErr.message }, { status: 500 });
  }

  // Aggregate by date
  const byDate: Record<string, { requests: number; errors: number; tokens: number; bytes: number }> = {};
  for (const d of daily || []) {
    if (!byDate[d.date]) byDate[d.date] = { requests: 0, errors: 0, tokens: 0, bytes: 0 };
    byDate[d.date].requests += d.requests;
    byDate[d.date].errors += d.errors;
    byDate[d.date].tokens += d.tokens_used || 0;
    byDate[d.date].bytes += d.bytes_uploaded || 0;
  }

  // Key summary (top keys by usage)
  const { data: keys } = await supabase()
    .from("api_keys")
    .select("id, label, revoked, requests_count, tokens_used, documents_ingested, searches_performed, errors_count, bytes_uploaded, created_at, last_used_at")
    .order("requests_count", { ascending: false });

  const totalRequests = (keys || []).reduce((s, k) => s + k.requests_count, 0);
  const totalTokens = (keys || []).reduce((s, k) => s + (k.tokens_used || 0), 0);
  const totalDocs = (keys || []).reduce((s, k) => s + (k.documents_ingested || 0), 0);
  const totalSearches = (keys || []).reduce((s, k) => s + (k.searches_performed || 0), 0);
  const totalErrors = (keys || []).reduce((s, k) => s + (k.errors_count || 0), 0);
  const totalBytesUploaded = (keys || []).reduce((s, k) => s + (k.bytes_uploaded || 0), 0);
  const activeKeys = (keys || []).filter((k) => !k.revoked).length;

  // Rough estimate: $0.10/1M tokens (Gemini Flash pricing)
  const estimatedMonthlyCost = ((totalTokens / 1_000_000) * 0.10).toFixed(2);

  return NextResponse.json({
    period_days: days,
    summary: {
      total_keys: (keys || []).length,
      active_keys: activeKeys,
      total_requests: totalRequests,
      total_tokens: totalTokens,
      total_documents: totalDocs,
      total_searches: totalSearches,
      total_errors: totalErrors,
      error_rate: totalRequests > 0 ? (totalErrors / totalRequests * 100).toFixed(1) : "0",
      total_bytes_uploaded: totalBytesUploaded,
      estimated_monthly_cost: "$" + estimatedMonthlyCost,
      total_storage_bytes: totalBytesUploaded,
    },
    daily: Object.entries(byDate)
      .map(([date, stats]) => ({ date, ...stats }))
      .sort((a, b) => a.date.localeCompare(b.date)),
    keys: keys || [],
  });
}
