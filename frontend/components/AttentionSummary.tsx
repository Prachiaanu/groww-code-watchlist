import type { WatchlistView } from "@/lib/types";

function Stat({ label, value, tone = "" }: { label: string; value: string | number; tone?: string }) {
  return (
    <div className="rounded-xl border border-slate-200/70 dark:border-slate-800 bg-white dark:bg-slate-900 px-3 py-2">
      <div className={`text-lg font-semibold tabular-nums ${tone}`}>{value}</div>
      <div className="text-xs text-slate-500 dark:text-slate-400">{label}</div>
    </div>
  );
}

export function AttentionSummary({ view }: { view: WatchlistView }) {
  const s = view.summary;
  const issues = s.data_issues.stale + s.data_issues.delayed + s.data_issues.conflict;
  return (
    <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-5">
      <Stat label="Tracking" value={s.total} />
      <Stat label="Need attention" value={s.meaningful} tone={s.meaningful ? "text-brand-600" : ""} />
      <Stat label="High / Medium" value={`${s.by_severity.high} / ${s.by_severity.medium}`} tone={s.by_severity.high ? "text-red-600" : ""} />
      <Stat
        label="Data issues"
        value={issues}
        tone={issues ? "text-amber-600" : "text-slate-400"}
      />
      <Stat label="Delayed / Stale" value={`${s.data_issues.delayed} / ${s.data_issues.stale}`} tone={s.data_issues.stale ? "text-red-600" : ""} />
    </div>
  );
}
