"use client";

import { useEffect, useState, useRef } from "react";
import Link from "next/link";
import { getSupabase } from "@/lib/supabase-browser";
import type { User } from "@supabase/supabase-js";

export function AuthButton() {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const [open, setOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const supabase = getSupabase();

    supabase.auth.getUser().then((res: { data: { user: User | null } }) => {
      setUser(res.data.user);
      setLoading(false);
    });

    const { data: { subscription } } = supabase.auth.onAuthStateChange(
      (_event: string, session: { user: User } | null) => {
        setUser(session?.user ?? null);
      }
    );

    return () => subscription.unsubscribe();
  }, []);

  // Close dropdown on outside click
  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    if (open) document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, [open]);

  if (loading) {
    return (
      <div className="w-8 h-8 rounded-full bg-zinc-800/50 animate-pulse" />
    );
  }

  if (!user) {
    return (
      <Link
        href="/dashboard"
        className="inline-flex items-center gap-2 text-sm font-semibold px-5 py-2 rounded-lg bg-amber-500 text-zinc-950 hover:bg-amber-400 transition-colors"
      >
        Sign in
      </Link>
    );
  }

  const avatarUrl =
    user.user_metadata?.avatar_url || user.user_metadata?.picture;
  const name =
    user.user_metadata?.full_name || user.user_metadata?.name || "";
  const email = user.email || "";
  const initial = (name || email).charAt(0).toUpperCase();

  async function handleSignOut() {
    const supabase = getSupabase();
    await supabase.auth.signOut();
    setOpen(false);
    window.location.href = "/";
  }

  return (
    <div className="relative" ref={menuRef}>
      <button
        onClick={() => setOpen(!open)}
        className="flex items-center gap-2 rounded-full focus:outline-none focus:ring-2 focus:ring-amber-400/50 focus:ring-offset-2 focus:ring-offset-zinc-950"
      >
        {avatarUrl ? (
          <img
            src={avatarUrl}
            alt="Avatar"
            className="w-8 h-8 rounded-full border border-zinc-700 hover:border-zinc-500 transition-colors"
          />
        ) : (
          <div className="w-8 h-8 rounded-full bg-zinc-800 border border-zinc-700 hover:border-zinc-500 transition-colors flex items-center justify-center">
            <span className="text-zinc-300 text-sm font-medium">{initial}</span>
          </div>
        )}
      </button>

      {open && (
        <div className="absolute right-0 mt-2 w-56 rounded-xl border border-zinc-800 bg-zinc-900 shadow-xl shadow-black/40 z-50 overflow-hidden">
          {/* User info */}
          <div className="px-4 py-3 border-b border-zinc-800">
            <p className="text-sm font-medium text-zinc-200 truncate">
              {name || "Account"}
            </p>
            <p className="text-xs text-zinc-500 truncate">{email}</p>
          </div>

          {/* Links */}
          <div className="py-1">
            <Link
              href="/dashboard"
              onClick={() => setOpen(false)}
              className="flex items-center gap-3 px-4 py-2.5 text-sm text-zinc-300 hover:bg-zinc-800 hover:text-zinc-100 transition-colors"
            >
              <svg className="w-4 h-4 text-zinc-500" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" d="M3.75 6A2.25 2.25 0 016 3.75h2.25A2.25 2.25 0 0110.5 6v2.25a2.25 2.25 0 01-2.25 2.25H6a2.25 2.25 0 01-2.25-2.25V6zM3.75 15.75A2.25 2.25 0 016 13.5h2.25a2.25 2.25 0 012.25 2.25V18a2.25 2.25 0 01-2.25 2.25H6A2.25 2.25 0 013.75 18v-2.25zM13.5 6a2.25 2.25 0 012.25-2.25H18A2.25 2.25 0 0120.25 6v2.25A2.25 2.25 0 0118 10.5h-2.25a2.25 2.25 0 01-2.25-2.25V6zM13.5 15.75a2.25 2.25 0 012.25-2.25H18a2.25 2.25 0 012.25 2.25V18A2.25 2.25 0 0118 20.25h-2.25A2.25 2.25 0 0113.5 18v-2.25z" />
              </svg>
              Dashboard
            </Link>
            <Link
              href="/dashboard/settings"
              onClick={() => setOpen(false)}
              className="flex items-center gap-3 px-4 py-2.5 text-sm text-zinc-300 hover:bg-zinc-800 hover:text-zinc-100 transition-colors"
            >
              <svg className="w-4 h-4 text-zinc-500" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" d="M9.594 3.94c.09-.542.56-.94 1.11-.94h2.593c.55 0 1.02.398 1.11.94l.213 1.281c.063.374.313.686.645.87.074.04.147.083.22.127.324.196.72.257 1.075.124l1.217-.456a1.125 1.125 0 011.37.49l1.296 2.247a1.125 1.125 0 01-.26 1.431l-1.003.827c-.293.24-.438.613-.431.992a6.759 6.759 0 010 .255c-.007.378.138.75.43.99l1.005.828c.424.35.534.954.26 1.43l-1.298 2.247a1.125 1.125 0 01-1.369.491l-1.217-.456c-.355-.133-.75-.072-1.076.124a6.57 6.57 0 01-.22.128c-.331.183-.581.495-.644.869l-.213 1.28c-.09.543-.56.941-1.11.941h-2.594c-.55 0-1.02-.398-1.11-.94l-.213-1.281c-.062-.374-.312-.686-.644-.87a6.52 6.52 0 01-.22-.127c-.325-.196-.72-.257-1.076-.124l-1.217.456a1.125 1.125 0 01-1.369-.49l-1.297-2.247a1.125 1.125 0 01.26-1.431l1.004-.827c.292-.24.437-.613.43-.992a6.932 6.932 0 010-.255c.007-.378-.138-.75-.43-.99l-1.004-.828a1.125 1.125 0 01-.26-1.43l1.297-2.247a1.125 1.125 0 011.37-.491l1.216.456c.356.133.751.072 1.076-.124.072-.044.146-.087.22-.128.332-.183.582-.495.644-.869l.214-1.281z" />
                <path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
              </svg>
              Settings
            </Link>
          </div>

          {/* Sign out */}
          <div className="border-t border-zinc-800 py-1">
            <button
              onClick={handleSignOut}
              className="flex items-center gap-3 w-full px-4 py-2.5 text-sm text-zinc-400 hover:bg-zinc-800 hover:text-zinc-100 transition-colors"
            >
              <svg className="w-4 h-4 text-zinc-500" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" d="M15.75 9V5.25A2.25 2.25 0 0013.5 3h-6a2.25 2.25 0 00-2.25 2.25v13.5A2.25 2.25 0 007.5 21h6a2.25 2.25 0 002.25-2.25V15m3 0l3-3m0 0l-3-3m3 3H9" />
              </svg>
              Sign out
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
