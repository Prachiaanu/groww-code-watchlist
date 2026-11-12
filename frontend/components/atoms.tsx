import type { Freshness, Severity, Signal } from "@/lib/types";

const SEV_STYLE: Record<Severity, string> = {
  high: "bg-red-100 text-red-700 dark:bg-red-950/60 dark:text-red-300 ring-red-300/50",
  medium: "bg-amber-100 text-amber-800 dark:bg-amber-950/60 dark:text-amber-300 ring-amber-300/50",
  low: "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300 ring-slate-300/40",
  none: "bg-slate-50 text-slate-400 dark:bg-slate-900 dark:text-slate-500 ring-slate-200/30",
};

export function SeverityPill({ severity, score }: { severity: Severity; score: number }) {
  const label = severity === "none" ? "quiet" : severity;
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-semibold uppercase tracking-wide ring-1 ${SEV_STYLE[severity]}`}
      title={`Attention score ${score}/100`}
    >
      {label}
      <span className="opacity-60 font-mono normal-case">{Math.round(score)}</span>
    </span>
  );
}

const FRESH_STYLE: Record<Freshness, { dot: string; text: string; label: string }> = {
  FRESH: { dot: "bg-emerald-500", text: "text-emerald-600 dark:text-emerald-400", label: "live" },
  DELAYED: { dot: "bg-amber-500", text: "text-amber-600 dark:text-amber-400", label: "delayed" },
  STALE: { dot: "bg-red-500", text: "text-red-600 dark:text-red-400", label: "stale" },
};

export function FreshnessBadge({ freshness, ageSeconds }: { freshness: Freshness; ageSeconds?: number }) {
  const s = FRESH_STYLE[freshness];
  return (
    <span className={`inline-flex items-center gap-1 text-xs font-medium ${s.text}`} title={ageSeconds != null ? `${ageSeconds}s old` : undefined}>
      <span className={`h-1.5 w-1.5 rounded-full ${s.dot} ${freshness === "FRESH" ? "animate-pulse" : ""}`} />
      {s.label}
    </span>
  );
}

export function Sparkline({ values, className = "" }: { values: number[]; className?: string }) {
  if (!values || values.length < 2) {
    return <div className={`h-6 w-20 ${className}`} aria-hidden />;
  }
  const w = 80;
  const h = 24;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  const step = w / (values.length - 1);
  const pts = values.map((v, i) => `${(i * step).toFixed(1)},${(h - ((v - min) / range) * h).toFixed(1)}`).join(" ");
  const up = values[values.length - 1] >= values[0];
  const color = up ? "#16a34a" : "#dc2626";
  return (
    <svg width={w} height={h} className={className} viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" aria-hidden>
      <polyline points={pts} fill="none" stroke={color} strokeWidth="1.5" strokeLinejoin="round" strokeLinecap="round" />
    </svg>
  );
}

export function SignalChips({ signals, max = 3 }: { signals: Signal[]; max?: number }) {
  if (!signals.length) return null;
  return (
    <div className="flex flex-wrap gap-1.5">
      {signals.slice(0, max).map((s, i) => {
        const tone =
          s.direction === "up"
            ? "border-emerald-300/60 text-emerald-700 dark:text-emerald-300"
            : s.direction === "down"
              ? "border-red-300/60 text-red-700 dark:text-red-300"
              : "border-slate-300/60 text-slate-600 dark:text-slate-300";
        return (
          <span key={i} className={`rounded-md border bg-white/40 dark:bg-white/5 px-2 py-0.5 text-xs ${tone}`}>
            {s.reason}
          </span>
        );
      })}
    </div>
  );
}
