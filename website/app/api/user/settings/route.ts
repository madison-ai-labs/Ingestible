import { NextRequest, NextResponse } from "next/server";
import { supabase } from "@/lib/supabase";

function getToken(req: NextRequest): string | null {
  const auth = req.headers.get("authorization");
  if (!auth || !auth.startsWith("Bearer ")) return null;
  return auth.slice(7);
}

// GET /api/user/settings — get current user's profile + tier limits
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

  const { data: profile, error: profErr } = await supabase()
    .from("profiles")
    .select("*")
    .eq("id", user.id)
    .single();

  if (profErr) {
    return NextResponse.json({ error: profErr.message }, { status: 500 });
  }

  const { data: tierLimits, error: tierErr } = await supabase()
    .from("tier_limits")
    .select("*")
    .eq("tier", profile.role)
    .single();

  if (tierErr) {
    return NextResponse.json({ error: tierErr.message }, { status: 500 });
  }

  // Count user's current usage
  const { data: keyStats } = await supabase()
    .from("api_keys")
    .select("id, requests_count, documents_ingested, tokens_used, bytes_uploaded")
    .eq("user_id", user.id);

  const keys = keyStats || [];
  const totalRequestsToday = 0; // Would need api_key_usage table query for today
  const totalDocuments = keys.reduce((s: number, k: any) => s + (k.documents_ingested || 0), 0);
  const totalTokens = keys.reduce((s: number, k: any) => s + (k.tokens_used || 0), 0);
  const totalBytes = keys.reduce((s: number, k: any) => s + (k.bytes_uploaded || 0), 0);
  // Rough estimate: $0.10/1M tokens (Gemini Flash pricing)
  const estimatedCostUsd = parseFloat(((totalTokens / 1_000_000) * 0.10).toFixed(4));

  return NextResponse.json({
    profile,
    tier_limits: tierLimits,
    // Shape expected by the dashboard
    tier: profile.role,
    limits: {
      requests_per_day: tierLimits?.requests_per_day ?? 100,
      requests_per_minute: tierLimits?.requests_per_minute ?? 10,
      max_documents: tierLimits?.max_documents ?? 5,
      max_keys: tierLimits?.max_keys ?? 2,
      max_file_size_mb: tierLimits?.max_file_size_mb ?? 50,
      enrichment_enabled: tierLimits?.enrichment_enabled ?? false,
    },
    usage: {
      requests_today: totalRequestsToday,
      documents: totalDocuments,
      keys: keys.length,
      total_tokens: totalTokens,
      total_bytes: totalBytes,
      estimated_cost_usd: estimatedCostUsd,
    },
  });
}

// PATCH /api/user/settings — update notification preferences
export async function PATCH(req: NextRequest) {
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

  const body = await req.json().catch(() => ({}));

  const booleanFields = [
    "notify_quota_warning",
    "notify_quota_exceeded",
    "notify_weekly_digest",
    "enrichment_enabled",
    "auto_merge_enabled",
    "hyde_enabled",
    "kg_retrieval_enabled",
    "content_classification",
  ];

  const stringFields = [
    "llm_provider",
    "llm_api_key",
    "llm_model",
    "llm_custom_endpoint",
    "llm_custom_model",
    "vector_backend",
    "vector_connection_string",
    "embedding_model",
  ];

  const allowedFields = [...booleanFields, ...stringFields];

  const updates: Record<string, unknown> = {};
  for (const field of booleanFields) {
    if (typeof body[field] === "boolean") {
      updates[field] = body[field];
    }
  }
  for (const field of stringFields) {
    if (typeof body[field] === "string" || body[field] === null) {
      updates[field] = body[field];
    }
  }

  if (Object.keys(updates).length === 0) {
    return NextResponse.json(
      { error: "No valid updates provided" },
      { status: 400 }
    );
  }

  const { data, error } = await supabase()
    .from("profiles")
    .update(updates)
    .eq("id", user.id)
    .select()
    .single();

  if (error) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }

  return NextResponse.json(data);
}
