import { NextRequest, NextResponse } from "next/server";
import { verifyAdmin } from "@/lib/admin-auth";
import { supabase } from "@/lib/supabase";

// PATCH /api/admin/users/[id] — update user role
export async function PATCH(
  req: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const denied = await verifyAdmin(req);
  if (denied) return denied;

  const { id } = await params;
  const body = await req.json().catch(() => ({}));

  const updates: Record<string, unknown> = {};
  if (body.role && ["free", "premium", "admin"].includes(body.role)) {
    updates.role = body.role;
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
    .eq("id", id)
    .select()
    .single();

  if (error) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }

  return NextResponse.json(data);
}
