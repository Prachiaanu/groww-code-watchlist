"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import { api } from "@/lib/api";
import type { Instrument } from "@/lib/types";

export function AddSymbol({
  existing,
  onAdd,
}: {
  existing: Set<string>;
  onAdd: (symbol: string) => Promise<unknown>;
}) {
  const [instruments, setInstruments] = useState<Instrument[]>([]);
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const boxRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    api.instruments().then(setInstruments).catch(() => {});
  }, []);

  useEffect(() => {
    const onClick = (e: MouseEvent) => {
      if (boxRef.current && !boxRef.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, []);

  const matches = useMemo(() => {
    const q = query.trim().toLowerCase();
    return instruments
      .filter((i) => !existing.has(i.symbol))
      .filter((i) => !q || i.symbol.toLowerCase().includes(q) || i.name.toLowerCase().includes(q))
      .slice(0, 8);
  }, [instruments, existing, query]);

  const add = async (symbol: string) => {
    setError(null);
    try {
      await onAdd(symbol);
      setQuery("");
      setOpen(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not add");
    }
  };

  return (
    <div ref={boxRef} className="relative w-full max-w-sm">
      <input
        value={query}
        onChange={(e) => {
          setQuery(e.target.value);
          setOpen(true);
          setError(null);
        }}
        onFocus={() => setOpen(true)}
        placeholder="Add a stock — search NSE symbols…"
        className="w-full rounded-xl border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-900 px-4 py-2.5 text-sm outline-none focus:ring-2 focus:ring-brand/40"
      />
      {open && matches.length > 0 && (
        <ul className="absolute z-20 mt-1 max-h-72 w-full overflow-auto rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 shadow-lg">
          {matches.map((i) => (
            <li key={i.symbol}>
              <button
                onClick={() => add(i.symbol)}
                className="flex w-full items-center justify-between px-4 py-2 text-left text-sm hover:bg-slate-50 dark:hover:bg-slate-800"
              >
                <span>
                  <span className="font-medium">{i.symbol}</span>{" "}
                  <span className="text-slate-400">· {i.name}</span>
                </span>
                <span className="text-xs text-slate-400">{i.sector}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
      {error && <div className="absolute mt-1 text-xs text-red-600">{error}</div>}
    </div>
  );
}
