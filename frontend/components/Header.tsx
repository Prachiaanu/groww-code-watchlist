"use client";

import { useState } from "react";

import { api } from "@/lib/api";
import { timeAgo } from "@/lib/format";
import type { ConnStatus } from "@/lib/useWatchlist";
import type { WatchlistView } from "@/lib/types";

const CONN: Record<ConnStatus, { dot: string; label: string }> = {
  live: { dot: "bg-emerald-500 animate-pulse", label: "Live" },
  connecting: { dot: "bg-amber-500", label: "Connecting…" },
  error: { dot: "bg-red-500", label: "Reconnecting…" },
};

export function Header({
  view,
  token,
  status,
  nowMs,
  onLogout,
}: {
  view: WatchlistView | null;
  token: string;
  status: ConnStatus;
  nowMs: number;
  onLogout: () => void;
}) {
  const c = CONN[status];
  const [verify, setVerify] = useState<string | null>(null);

  const runVerify = async () => {
    setVerify("checking…");
    try {
      const r = await api.verifyLog(token);
      setVerify(r.ok ? `log intact · ${r.entries} events` : `TAMPERED at #${r.broken_at_seq}`);
    } catch {
      setVerify("verify failed");
    }
    setTimeout(() => setVerify(null), 4000);
  };

  return (
    <header className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-200/70 dark:border-slate-800 pb-4">
      <div className="flex items-center gap-3">
        <div className="grid h-9 w-9 place-items-center rounded-xl bg-brand text-white font-bold">W</div>
        <div>
          <h1 className="text-base font-semibold leading-tight">Smart Watchlist</h1>
          <p className="text-xs text-slate-500 dark:text-slate-400">what changed, and what deserves your attention</p>
        </div>
      </div>
      <div className="flex items-center gap-4 text-sm">
        <span className="inline-flex items-center gap-1.5 text-slate-600 dark:text-slate-300">
          <span className={`h-2 w-2 rounded-full ${c.dot}`} /> {c.label}
        </span>
        {view && <span className="hidden sm:inline text-xs text-slate-400">updated {timeAgo(view.server_time, nowMs)}</span>}
        <button onClick={runVerify} className="text-xs text-slate-500 hover:text-brand-600" title="Verify the tamper-evident activity log">
          {verify ?? "🔒 verify log"}
        </button>
        {view && (
          <div className="flex items-center gap-2">
            <span className="hidden sm:inline text-xs text-slate-400">{view.user.email}</span>
            <button onClick={onLogout} className="rounded-lg border border-slate-300 dark:border-slate-700 px-2 py-1 text-xs hover:bg-slate-50 dark:hover:bg-slate-800">
              Sign out
            </button>
          </div>
        )}
      </div>
    </header>
  );
}
