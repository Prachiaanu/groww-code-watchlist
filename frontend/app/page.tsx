"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { AddSymbol } from "@/components/AddSymbol";
import { AttentionSummary } from "@/components/AttentionSummary";
import { Header } from "@/components/Header";
import { LoginCard } from "@/components/LoginCard";
import { WatchCard } from "@/components/WatchCard";
import { WhileAwayPanel } from "@/components/WhileAwayPanel";
import type { Session, WatchItem } from "@/lib/types";
import { useWatchlist } from "@/lib/useWatchlist";

const SESSION_KEY = "wl_session";
type SortMode = "attention" | "az" | "added";

export default function Page() {
  const [mounted, setMounted] = useState(false);
  const [session, setSession] = useState<Session | null>(null);
  const [nowMs, setNowMs] = useState(0);
  const [sort, setSort] = useState<SortMode>("attention");

  useEffect(() => {
    setMounted(true);
    setNowMs(Date.now());
    try {
      const raw = localStorage.getItem(SESSION_KEY);
      if (raw) setSession(JSON.parse(raw));
    } catch {
      /* ignore */
    }
    const t = setInterval(() => setNowMs(Date.now()), 1000);
    return () => clearInterval(t);
  }, []);

  const login = useCallback((s: Session) => {
    localStorage.setItem(SESSION_KEY, JSON.stringify(s));
    setSession(s);
  }, []);
  const logout = useCallback(() => {
    localStorage.removeItem(SESSION_KEY);
    setSession(null);
  }, []);

  // logout on an expired/invalid stored token, so we never hang on "Loading…"
  const { view, status, actions, history } = useWatchlist(session?.token ?? null, logout);

  const ordered: WatchItem[] = useMemo(() => {
    if (!view) return [];
    const items = view.items;
    if (sort === "az") return [...items].sort((a, b) => a.symbol.localeCompare(b.symbol));
    if (sort === "added") return items;
    const rank = new Map(view.attention_order.map((s, i) => [s, i]));
    return [...items].sort((a, b) => (rank.get(a.symbol) ?? 999) - (rank.get(b.symbol) ?? 999));
  }, [view, sort]);

  if (!mounted) return null;
  if (!session) return <main className="min-h-screen px-4"><LoginCard onLogin={login} /></main>;

  const existing = new Set(view?.items.map((i) => i.symbol) ?? []);

  return (
    <main className="mx-auto max-w-6xl px-4 py-6">
      <Header view={view} token={session.token} status={status} nowMs={nowMs} onLogout={logout} />

      {!view ? (
        <div className="mt-16 text-center text-slate-500">Loading your watchlist…</div>
      ) : (
        <div className="mt-6 space-y-6">
          <WhileAwayPanel view={view} nowMs={nowMs} onMarkAll={() => actions.markSeen()} />

          <AttentionSummary view={view} />

          <div className="flex flex-wrap items-center justify-between gap-3">
            <AddSymbol existing={existing} onAdd={(s) => actions.addItem(s)} />
            <label className="flex items-center gap-2 text-sm text-slate-500">
              Sort
              <select
                value={sort}
                onChange={(e) => setSort(e.target.value as SortMode)}
                className="rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-900 px-2 py-1.5 text-sm"
              >
                <option value="attention">By attention</option>
                <option value="az">A–Z</option>
                <option value="added">Order added</option>
              </select>
            </label>
          </div>

          {ordered.length === 0 ? (
            <div className="rounded-2xl border border-dashed border-slate-300 dark:border-slate-700 p-12 text-center text-slate-500">
              Your watchlist is empty. Search above to add a stock.
            </div>
          ) : (
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {ordered.map((item) => (
                <WatchCard
                  key={item.symbol}
                  item={item}
                  history={history.get(item.symbol) ?? []}
                  nowMs={nowMs}
                  onRemove={(s) => actions.removeItem(s)}
                  onSetAlerts={(s, body) => actions.setAlerts(s, body)}
                />
              ))}
            </div>
          )}

          <footer className="pt-6 text-center text-xs text-slate-400">
            Prices are simulated for this demo · “Meaningful” = volatility-normalised, not a flat % · Activity log is hash-chained &amp; verifiable
          </footer>
        </div>
      )}
    </main>
  );
}
