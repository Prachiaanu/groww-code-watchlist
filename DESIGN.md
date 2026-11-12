# Design & Engineering Notes — Smart Market Watchlist

This is the "why" behind the build: the problem interpretation, the key decisions, the trade-offs I made deliberately, and what I'd do next. It's written to be defended.

---

## 1. Problem interpretation

The brief asks for a watchlist that helps users "quickly understand what has *meaningfully changed* since they last checked, and what deserves their attention now." I took the emphasis literally:

> The scarce resource isn't market data — it's **attention**. A watchlist's real job is to **decide what you should look at**, and justify that decision.

That reframes the product from a *display* problem into a *decision* problem — and a decision problem is best solved with an explicit, explainable **policy engine**, not ad-hoc UI conditionals. Everything else follows from that stance.

Three sub-problems fall out, and they map to the three required capabilities:

| Brief requirement | Hard question underneath it | My answer |
|---|---|---|
| Create & manage a watchlist | — | Per-user watchlist + alerts, server-side |
| View latest market information | How do I show data I can't fully trust? | Consolidated quotes with explicit freshness/conflict |
| Return later & see what changed | What is a *meaningful* change, and how do I know what happened while away? | Volatility-normalised significance engine + tamper-evident event log |

---

## 2. What counts as a "meaningful" change

This is the most important decision in the project, so it gets the most scrutiny.

**The naïve answer — a fixed % threshold — is wrong.** A ±1.5% day is a genuine event for a sleepy large-cap like HINDUNILVR and complete noise for a jumpy name like ZOMATO. A single threshold either drowns you in small-cap noise or hides real large-cap moves.

**My definition: a move is meaningful relative to *that stock's own* normal behaviour.** Concretely, I score a move as a **z-score against the stock's recent realised volatility**, scaled to the *horizon* of the move:

```
rₜ      = per-tick % return                     (kept in a rolling window of 120)
σ_tick  = stdev(recent rₜ)                       (the stock's own "normal" wiggle)
σ(n)    = σ_tick · √n                             (a move over n ticks; variance ∝ time, random walk)
z       = Δ% / σ(n)                              (how many std-devs this move is)
```

A move is surfaced only if it clears **two** bars:

1. an **absolute floor** (`|Δ%| ≥ 0.5%`) — kills rounding/micro-noise regardless of z, and
2. a **volatility bar** (`|z| ≥ 1σ`, once we have ≥10 samples) — makes "unusual" relative to the stock.

The score then scales linearly to `|z| = 3σ` (a "major" move), and discrete events add on top:

```
move_score   = clamp(|z| / 3, 0, 1) · 60
+ alert crossed        +40   (the user's own intent — highest weight)
+ new 52-week high/low +35
+ opening gap (≥2%)    +15
+ volume spike (≥1.8×) +10
attention_score = clamp(Σ, 0, 100)
```

**Worked example (both up exactly +1% since you last looked):**

| Stock | σ_tick | z (n=1) | move score | Verdict |
|---|---|---|---|---|
| A calm large-cap | 0.1% | **10σ** | 60 (capped) | **meaningful** (major) |
| A volatile small-cap | 1.0% | **1σ** | 20 | *not* meaningful (normal for it) |

Same raw number, opposite conclusions — which is the entire point, and something a flat threshold can't do. This is verified by `test_same_move_meaningful_for_calm_not_jumpy`, and you can see it live in the UI: ZOMATO up 3% often ranks *below* a large-cap up 1.5%.

**Why this design is defensible**

- **Explainable, not a black box.** Every signal carries a human-readable `reason` (`+3.2% since you looked — 2.6σ vs its usual move`). Transparency is a Groww value; it's also just good product.
- **The thresholds are the product, so they're first-class.** They live, named and commented, in `config.py::SignificanceConfig` — an *operating-point* choice, exactly like picking a classifier threshold from a precision/recall curve. Tuning them never touches logic.
- **Deterministic & pure.** `significance.py` is pure functions with no I/O or clock of its own, so it's exhaustively unit-testable.
- **User intent wins.** A crossed price alert is a "hard" signal — always meaningful, regardless of score — because the user explicitly said they cared.

Honest limitations: σ is short-horizon realised vol (not intraday-seasonality-aware), the √n horizon scaling assumes a random walk, and there's no cross-asset/correlation view yet. See §9.

---

## 3. The significance engine as a policy engine

`significance.py` is structured as a small rules engine: pure helpers (`_move_signal`, `_week52_signals`, `_gap_signal`, `_volume_signal`, `_alert_signals`) each emit zero-or-more scored `Signal`s, and an aggregator combines them into an `AttentionResult` (score, severity bucket, `is_meaningful`, ordered signals, `since_seen`).

Two entry points, deliberately split for **scale** (see §7):

- `evaluate_symbol_events(...)` — user-*independent* signals (unusual move today, 52wk break, gap, volume spike). Computed **once per symbol per tick** and written to the shared event log.
- `evaluate_attention(...)` — user-*specific* view (since-you-last-looked delta + your alerts, on top of the symbol-level signals). Computed cheaply **per request**.

---

## 4. "Since you last checked" and "while you were away"

