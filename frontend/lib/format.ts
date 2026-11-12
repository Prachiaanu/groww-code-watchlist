// Presentation helpers. Money in Indian grouping, signed percentages, relative time.

export function formatINR(value: number, currency = "INR"): string {
  try {
    return new Intl.NumberFormat("en-IN", {
      style: "currency",
      currency,
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }).format(value);
  } catch {
    return `₹${value.toFixed(2)}`;
  }
}

export function formatPct(pct: number, digits = 2): string {
  const s = pct >= 0 ? "+" : "";
  return `${s}${pct.toFixed(digits)}%`;
}

export function formatCompact(n: number): string {
  return new Intl.NumberFormat("en-IN", { notation: "compact", maximumFractionDigits: 1 }).format(n);
}

export function timeAgo(iso: string | null, nowMs?: number): string {
  if (!iso) return "—";
  const then = new Date(iso).getTime();
  const now = nowMs ?? Date.now();
  const s = Math.max(0, Math.round((now - then) / 1000));
  if (s < 5) return "just now";
  if (s < 60) return `${s}s ago`;
  const m = Math.round(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.round(m / 60);
  if (h < 24) return `${h}h ago`;
  const d = Math.round(h / 24);
  return `${d}d ago`;
}

export const dirClass = (v: number) => (v > 0 ? "text-up" : v < 0 ? "text-down" : "text-slate-500");
