import { createClient, SupabaseClient } from "@supabase/supabase-js";

let _client: SupabaseClient | null = null;

export function supabase(): SupabaseClient {
  if (!_client) {
    const url = process.env.SUPABASE_URL;
    const key = process.env.SUPABASE_SERVICE_ROLE_KEY;
    if (!url || !key) {
      throw new Error("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set");
    }
    _client = createClient(url, key);
  }
  return _client;
}

export interface ApiKey {
  id: string;
  key: string;
  label: string;
  created_at: string;
  last_used_at: string | null;
  revoked: boolean;
  requests_count: number;
}
