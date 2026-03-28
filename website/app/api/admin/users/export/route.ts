import { NextRequest, NextResponse } from "next/server";
import { verifyAdmin } from "@/lib/admin-auth";
import { supabase } from "@/lib/supabase";

// GET /api/admin/users/export — export users as CSV
export async function GET(req: NextRequest) {
  const denied = await verifyAdmin(req);
  if (denied) return denied;

  const { data, error } = await supabase()
    .from("profiles")
    .select("*")
    .order("created_at", { ascending: false });

  if (error) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }

  const rows = data || [];
  const headers = [
    "id",
    "email",
    "role",
    "created_at",
    "notify_quota_warning",
    "notify_quota_exceeded",
    "notify_weekly_digest",
  ];

  const csvLines = [headers.join(",")];
  for (const row of rows) {
    const line = headers.map((h) => {
      const val = row[h];
      if (val === null || val === undefined) return "";
      const str = String(val);
      return `"${str.replace(/"/g, '""')}"`;
    });
    csvLines.push(line.join(","));
  }

  return new NextResponse(csvLines.join("\n"), {
    headers: {
      "Content-Type": "text/csv",
      "Content-Disposition": "attachment; filename=users.csv",
    },
  });
}
