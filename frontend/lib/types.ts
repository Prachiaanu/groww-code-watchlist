// TypeScript mirror of the backend's watchlist view contract (see services/watchlist.py).

export type Freshness = "FRESH" | "DELAYED" | "STALE";
export type Severity = "high" | "medium" | "low" | "none";

export interface SourceView {
  source: string;
  price: number;
  as_of: string;
  freshness: Freshness;
}

export interface Signal {
  type: string;
  direction: "up" | "down" | "neutral";
  score: number;
  reason: string;
  magnitude_pct: number;
  z: number | null;
  as_of: string | null;
}

export interface SinceSeen {
  baseline_price: number;
  current_price: number;
  change_pct: number;
  change_abs: number;
  seconds_away: number;
  last_seen_at: string;
}

export interface Attention {
  symbol: string;
  attention_score: number;
  severity: Severity;
  is_meaningful: boolean;
  primary_reason: string | null;
  since_seen: SinceSeen | null;
  signals: Signal[];
}

export interface WatchItem {
  symbol: string;
  name: string;
  sector: string;
  currency: string;
  price: number;
  prev_close: number;
  day_change_pct: number;
  day_change_abs: number;
  as_of: string;
  received_at: string;
  freshness: Freshness;
  source: string;
  age_seconds: number;
  conflict: { divergence_pct: number; views: SourceView[] } | null;
  sources: SourceView[];
  day_high: number | null;
  day_low: number | null;
  week52_high: number | null;
  week52_low: number | null;
  volume: number;
  alert_above: number | null;
  alert_below: number | null;
  seen: { baseline_price: number; seen_at: string } | null;
  attention: Attention;
}

export interface ActivityEvent {
  seq: number;
  symbol: string;
  type: string;
  direction: string;
  score: number;
  magnitude_pct: number;
  z: number | null;
  reason: string;
  as_of: string;
  created_at: string;
  hash: string;
}

export interface WatchlistView {
  user: { id: number; email: string; display_name: string };
  watchlist: { id: number; name: string };
  server_time: string;
  summary: {
    total: number;
    meaningful: number;
    by_severity: Record<Severity, number>;
    data_issues: { stale: number; delayed: number; conflict: number };
    last_reviewed_at: string | null;
  };
  attention_order: string[];
  items: WatchItem[];
  while_away: ActivityEvent[];
  marked_seen?: number;
}

export interface Instrument {
  symbol: string;
  name: string;
  sector: string;
  currency: string;
}

export interface Session {
  token: string;
  user_id: number;
  email: string;
  display_name: string;
}
