import { NextRequest, NextResponse } from "next/server";
import { supabase } from "@/lib/supabase";

function getToken(req: NextRequest): string | null {
  const auth = req.headers.get("authorization");
  if (!auth || !auth.startsWith("Bearer ")) return null;
  return auth.slice(7);
}

// GET /api/user/usage — get user's usage summary + daily breakdown
export async function GET(req: NextRequest) {
  const token = getToken(req);
  if (!token) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  const {
    data: { user },
    error: authErr,
  } = await supabase().auth.getUser(token);

  if (authErr || !user) {
    return NextResponse.json({ error: "Invalid session" }, { status: 401 });
  }

  const url = new URL(req.url);
  const days = parseInt(url.searchParams.get("days") || "30", 10);

  // Get all API keys for this user
  const { data: keys, error: keysErr } = await supabase()
    .from("api_keys")
    .select("id, requests_count, tokens_used, documents_ingested, searches_performed, errors_count, bytes_uploaded")
    .eq("user_id", user.id);

  if (keysErr) {
    return NextResponse.json({ error: keysErr.message }, { status: 500 });
  }

  // Aggregate summary across all keys
  const summary = {
    total_requests: 0,
    total_tokens: 0,
    total_documents: 0,
    total_searches: 0,
    total_errors: 0,
    total_bytes_uploaded: 0,
  };

  for (const key of keys || []) {
    summary.total_requests += key.requests_count || 0;
    summary.total_tokens += key.tokens_used || 0;
    summary.total_documents += key.documents_ingested || 0;
    summary.total_searches += key.searches_performed || 0;
    summary.total_errors += key.errors_count || 0;
    summary.total_bytes_uploaded += key.bytes_uploaded || 0;
  }

  // Get daily breakdown from api_key_usage
  const keyIds = (keys || []).map((k) => k.id);

  let daily: Record<string, { requests: number; tokens: number }> = {};

  if (keyIds.length > 0) {
    const since = new Date();
    since.setDate(since.getDate() - days);

    const { data: usage, error: usageErr } = await supabase()
      .from("api_key_usage")
      .select("date, requests, tokens_used")
      .in("api_key_id", keyIds)
      .gte("date", since.toISOString().split("T")[0])
      .order("date", { ascending: true });

    if (usageErr) {
      return NextResponse.json({ error: usageErr.message }, { status: 500 });
    }

    for (const row of usage || []) {
      if (!daily[row.date]) {
        daily[row.date] = { requests: 0, tokens: 0 };
      }
      daily[row.date].requests += row.requests || 0;
      daily[row.date].tokens += row.tokens_used || 0;
    }
  }

  const dailyBreakdown = Object.entries(daily).map(([date, stats]) => ({
    date,
    ...stats,
  }));

  return NextResponse.json({ summary, daily: dailyBreakdown });
}
