"use client";

import { useEffect, useRef, useState } from "react";

import { dirClass, formatINR, formatPct, timeAgo } from "@/lib/format";
import type { WatchItem } from "@/lib/types";

import { FreshnessBadge, SeverityPill, SignalChips, Sparkline } from "./atoms";

export function WatchCard({
  item,
  history,
  nowMs,
  onRemove,
  onSetAlerts,
}: {
  item: WatchItem;
  history: number[];
  nowMs: number;
  onRemove: (symbol: string) => Promise<unknown> | void;
  onSetAlerts: (symbol: string, body: { alert_above?: number | null; alert_below?: number | null; clear_alerts?: boolean }) => Promise<unknown>;
}) {
  const a = item.attention;
  const ss = a.since_seen;
  const meaningful = a.is_meaningful;

  // subtle flash when the price ticks
  const prev = useRef(item.price);
  const [flash, setFlash] = useState<"" | "up" | "down">("");
  useEffect(() => {
    if (item.price !== prev.current) {
      setFlash(item.price > prev.current ? "up" : "down");
      prev.current = item.price;
      const t = setTimeout(() => setFlash(""), 700);
      return () => clearTimeout(t);
    }
  }, [item.price]);

  const [editing, setEditing] = useState(false);
  const [removeErr, setRemoveErr] = useState<string | null>(null);
  const remove = async () => {
    setRemoveErr(null);
    try {
      await onRemove(item.symbol);
    } catch (e) {
      setRemoveErr(e instanceof Error ? e.message : "Could not remove");
    }
  };

  return (
    <div
      className={`rounded-2xl border p-4 shadow-sm transition-colors ${
        meaningful
          ? "border-brand/40 bg-white dark:bg-slate-900"
          : "border-slate-200/70 dark:border-slate-800 bg-white/70 dark:bg-slate-900/60"
      }`}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className="font-semibold tracking-tight">{item.symbol}</span>
            <span className="truncate text-xs text-slate-400">{item.sector}</span>
          </div>
          <div className="truncate text-xs text-slate-500 dark:text-slate-400">{item.name}</div>
        </div>
        <SeverityPill severity={a.severity} score={a.attention_score} />
      </div>

      <div className="mt-3 flex items-end justify-between gap-3">
        <div>
          <div className={`text-2xl font-semibold tabular-nums rounded px-1 -mx-1 ${flash === "up" ? "animate-flashup" : flash === "down" ? "animate-flashdown" : ""}`}>
            {formatINR(item.price, item.currency)}
          </div>
          <div className={`text-sm font-medium tabular-nums ${dirClass(item.day_change_pct)}`}>
            {formatPct(item.day_change_pct)} <span className="text-slate-400">today</span>
          </div>
        </div>
        <div className="flex flex-col items-end gap-1">
          <Sparkline values={history} />
          <FreshnessBadge freshness={item.freshness} ageSeconds={item.age_seconds} />
        </div>
      </div>

      {ss && Math.abs(ss.change_pct) >= 0.01 && (
        <div className="mt-3 rounded-lg bg-slate-50 dark:bg-slate-800/60 px-3 py-2 text-sm">
          <span className="text-slate-500 dark:text-slate-400">Since you looked ({timeAgo(ss.last_seen_at, nowMs)}): </span>
          <span className={`font-medium tabular-nums ${dirClass(ss.change_pct)}`}>
            {formatPct(ss.change_pct)} ({ss.change_abs >= 0 ? "+" : ""}
            {formatINR(ss.change_abs, item.currency)})
          </span>
        </div>
      )}

      {a.signals.length > 0 && (
        <div className="mt-3">
          <SignalChips signals={a.signals} />
        </div>
      )}

      {item.conflict && (
        <div className="mt-3 rounded-lg border border-amber-300/60 bg-amber-50 dark:bg-amber-950/40 px-3 py-2 text-xs text-amber-800 dark:text-amber-300">
          ⚠ Sources disagree by {item.conflict.divergence_pct}% —{" "}
          {item.conflict.views.map((v) => `${v.source.replace("sim-", "")} ${formatINR(v.price, item.currency)}`).join(" vs ")}
        </div>
      )}

      {/* alerts */}
      {!editing ? (
        <div className="mt-3 flex items-center justify-between text-xs">
          <div className="text-slate-500 dark:text-slate-400">
            {item.alert_above || item.alert_below ? (
              <span>
                Alerts:{" "}
                {item.alert_above ? <span className="font-medium">↑ {formatINR(item.alert_above, item.currency)} </span> : null}
                {item.alert_below ? <span className="font-medium">↓ {formatINR(item.alert_below, item.currency)}</span> : null}
              </span>
            ) : (
              <span className="text-slate-400">No alerts set</span>
            )}
          </div>
          <div className="flex gap-3">
            <button onClick={() => setEditing(true)} className="text-brand-600 hover:underline">
              {item.alert_above || item.alert_below ? "Edit alert" : "Set alert"}
            </button>
            <button onClick={remove} className="text-slate-400 hover:text-red-600">
              Remove
            </button>
          </div>
        </div>
      ) : (
        <AlertEditor item={item} onSetAlerts={onSetAlerts} onClose={() => setEditing(false)} />
      )}
      {removeErr && <p className="mt-2 text-xs text-red-600">{removeErr}</p>}
    </div>
  );
}

function AlertEditor({
  item,
  onSetAlerts,
  onClose,
}: {
  item: WatchItem;
  onSetAlerts: (symbol: string, body: { alert_above?: number | null; alert_below?: number | null; clear_alerts?: boolean }) => Promise<unknown>;
  onClose: () => void;
}) {
  const [above, setAbove] = useState(item.alert_above?.toString() ?? "");
  const [below, setBelow] = useState(item.alert_below?.toString() ?? "");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const save = async () => {
    setBusy(true);
    setErr(null);
    try {
      await onSetAlerts(item.symbol, {
        alert_above: above ? Number(above) : null,
        alert_below: below ? Number(below) : null,
      });
      onClose();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Could not save alert");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mt-3 rounded-lg border border-slate-200 dark:border-slate-700 p-3 text-xs">
      <div className="flex items-center gap-2">
        <label className="flex items-center gap-1">
          <span className="text-slate-500">Above ₹</span>
          <input value={above} onChange={(e) => setAbove(e.target.value)} inputMode="decimal" className="w-20 rounded border border-slate-300 dark:border-slate-600 bg-transparent px-1.5 py-1" />
        </label>
        <label className="flex items-center gap-1">
          <span className="text-slate-500">Below ₹</span>
          <input value={below} onChange={(e) => setBelow(e.target.value)} inputMode="decimal" className="w-20 rounded border border-slate-300 dark:border-slate-600 bg-transparent px-1.5 py-1" />
        </label>
      </div>
      <div className="mt-2 flex gap-3">
        <button disabled={busy} onClick={save} className="rounded bg-brand px-2 py-1 font-medium text-white disabled:opacity-50">
          Save
        </button>
        <button
          onClick={async () => {
            setErr(null);
            try {
              await onSetAlerts(item.symbol, { clear_alerts: true });
              onClose();
            } catch (e) {
              setErr(e instanceof Error ? e.message : "Could not clear alert");
            }
          }}
          className="text-slate-500 hover:underline"
        >
          Clear
        </button>
        <button onClick={onClose} className="text-slate-400 hover:underline">
          Cancel
        </button>
      </div>
      {err && <p className="mt-2 text-red-600">{err}</p>}
    </div>
  );
}
