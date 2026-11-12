"use client";

import { useState } from "react";

import { api } from "@/lib/api";
import type { Session } from "@/lib/types";

export function LoginCard({ onLogin }: { onLogin: (s: Session) => void }) {
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      onLogin(await api.login(email.trim(), name.trim()));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Login failed. Is the backend running?");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mx-auto mt-24 max-w-sm rounded-2xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 p-6 shadow-sm">
      <div className="mb-1 flex items-center gap-2">
        <div className="grid h-9 w-9 place-items-center rounded-xl bg-brand text-white font-bold">W</div>
        <h1 className="text-lg font-semibold">Smart Market Watchlist</h1>
      </div>
      <p className="mb-5 text-sm text-slate-500 dark:text-slate-400">
        Sign in with your email — your watchlist and “since you last checked” baseline follow you across devices.
      </p>
      <form onSubmit={submit} className="space-y-3">
        <input
          type="email"
          required
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          placeholder="you@example.com"
          className="w-full rounded-xl border border-slate-300 dark:border-slate-700 bg-transparent px-3 py-2.5 text-sm outline-none focus:ring-2 focus:ring-brand/40"
        />
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="Display name (optional)"
          className="w-full rounded-xl border border-slate-300 dark:border-slate-700 bg-transparent px-3 py-2.5 text-sm outline-none focus:ring-2 focus:ring-brand/40"
        />
        <button
          disabled={busy}
          className="w-full rounded-xl bg-brand px-3 py-2.5 text-sm font-semibold text-white hover:bg-brand-600 disabled:opacity-50"
        >
          {busy ? "Signing in…" : "Continue"}
        </button>
        {error && <p className="text-sm text-red-600">{error}</p>}
      </form>
      <p className="mt-4 text-xs text-slate-400">No password — this is a demo. Prices are simulated (clearly labelled), not live market data.</p>
    </div>
  );
}
