import { NextRequest, NextResponse } from "next/server";
import { verifyAdmin, generateApiKey } from "@/lib/admin-auth";
import { supabase } from "@/lib/supabase";

// GET /api/admin/keys — list all keys
export async function GET(req: NextRequest) {
  const denied = await verifyAdmin(req);
  if (denied) return denied;

  const { data, error } = await supabase()
    .from("api_keys")
    .select("*")
    .order("created_at", { ascending: false });

  if (error) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }

  // Mask keys in list view (only show prefix + last 4 chars)
  const masked = (data || []).map((k) => ({
    ...k,
    key: k.key.slice(0, 3) + "..." + k.key.slice(-4),
  }));

  return NextResponse.json(masked);
}

// POST /api/admin/keys — generate a new key
export async function POST(req: NextRequest) {
  const denied = await verifyAdmin(req);
  if (denied) return denied;

  const body = await req.json().catch(() => ({}));
  const label = body.label || "Untitled";

  const key = generateApiKey();

  const { data, error } = await supabase()
    .from("api_keys")
    .insert({ key, label })
    .select()
    .single();

  if (error) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }

  // Return the full key only on creation — this is the only time it's visible
  return NextResponse.json(data, { status: 201 });
}