Two complementary mechanisms:

- **`seen_state` (per user, per symbol): baseline price + timestamp.** This is the anchor for the live diff. It's keyed by **user**, not device or session, so opening the app on your phone shows the same baseline as your laptop. It's set by an explicit **"Mark all as reviewed"** action (the notification-clearing gesture), so the diff means "since I last acknowledged this."
- **`signal_log` (append-only, hash-chained): every material market event.** This powers the "while you were away" timeline and is **tamper-evident**: `hash = sha256(prev_hash | canonical(payload))`, so each row commits to the entire history before it. `GET /api/log/verify` recomputes the chain and reports the first break. Editing or deleting any past event is detectable — proven by `test_tamper_of_a_field_is_detected` and `test_deletion_breaks_the_chain`.

Why a hash chain for a watchlist? Because "trust what changed while you were away" is a *trust* claim. If a user returns after a week, the feed of what happened should be provably un-rewritten. (This mirrors a pattern I've used before for a financial audit ledger.)

Logging is **edge-triggered**: an event is written when its `dedup_key` first becomes active and not again while it stays active — so a stock sitting at a 52-week high produces *one* log entry, not one per tick. The dedup key buckets moves by whole-percent, so an *escalating* move still logs each new step.

---

## 5. Handling stale, delayed & conflicting data

The brief calls this out explicitly, so it's built into the ingest engine (`market/engine.py`) rather than bolted on. Every quote carries three facts: `as_of` (when the data is valid, per the source), `source` (who said it), and `received_at` (when we saw it). Everything below is derived from those.

| Hazard | Detection | Response |
|---|---|---|
| **Out-of-order / duplicate** ticks | monotonic guard per `(symbol, source)`: reject any `as_of ≤` the last stored | never corrupt state; counted in `/health` |
| **Delayed / stale** data | freshness computed **at read time** from `as_of` age (FRESH < 6s ≤ DELAYED < 15s ≤ STALE) | surfaced in the UI; we keep the last good value and never present stale data as live |
| **Conflicting** sources | among **fresh** sources only, if max/min price diverge > 0.75% | pick a deterministic winner (freshest → highest-priority source → newest `as_of`) **and** flag `CONFLICT` so the disagreement is visible |

The subtlety worth calling out: **a delayed source is *not* a conflict.** It's simply behind. Conflict detection therefore considers only sources that are currently FRESH — otherwise every lagging feed would raise a false alarm (a bug I hit and fixed during development). The winner is always chosen so the UI never blanks, but the disagreement is never hidden.

**The simulator makes this real, not theatrical.** Instead of two unrelated random feeds, there's one ground-truth price process and each provider is an *imperfect view* of it. The secondary provider runs deterministic, staggered quirks — an **outage** (stops quoting → ages to STALE), a **bad print** (one divergent tick → CONFLICT), and a **late tick** (past `as_of` → rejected). So the data-quality paths are exercised reproducibly, and the tests assert them precisely.

---

## 6. State across sessions & devices

All durable state is server-side in SQLite, keyed by `user_id` from a JWT: the watchlist, alerts, `seen_state`, and the (global) event log. There is no client-authoritative state — the browser holds only the token and a few cosmetic sparkline points. So any device with the token converges on the same watchlist and the same "since you last checked" baseline. Auth is passwordless-by-email for the demo; the token machinery is unchanged if you later drop in OTP/OAuth.

---

## 7. Scale

Design choices that keep this cheap as users and watchlists grow:

- **Shared quotes, not per-user copies.** The engine holds one price + one stats object per symbol. *N users watching RELIANCE cost one price object, not N.* A watchlist is just a set of symbol references.
- **Symbol-level work is done once.** Volatility, 52-week levels, gaps, volume spikes and their log entries are computed **once per symbol per tick** — O(symbols), independent of user count. Only the genuinely user-specific bits (since-you-looked delta, your alerts) are computed per request, at O(items in *your* list).
- **The read path is a cheap join.** `build_view` reads in-memory quotes/stats under a short lock and does one indexed query for the "while away" feed.
- **Honest ceilings.** SQLite (WAL mode) comfortably handles a single-node demo; the repository boundary (all persistence behind the ORM/services) means Postgres is a `DATABASE_URL` change. The real fan-out ceiling is the single-process in-memory engine + per-connection SSE; the next step is a shared quote cache (Redis) with pub/sub so multiple API nodes broadcast one upstream feed. That's deliberately **not** built yet — see "simple vs complex" below.

---

## 8. Concurrency model

FastAPI runs sync endpoints in a threadpool, and a background asyncio task advances the market each tick (the sync tick runs in a worker thread so the event loop stays responsive). That means the shared engine is touched from multiple threads, so it's guarded by a single reentrant lock: the whole tick update and every request-side engine read span hold it. The locked spans are pure in-memory CPU work (no I/O inside them), so contention is negligible at this scale. SQLite is in WAL mode so the background writer and request readers don't block each other, and each request/tick/SSE-frame uses its own short-lived session.

---

## 9. Testing strategy

40 `pytest` tests, focused on **invariants** rather than line coverage for its own sake:

- **The thesis** — the same % move is meaningful for a calm stock and not for a volatile one.
- **Gates** — the absolute floor and the z-score bar each suppress the right moves; hard signals (alerts, 52wk) are always meaningful; the score caps at 100.
- **Data quality** — out-of-order/duplicate rejection, freshness classification, conflict *only* between fresh sources, deterministic winner selection.
- **Integrity** — the hash chain verifies clean, and detects both field tampering and row deletion.
- **Since-you-looked** — baselines set/reset correctly; the while-away feed is scoped to the review checkpoint.
- **API** — auth required, unknown-symbol 404, duplicate 409, user isolation, case-insensitive symbols, health & verify.

Everything is deterministic: fixed seed, injectable time, and the background loop disabled in tests.

---

## 10. Where I kept it simple vs added complexity

| Kept simple | Added complexity (on purpose) |
|---|---|
| SQLite, not Postgres/Redis | Volatility-normalised significance (the core value) |
| Passwordless email auth | Multi-source ingest with conflict resolution |
| SSE, not WebSockets | Tamper-evident hash-chained event log |
| One watchlist per user (schema supports many) | A deterministic simulator that *injects* messy data |
| Full-view push on each tick (not deltas) | Edge-triggered, deduped event logging |

The rule I followed: **spend complexity only where it buys the user trust or better decisions.** A watchlist doesn't need a microservice mesh; it needs to be *right* about what matters.

---

## 11. Trade-offs & what I'd do next

- **Real data adapter.** Implement `MarketDataProvider` against a live vendor (e.g. a broker websocket) — the rest of the system is unchanged. Add a 15-minute-delayed tier and let freshness surface it.
- **Learned thresholds.** Today's operating points are chosen by judgement. With labelled "did the user actually care?" data, I'd tune them the way I pick a model's operating point from a precision/recall curve — and A/B the alert weights.
- **Portfolio-aware significance.** Weight attention by position size and correlation, so a move in something you hold a lot of (or in a name correlated with your book) ranks higher.
- **Horizontal scale.** Redis-backed shared quote cache + pub/sub fan-out; multiple stateless API nodes; move the tick loop into a dedicated worker.
- **Auth hardening.** OTP/OAuth login; short-lived, single-use stream tokens instead of a query-param JWT for SSE; rate limiting.
- **Notifications & digests.** Push/email "here's what changed" digests using the exact same significance engine that powers the UI.

---

## 11b. Hardening pass & consciously deferred items

After the first working version I ran a structured, multi-perspective review of the whole codebase (correctness, data-quality, concurrency, security, frontend/API contract, product edge-cases) with each finding independently verified before acting. That pass directly produced several fixes now in the code, e.g.:

- **Security:** SSE now uses a short-lived, read-only **stream-scoped** token (the session token never rides in a URL); fail-fast on the insecure default secret in prod; generic 401s; authenticated log-verify; bounded request inputs; shorter token TTL.
- **Correctness:** the intraday move is anchored to the session open so the overnight **gap isn't double-counted** in the z-score; the volatility horizon is **capped** so significance doesn't decay to zero over a long session; volume-delta detection ignores lagged/backwards cumulative prints.
- **Robustness:** all providers ingest in a single batch per tick (correct conflict counting); event dedup uses a monotonic ratchet (oscillating prices don't re-log); dedup state is seeded after warmup (restart-safe); the "while you were away" feed filters **per-symbol** and shows nothing on a first-ever visit.
- **Frontend:** per-account state reset on user switch; graceful logout on an expired token; user-visible errors on every mutating action; sparkline history pruned on removal.

Things I consciously **left** (documented, not missed):

- **No trading-day/session boundary.** The demo market runs continuously; `session_open`/`ticks_since_open` never reset. The practical downside (significance decaying as the "day" grows) is neutralised by the volatility-horizon cap; a real deployment would reset these on the exchange's session boundary.
- **JWT in `localStorage`.** Convenient for a demo SPA and low-risk here (React escapes output; no `dangerouslySetInnerHTML`), but an HttpOnly cookie is the production answer. Mitigated by the shorter TTL and the read-only stream token.
- **`build_view` holds the engine lock across its per-symbol compute.** Pure in-memory work, negligible at this scale; at high SSE-client counts I'd snapshot the needed scalars under the lock and compute outside it.
- **Full-chain rehash on `/log/verify`.** O(n); fine for a demo and now authenticated. At scale I'd verify incrementally against a cached head hash.

## 12. Map of the code

Start here to read the project in dependency order:

1. `backend/app/config.py` — the operating points (what "meaningful" means).
2. `backend/app/market/provider.py` → `simulated.py` → `engine.py` — data in, trustworthy view out.
3. `backend/app/significance.py` — the core decision engine.
4. `backend/app/signals_log.py` — the tamper-evident history.
5. `backend/app/services/{ticker,watchlist,accounts}.py` — orchestration.
6. `backend/app/api/*` + `main.py` — HTTP/SSE surface and the background loop.
7. `frontend/lib/{types,api,useWatchlist}.ts` → `components/*` → `app/page.tsx` — the UI.
8. `backend/tests/*` — the invariants that keep it honest.
