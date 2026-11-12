"use client";

import { useState } from "react";

import { dirClass, formatPct, timeAgo } from "@/lib/format";
import type { WatchlistView } from "@/lib/types";

// The product's headline answer to "what changed since I last looked?".
export function WhileAwayPanel({
  view,
  nowMs,
  onMarkAll,
}: {
  view: WatchlistView;
  nowMs: number;
  onMarkAll: () => Promise<unknown>;
}) {
  const [busy, setBusy] = useState(false);
  const { summary, items, while_away } = view;

  // Drive the hero off the same definition as the "Need attention" summary tile
  // (is_meaningful), so the count here and the tile never disagree.
  const movers = items
    .filter((it) => it.attention.is_meaningful)
    .sort((a, b) => b.attention.attention_score - a.attention.attention_score);

  const firstVisit = summary.last_reviewed_at === null;
  const caughtUp = !firstVisit && movers.length === 0 && while_away.length === 0;

  const markAll = async () => {
    setBusy(true);
    try {
      await onMarkAll();
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="rounded-2xl border border-brand/30 bg-gradient-to-b from-brand/5 to-transparent p-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold">
            {firstVisit
              ? "Your watchlist"
              : caughtUp
                ? "You're all caught up ✓"
                : `${movers.length} ${movers.length === 1 ? "stock needs" : "stocks need"} your attention`}
          </h2>
          <p className="text-sm text-slate-500 dark:text-slate-400">
            {firstVisit
              ? "Scan the movers, then mark them reviewed to set your baseline."
              : `Since you last reviewed ${timeAgo(summary.last_reviewed_at, nowMs)}.`}
          </p>
        </div>
        <button
          onClick={markAll}
          disabled={busy || view.items.length === 0}
          className="rounded-xl bg-brand px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-brand-600 disabled:opacity-50"
        >
          {busy ? "Saving…" : "Mark all as reviewed"}
        </button>
      </div>

      {!caughtUp && movers.length > 0 && (
        <div className="mt-4 grid gap-2 sm:grid-cols-2">
          {movers.slice(0, 6).map((it) => {
            const ss = it.attention.since_seen;
            return (
              <div key={it.symbol} className="flex items-center justify-between rounded-xl bg-white dark:bg-slate-900 border border-slate-200/70 dark:border-slate-800 px-3 py-2">
                <div className="min-w-0">
                  <div className="font-medium">{it.symbol}</div>
                  <div className="truncate text-xs text-slate-500 dark:text-slate-400">{it.attention.primary_reason ?? "—"}</div>
                </div>
                {ss ? (
                  <div className={`text-sm font-semibold tabular-nums ${dirClass(ss.change_pct)}`}>{formatPct(ss.change_pct)}</div>
                ) : (
                  <div className={`text-sm font-semibold tabular-nums ${dirClass(it.day_change_pct)}`}>{formatPct(it.day_change_pct)}</div>
                )}
              </div>
            );
          })}
        </div>
      )}

      {while_away.length > 0 && (
        <details className="mt-4 group">
          <summary className="cursor-pointer text-sm font-medium text-slate-600 dark:text-slate-300">
            Market events while you were away ({while_away.length}) 🔒
          </summary>
          <ul className="mt-2 divide-y divide-slate-100 dark:divide-slate-800 rounded-xl border border-slate-200/70 dark:border-slate-800">
            {while_away.slice(0, 12).map((e) => (
              <li key={e.seq} className="flex items-center justify-between px-3 py-2 text-sm">
                <span>
                  <span className="font-medium">{e.symbol}</span>{" "}
                  <span className="text-slate-500 dark:text-slate-400">{e.reason}</span>
                </span>
                <span className="text-xs text-slate-400" title={`chain hash ${e.hash.slice(0, 12)}…`}>
                  {timeAgo(e.created_at, nowMs)}
                </span>
              </li>
            ))}
          </ul>
        </details>
      )}
    </section>
  );
}
