import { createBrowserClient } from "@supabase/ssr";

let client: ReturnType<typeof createBrowserClient> | null = null;

export function getSupabase() {
  if (typeof window === "undefined") {
    // During SSR/prerender — return a proxy that won't crash but also won't do anything.
    // Real calls only happen in useEffect (client-side).
    return new Proxy({} as ReturnType<typeof createBrowserClient>, {
      get: () => () => ({ data: { user: null, session: null, subscription: { unsubscribe: () => {} } }, error: null }),
    });
  }
  if (!client) {
    client = createBrowserClient(
      process.env.NEXT_PUBLIC_SUPABASE_URL!,
      process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!
    );
  }
  return client;
}
