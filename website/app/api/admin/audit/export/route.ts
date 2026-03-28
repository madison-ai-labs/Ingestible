import { NextRequest, NextResponse } from "next/server";
import { verifyAdmin } from "@/lib/admin-auth";
import { supabase } from "@/lib/supabase";

// GET /api/admin/audit/export — export audit log as CSV
export async function GET(req: NextRequest) {
  const denied = await verifyAdmin(req);
  if (denied) return denied;

  const { data, error } = await supabase()
    .from("audit_log")
    .select("*")
    .order("created_at", { ascending: false });

  if (error) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }

  const rows = data || [];
  const headers = [
    "id",
    "actor_id",
    "actor_email",
    "event",
    "target_type",
    "target_id",
    "metadata",
    "ip_address",
    "user_agent",
    "created_at",
  ];

  const csvLines = [headers.join(",")];
  for (const row of rows) {
    const line = headers.map((h) => {
      const val = row[h];
      if (val === null || val === undefined) return "";
      const str = typeof val === "object" ? JSON.stringify(val) : String(val);
      return `"${str.replace(/"/g, '""')}"`;
    });
    csvLines.push(line.join(","));
  }

  return new NextResponse(csvLines.join("\n"), {
    headers: {
      "Content-Type": "text/csv",
      "Content-Disposition": "attachment; filename=audit_log.csv",
    },
  });
}
