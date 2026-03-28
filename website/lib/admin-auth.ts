import { NextRequest, NextResponse } from "next/server";
import crypto from "crypto";
import { createClient } from "@supabase/supabase-js";

const ADMIN_EMAILS = ["lisa@tastehub.io", "martyna@tastehub.io"];

/**
 * Verify admin access via Supabase access token.
 * The client sends the Supabase session access_token as Bearer token.
 * We verify it and check if the user's email is in the admin list.
 */
export async function verifyAdmin(req: NextRequest): Promise<NextResponse | null> {
  const auth = req.headers.get("authorization");
  if (!auth || !auth.startsWith("Bearer ")) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  const token = auth.slice(7);

  const supabaseUrl = process.env.SUPABASE_URL || process.env.NEXT_PUBLIC_SUPABASE_URL;
  const supabaseServiceKey = process.env.SUPABASE_SERVICE_ROLE_KEY;

  if (!supabaseUrl || !supabaseServiceKey) {
    return NextResponse.json({ error: "Server misconfigured" }, { status: 500 });
  }

  const supabase = createClient(supabaseUrl, supabaseServiceKey);

  const { data: { user }, error } = await supabase.auth.getUser(token);

  if (error || !user) {
    return NextResponse.json({ error: "Invalid session" }, { status: 401 });
  }

  if (!user.email || !ADMIN_EMAILS.includes(user.email.toLowerCase())) {
    return NextResponse.json({ error: "Forbidden" }, { status: 403 });
  }

  return null; // authorized
}

export function generateApiKey(): string {
  const prefix = "ik_";
  const bytes = crypto.randomBytes(32);
  return prefix + bytes.toString("base64url");
}
