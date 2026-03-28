import { NextRequest, NextResponse } from "next/server";
import { verifyAdmin } from "@/lib/admin-auth";
import { supabase } from "@/lib/supabase";

// GET /api/admin/keys/[id]/usage?days=30
export async function GET(
  req: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const denied = await verifyAdmin(req);
  if (denied) return denied;

  const { id } = await params;
  const days = parseInt(req.nextUrl.searchParams.get("days") || "30");
  const since = new Date();
  since.setDate(since.getDate() - days);

  // Daily usage breakdown
  const { data: daily, error: dailyErr } = await supabase()
    .from("api_key_usage")
    .select("*")
    .eq("api_key_id", id)
    .gte("date", since.toISOString().split("T")[0])
    .order("date", { ascending: true });

  if (dailyErr) {
    return NextResponse.json({ error: dailyErr.message }, { status: 500 });
  }

  // Recent requests
  const { data: recent, error: recentErr } = await supabase()
    .from("api_request_log")
    .select("*")
    .eq("api_key_id", id)
    .order("timestamp", { ascending: false })
    .limit(50);

  if (recentErr) {
    return NextResponse.json({ error: recentErr.message }, { status: 500 });
  }

  // Aggregate stats
  const totalRequests = (daily || []).reduce((s, d) => s + d.requests, 0);
  const totalErrors = (daily || []).reduce((s, d) => s + d.errors, 0);
  const totalTokens = (daily || []).reduce((s, d) => s + (d.tokens_used || 0), 0);
  const totalBytes = (daily || []).reduce((s, d) => s + (d.bytes_uploaded || 0), 0);

  // Endpoint breakdown
  const byEndpoint: Record<string, { requests: number; errors: number }> = {};
  for (const d of daily || []) {
    if (!byEndpoint[d.endpoint]) byEndpoint[d.endpoint] = { requests: 0, errors: 0 };
    byEndpoint[d.endpoint].requests += d.requests;
    byEndpoint[d.endpoint].errors += d.errors;
  }

  return NextResponse.json({
    period_days: days,
    totals: {
      requests: totalRequests,
      errors: totalErrors,
      tokens_used: totalTokens,
      bytes_uploaded: totalBytes,
      error_rate: totalRequests > 0 ? (totalErrors / totalRequests * 100).toFixed(1) : "0",
    },
    by_endpoint: byEndpoint,
    daily: daily || [],
    recent_requests: recent || [],
  });
}
