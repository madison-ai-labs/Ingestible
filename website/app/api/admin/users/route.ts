import { NextRequest, NextResponse } from "next/server";
import { verifyAdmin } from "@/lib/admin-auth";
import { supabase } from "@/lib/supabase";

// GET /api/admin/users — list all users with their usage stats
export async function GET(req: NextRequest) {
  const denied = await verifyAdmin(req);
  if (denied) return denied;

  // Get profiles
  const { data: profiles, error: profErr } = await supabase()
    .from("profiles")
    .select("*")
    .order("created_at", { ascending: false });

  if (profErr) {
    return NextResponse.json({ error: profErr.message }, { status: 500 });
  }

  // Get per-user key stats (aggregated)
  const { data: keyStats, error: keyErr } = await supabase()
    .from("api_keys")
    .select(
      "user_id, id, label, revoked, requests_count, tokens_used, documents_ingested, searches_performed, errors_count, bytes_uploaded, created_at, last_used_at"
    );

  if (keyErr) {
    return NextResponse.json({ error: keyErr.message }, { status: 500 });
  }

  // Aggregate stats per user
  const userKeys: Record<
    string,
    {
      total_keys: number;
      active_keys: number;
      total_requests: number;
      total_tokens: number;
      total_documents: number;
      total_searches: number;
      total_errors: number;
      last_used_at: string | null;
    }
  > = {};

  for (const k of keyStats || []) {
    if (!userKeys[k.user_id]) {
      userKeys[k.user_id] = {
        total_keys: 0,
        active_keys: 0,
        total_requests: 0,
        total_tokens: 0,
        total_documents: 0,
        total_searches: 0,
        total_errors: 0,
        last_used_at: null,
      };
    }
    const u = userKeys[k.user_id];
    u.total_keys++;
    if (!k.revoked) u.active_keys++;
    u.total_requests += k.requests_count || 0;
    u.total_tokens += k.tokens_used || 0;
    u.total_documents += k.documents_ingested || 0;
    u.total_searches += k.searches_performed || 0;
    u.total_errors += k.errors_count || 0;
    if (
      k.last_used_at &&
      (!u.last_used_at || k.last_used_at > u.last_used_at)
    ) {
      u.last_used_at = k.last_used_at;
    }
  }

  const users = (profiles || []).map((p) => ({
    ...p,
    usage: userKeys[p.id] || {
      total_keys: 0,
      active_keys: 0,
      total_requests: 0,
      total_tokens: 0,
      total_documents: 0,
      total_searches: 0,
      total_errors: 0,
      last_used_at: null,
    },
  }));

  return NextResponse.json(users);
}
