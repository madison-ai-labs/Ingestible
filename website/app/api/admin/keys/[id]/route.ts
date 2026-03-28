import { NextRequest, NextResponse } from "next/server";
import { verifyAdmin } from "@/lib/admin-auth";
import { supabase } from "@/lib/supabase";

// PATCH /api/admin/keys/[id] — revoke or update a key
export async function PATCH(
  req: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const denied = await verifyAdmin(req);
  if (denied) return denied;

  const { id } = await params;
  const body = await req.json().catch(() => ({}));

  const updates: Record<string, unknown> = {};
  if (typeof body.revoked === "boolean") updates.revoked = body.revoked;
  if (typeof body.label === "string") updates.label = body.label;

  if (Object.keys(updates).length === 0) {
    return NextResponse.json({ error: "No updates provided" }, { status: 400 });
  }

  const { data, error } = await supabase()
    .from("api_keys")
    .update(updates)
    .eq("id", id)
    .select()
    .single();

  if (error) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }

  return NextResponse.json(data);
}

// DELETE /api/admin/keys/[id] — permanently delete a key
export async function DELETE(
  req: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const denied = await verifyAdmin(req);
  if (denied) return denied;

  const { id } = await params;

  const { error } = await supabase().from("api_keys").delete().eq("id", id);

  if (error) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }

  return NextResponse.json({ ok: true });
}
