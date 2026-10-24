"use client";

import clsx from "clsx";
import { useState } from "react";
import type { Cell } from "@/lib/types";

const LEVEL_BG = ["bg-[rgb(var(--grid-0))]", "bg-[rgb(var(--grid-1))]", "bg-[rgb(var(--grid-2))]", "bg-[rgb(var(--grid-3))]", "bg-[rgb(var(--grid-4))]"];
const DAY_LABELS = ["Mon", "", "Wed", "", "Fri", "", ""];
const LEVEL_TEXT = ["No activity", "Low", "Moderate", "High", "Very high"];

type Props = {
  weeks: Cell[][];
  onSelect?: (date: string) => void;
  selected?: string | null;
  unit?: string;
  size?: number;
};

/**
 * GitHub-style grid: one column per Monday-first week, 7 rows. Levels 0-4 come
 * from the API (quartiles of the user's non-zero days); the last 3 days are
 * "not reported yet" because Google usage lags.
 */
export function ActivityGrid({ weeks, onSelect, selected, unit = "points", size = 13 }: Props) {
  const [hover, setHover] = useState<{ cell: Cell; x: number; y: number } | null>(null);
  const gap = 3;

  const months: { label: string; col: number }[] = [];
  weeks.forEach((col, i) => {
    const first = col[0];
    if (!first) return;
    const d = new Date(first.date);
    const label = d.toLocaleString("en-IN", { month: "short" });
    const prev = months[months.length - 1];
    // Label the first week of each month; skip one that would collide with the previous label.
    if ((prev && prev.label === label) || (d.getDate() > 7 && i !== 0)) return;
    if (prev && i - prev.col < 3) {
      // A sliver of the first month at the left edge: show the full month instead.
      if (prev.col === 0) months[months.length - 1] = { label, col: i };
      return;
    }
    months.push({ label, col: i });
  });

  return (
    <div className="relative">
      <div className="overflow-x-auto pb-1">
        <div className="inline-flex flex-col" style={{ gap }}>
          <div className="relative ml-8 h-4 text-[11px] text-ink-3" aria-hidden>
            {months.map((m) => (
              <span key={`${m.label}-${m.col}`} className="absolute" style={{ left: m.col * (size + gap) }}>
                {m.label}
              </span>
            ))}
          </div>
          <div className="flex" style={{ gap }}>
            <div className="flex w-7 flex-col text-[10px] leading-none text-ink-3" style={{ gap }} aria-hidden>
              {DAY_LABELS.map((d, i) => (
                <span key={i} style={{ height: size }} className="flex items-center">
                  {d}
                </span>
              ))}
            </div>
            <div className="flex" style={{ gap }} role="grid" aria-label="Daily activity, last 6 months">
              {weeks.map((col, wi) => (
                <div key={wi} className="flex flex-col" style={{ gap }} role="row">
                  {col.map((c) => {
                    const label = c.pending
                      ? `${c.date}: not reported yet`
                      : `${c.date}: ${LEVEL_TEXT[c.level]}, ${c.score} ${unit}`;
                    const Tag = onSelect ? "button" : "span";
                    return (
                      <Tag
                        key={c.date}
                        role="gridcell"
                        aria-label={label}
                        onClick={onSelect && !c.pending ? () => onSelect(c.date) : undefined}
                        onMouseEnter={(e: React.MouseEvent) => {
                          const r = (e.currentTarget as HTMLElement).getBoundingClientRect();
                          const host = (e.currentTarget as HTMLElement).closest(".relative")!.getBoundingClientRect();
                          setHover({ cell: c, x: r.left - host.left + size / 2, y: r.top - host.top });
                        }}
                        onMouseLeave={() => setHover(null)}
                        onFocus={() => setHover(null)}
                        style={{ width: size, height: size }}
                        className={clsx(
                          "block rounded-[3px] outline-offset-1",
                          c.pending
                            ? "border border-dashed border-ink-3/60 bg-transparent"
                            : LEVEL_BG[c.level],
                          onSelect && !c.pending && "cursor-pointer hover:ring-2 hover:ring-brand/50 focus-visible:ring-2 focus-visible:ring-brand",
                          selected === c.date && "ring-2 ring-ink",
                        )}
                      />
                    );
                  })}
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>

      {hover && (
        <div
          role="tooltip"
          className="pointer-events-none absolute z-20 -translate-x-1/2 -translate-y-full whitespace-nowrap rounded-md bg-ink px-2 py-1 text-xs text-bg shadow-lg"
          style={{ left: hover.x, top: hover.y - 6 }}
        >
          <div className="font-medium">
            {new Date(hover.cell.date).toLocaleDateString("en-IN", { weekday: "short", day: "numeric", month: "short", year: "numeric" })}
          </div>
          <div className="opacity-80">
            {hover.cell.pending ? "Not reported yet (Google lags 2–3 days)" : `${LEVEL_TEXT[hover.cell.level]} · ${hover.cell.score} ${unit}`}
          </div>
        </div>
      )}

      <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-2 text-xs text-ink-3">
        <span className="flex items-center gap-1">
          Less
          {LEVEL_BG.map((bg, i) => (
            <span key={i} className={clsx("inline-block rounded-[3px]", bg)} style={{ width: 11, height: 11 }} title={LEVEL_TEXT[i]} />
          ))}
          More
        </span>
        <span className="flex items-center gap-1">
          <span className="inline-block rounded-[3px] border border-dashed border-ink-3/60" style={{ width: 11, height: 11 }} />
          Not reported yet
        </span>
      </div>
    </div>
  );
}
