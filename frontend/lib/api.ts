// Thin API client. All calls go through here so the base URL and auth header live
// in one place.

import type { Instrument, Session, WatchlistView } from "./types";

export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE?.replace(/\/$/, "") || "http://localhost:8137";

async function req<T>(path: string, opts: RequestInit = {}, token?: string): Promise<T> {
  const headers: Record<string, string> = { "Content-Type": "application/json", ...(opts.headers as any) };
  if (token) headers["Authorization"] = `Bearer ${token}`;
  const res = await fetch(`${API_BASE}${path}`, { ...opts, headers });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail ?? detail;
    } catch {
      /* ignore */
    }
    throw new ApiError(res.status, String(detail));
  }
  return res.json() as Promise<T>;
}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

export const api = {
  login: (email: string, display_name = "") =>
    req<Session>("/api/auth/login", { method: "POST", body: JSON.stringify({ email, display_name }) }),

  instruments: () => req<Instrument[]>("/api/instruments"),

  watchlist: (token: string) => req<WatchlistView>("/api/watchlist", {}, token),

  addItem: (token: string, symbol: string, alert_above?: number | null, alert_below?: number | null) =>
    req<WatchlistView>(
      "/api/watchlist/items",
      { method: "POST", body: JSON.stringify({ symbol, alert_above, alert_below }) },
      token,
    ),

  updateItem: (
    token: string,
    symbol: string,
    body: { alert_above?: number | null; alert_below?: number | null; clear_alerts?: boolean },
  ) => req<WatchlistView>(`/api/watchlist/items/${symbol}`, { method: "PATCH", body: JSON.stringify(body) }, token),

  removeItem: (token: string, symbol: string) =>
    req<WatchlistView>(`/api/watchlist/items/${symbol}`, { method: "DELETE" }, token),

  markSeen: (token: string, symbols?: string[]) =>
    req<WatchlistView>("/api/watchlist/seen", { method: "POST", body: JSON.stringify({ symbols: symbols ?? null }) }, token),

  verifyLog: (token: string) =>
    req<{ ok: boolean; entries: number; head_hash?: string; broken_at_seq?: number }>("/api/log/verify", {}, token),

  // Exchange the session token for a short-lived, read-only STREAM token; only this
  // narrow token ever appears in a URL (EventSource can't send headers).
  streamToken: (token: string) =>
    req<{ stream_token: string }>("/api/auth/stream-token", { method: "POST" }, token),

  streamUrl: (streamToken: string) => `${API_BASE}/api/stream?token=${encodeURIComponent(streamToken)}`,
};
