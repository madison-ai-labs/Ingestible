import { NextRequest, NextResponse } from "next/server";
import { verifyAdmin } from "@/lib/admin-auth";
import { supabase } from "@/lib/supabase";

// GET /api/admin/tiers — list all tier limits
export async function GET(req: NextRequest) {
  const denied = await verifyAdmin(req);
  if (denied) return denied;

  const { data, error } = await supabase()
    .from("tier_limits")
    .select("*")
    .order("tier");

  if (error) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }

  return NextResponse.json(data);
}

// PATCH /api/admin/tiers — update tier limits
export async function PATCH(req: NextRequest) {
  const denied = await verifyAdmin(req);
  if (denied) return denied;

  const body = await req.json().catch(() => ({}));

  if (!body.tier || !["free", "premium", "admin"].includes(body.tier)) {
    return NextResponse.json(
      { error: "Valid tier required (free, premium, admin)" },
      { status: 400 }
    );
  }

  const allowedFields = [
    "requests_per_day",
    "requests_per_minute",
    "max_documents",
    "max_keys",
    "max_file_size_mb",
    "enrichment_enabled",
  ];

  const updates: Record<string, unknown> = {};
  for (const field of allowedFields) {
    if (body[field] !== undefined) {
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
    .from("tier_limits")
    .update(updates)
    .eq("tier", body.tier)
    .select()
    .single();

  if (error) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }

  return NextResponse.json(data);
}
