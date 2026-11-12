"use client";

// One hook owns the live view: an initial fetch, an SSE subscription that replaces
// the view on every tick, per-symbol price history for sparklines, and the mutation
// actions (which return the fresh view so the UI updates immediately).
//
// SSE auth uses a short-lived, read-only STREAM token (minted from the session
// token) so the long-lived credential never rides in a URL. On disconnect we
// re-mint and reconnect, because the stream token expires.

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { ApiError, api } from "./api";
import type { WatchlistView } from "./types";

const HISTORY = 48;
export type ConnStatus = "connecting" | "live" | "error";

export function useWatchlist(token: string | null, onAuthError?: () => void) {
  const [view, setView] = useState<WatchlistView | null>(null);
  const [status, setStatus] = useState<ConnStatus>("connecting");
  const historyRef = useRef<Map<string, number[]>>(new Map());
  const [, bump] = useState(0);

  // keep the auth-error callback in a ref so it isn't an effect dependency
  const onAuthRef = useRef(onAuthError);
  onAuthRef.current = onAuthError;

  const applyView = useCallback((v: WatchlistView) => {
    const h = historyRef.current;
    const live = new Set(v.items.map((i) => i.symbol));
    for (const it of v.items) {
      const arr = h.get(it.symbol) ?? [];
      if (arr[arr.length - 1] !== it.price) {
        arr.push(it.price);
        if (arr.length > HISTORY) arr.shift();
        h.set(it.symbol, arr);
      }
    }
    for (const k of Array.from(h.keys())) if (!live.has(k)) h.delete(k); // prune removed symbols
    setView(v);
    bump((n) => n + 1);
  }, []);

  useEffect(() => {
    // reset per-session state whenever the user (token) changes — no cross-account leak
    setView(null);
    historyRef.current = new Map();
    setStatus("connecting");
    if (!token) return;

    let closed = false;
    let es: EventSource | null = null;
    let retry: ReturnType<typeof setTimeout> | null = null;

    const authFailed = (e: unknown) => e instanceof ApiError && e.status === 401;

    api
      .watchlist(token)
      .then((v) => !closed && applyView(v))
      .catch((e) => authFailed(e) && onAuthRef.current?.());

    const open = async () => {
      if (closed) return;
      try {
        const { stream_token } = await api.streamToken(token);
        if (closed) return;
        es = new EventSource(api.streamUrl(stream_token));
        es.addEventListener("snapshot", (e) => {
          try {
            applyView(JSON.parse((e as MessageEvent).data));
            setStatus("live");
          } catch {
            /* ignore malformed frame */
          }
        });
        es.onopen = () => !closed && setStatus("live");
        es.onerror = () => {
          setStatus("error");
          if (es) {
            es.close();
            es = null;
          }
          if (!closed) retry = setTimeout(open, 3000); // reconnect with a fresh stream token
        };
      } catch (e) {
        if (authFailed(e)) {
          onAuthRef.current?.();
          return;
        }
        setStatus("error");
        if (!closed) retry = setTimeout(open, 3000);
      }
    };
    open();

    return () => {
      closed = true;
      if (es) es.close();
      if (retry) clearTimeout(retry);
    };
  }, [token, applyView]);

  const actions = useMemo(
    () => ({
      addItem: (symbol: string, above?: number | null, below?: number | null) =>
        token ? api.addItem(token, symbol, above, below).then(applyView) : Promise.resolve(),
      removeItem: (symbol: string) => (token ? api.removeItem(token, symbol).then(applyView) : Promise.resolve()),
      setAlerts: (
        symbol: string,
        body: { alert_above?: number | null; alert_below?: number | null; clear_alerts?: boolean },
      ) => (token ? api.updateItem(token, symbol, body).then(applyView) : Promise.resolve()),
      markSeen: (symbols?: string[]) => (token ? api.markSeen(token, symbols).then(applyView) : Promise.resolve()),
    }),
    [token, applyView],
  );

  return { view, status, actions, history: historyRef.current };
}
