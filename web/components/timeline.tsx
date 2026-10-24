"use client";

import clsx from "clsx";
import { useState } from "react";
import { useApi } from "@/lib/api";
import { fmtDate } from "@/lib/format";
import { CardSkeleton, Empty } from "./ui";

type Item = {
  time: string;
  first: string;
  count: number;
  app: string;
  app_label: string;
  event: string;
  text: string;
  country: string | null;
};
type Data = {
  days: { date: string; items: Item[] }[];
  apps: { app: string; label: string; count: number }[];
  truncated: boolean;
};

const clock = (iso: string) => new Date(iso).toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" });
const PER_DAY = 25;

/** A person's activity, newest first, in plain English, with app filters. */
export function Timeline({ userId }: { userId: string }) {
  const [app, setApp] = useState<string>("");
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  // The app list (with counts) comes from the unfiltered query and stays put while filtering.
  const all = useApi<Data>(`/people/${userId}/timeline?months=2`);
  const filtered = useApi<Data>(app ? `/people/${userId}/timeline?months=2&app=${encodeURIComponent(app)}` : null);
  const data = app ? filtered.data : all.data;

  if (!all.data) return <CardSkeleton rows={4} />;
  return (
    <div>
      <div className="mb-3 flex flex-wrap gap-1.5" role="group" aria-label="Filter by app">
        {[{ app: "", label: "All", count: all.data.apps.reduce((n, a) => n + a.count, 0) }, ...all.data.apps].map((a) => (
          <button
            key={a.app || "all"}
            onClick={() => setApp(a.app)}
            aria-pressed={app === a.app}
            className={clsx(
              "rounded-full border px-2.5 py-0.5 text-xs font-medium transition",
              app === a.app ? "border-brand bg-brand-soft text-brand-strong" : "border-line text-ink-2 hover:bg-surface-2",
            )}
          >
            {a.label} <span className="tabular-nums opacity-70">{a.count.toLocaleString("en-IN")}</span>
          </button>
        ))}
      </div>

      {!data ? (
        <CardSkeleton rows={4} />
      ) : !data.days.length ? (
        <Empty title="No activity in the last 2 months" />
      ) : (
        <ol className="max-h-[520px] space-y-4 overflow-y-auto pr-2">
          {data.days.map((d) => {
            const open = expanded[d.date];
            const items = open ? d.items : d.items.slice(0, PER_DAY);
            return (
              <li key={d.date}>
                <h3 className="sticky top-0 z-10 bg-surface py-1 text-xs font-semibold uppercase tracking-wide text-ink-3">
                  {fmtDate(d.date)}
                </h3>
                <ul className="mt-1 border-l border-line">
                  {items.map((it, i) => (
                    <li key={i} className="grid grid-cols-[4.5rem_5.5rem_1fr] items-start gap-x-3 py-1 pl-4 text-sm">
                      <span className="whitespace-nowrap pt-0.5 tabular-nums text-ink-3" title={it.count > 1 ? `${clock(it.first)}–${clock(it.time)}` : undefined}>
                        {clock(it.time)}
                      </span>
                      <span
                        className="truncate rounded-full bg-surface-2 px-2 py-0.5 text-center text-xs font-medium text-ink-2"
                        title={it.app_label}
                      >
                        {it.app_label}
                      </span>
                      <span className="min-w-0 break-words text-ink">
                        {it.text}
                        {it.count > 1 && (
                          <span className="ml-1.5 whitespace-nowrap text-xs text-ink-3">
                            ×{it.count} · {clock(it.first)}–{clock(it.time)}
                          </span>
                        )}
                      </span>
                    </li>
                  ))}
                </ul>
                {d.items.length > PER_DAY && (
                  <button
                    onClick={() => setExpanded({ ...expanded, [d.date]: !open })}
                    className="ml-4 mt-1 text-xs font-medium text-brand hover:underline"
                  >
                    {open ? "Show fewer" : `Show all ${d.items.length}`}
                  </button>
                )}
              </li>
            );
          })}
          {data.truncated && <li className="text-xs text-ink-3">Showing the most recent 3,000 events.</li>}
        </ol>
      )}
    </div>
  );
}
