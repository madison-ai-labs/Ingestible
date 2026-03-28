import { NextRequest, NextResponse } from "next/server";
import { supabase } from "@/lib/supabase";

function getToken(req: NextRequest): string | null {
  const auth = req.headers.get("authorization");
  if (!auth || !auth.startsWith("Bearer ")) return null;
  return auth.slice(7);
}

// GET /api/user/webhooks — list user's webhook subscriptions
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

  const { data, error } = await supabase()
    .from("webhook_subscriptions")
    .select("*")
    .eq("user_id", user.id)
    .order("created_at", { ascending: false });

  if (error) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }

  return NextResponse.json(data);
}

// POST /api/user/webhooks — create a new webhook subscription
export async function POST(req: NextRequest) {
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

  if (!body.url || !Array.isArray(body.events) || body.events.length === 0) {
    return NextResponse.json(
      { error: "url and events[] are required" },
      { status: 400 }
    );
  }

  const { data, error } = await supabase()
    .from("webhook_subscriptions")
    .insert({
      user_id: user.id,
      url: body.url,
      events: body.events,
      secret: body.secret || null,
    })
    .select()
    .single();

  if (error) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }

  return NextResponse.json(data, { status: 201 });
}
