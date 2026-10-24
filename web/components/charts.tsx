"use client";

import { useEffect, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

const TOKENS = ["--brand", "--text-2", "--text-3", "--border", "--surface", "--s1", "--s2", "--s3", "--s4", "--s5"] as const;
type Palette = Record<(typeof TOKENS)[number], string>;

/** Resolve theme tokens to colours (SVG attributes can't read CSS vars); re-read on theme change. */
export function usePalette(): Palette {
  const read = (): Palette => {
    const out = {} as Palette;
    const cs = typeof window === "undefined" ? null : getComputedStyle(document.documentElement);
    for (const t of TOKENS) out[t] = cs ? `rgb(${cs.getPropertyValue(t).trim()})` : "#888";
    return out;
  };
  const [p, setP] = useState<Palette>(read);
  useEffect(() => {
    setP(read());
    const obs = new MutationObserver(() => setP(read()));
    obs.observe(document.documentElement, { attributes: true, attributeFilter: ["class"] });
    return () => obs.disconnect();
  }, []);
  return p;
}

const SERIES = ["--s1", "--s2", "--s3", "--s4", "--s5"] as const;

function TooltipBox({ active, payload, label, unit }: { active?: boolean; payload?: { name: string; value: number; color: string }[]; label?: string; unit?: string }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-md border border-line bg-surface px-3 py-2 text-xs shadow-lg">
      <div className="mb-1 font-medium text-ink">{label}</div>
      {payload.map((p) => (
        <div key={p.name} className="flex items-center gap-2 text-ink-2">
          <span className="inline-block h-2 w-2 rounded-full" style={{ background: p.color }} />
          <span className="flex-1">{p.name}</span>
          <span className="tabular-nums text-ink">
            {typeof p.value === "number" ? p.value.toLocaleString("en-IN", { maximumFractionDigits: 1 }) : p.value}
            {unit ? ` ${unit}` : ""}
          </span>
        </div>
      ))}
    </div>
  );
}

/** Line chart over time. One series = brand colour, no legend; several = fixed categorical order + legend. */
export function TrendChart<T extends Record<string, unknown>>({
  data,
  x,
  series,
  height = 220,
  unit,
  xFormat,
}: {
  data: T[];
  x: keyof T & string;
  series: { key: keyof T & string; label: string }[];
  height?: number;
  unit?: string;
  xFormat?: (v: string) => string;
}) {
  const p = usePalette();
  const color = (i: number) => (series.length === 1 ? p["--brand"] : p[SERIES[i % SERIES.length]]);
  return (
    <div style={{ height }} className="w-full">
      <ResponsiveContainer>
        <LineChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: -12 }}>
          <CartesianGrid stroke={p["--border"]} vertical={false} />
          <XAxis dataKey={x} tick={{ fill: p["--text-3"], fontSize: 11 }} tickLine={false} axisLine={{ stroke: p["--border"] }} tickFormatter={xFormat} minTickGap={24} />
          <YAxis tick={{ fill: p["--text-3"], fontSize: 11 }} tickLine={false} axisLine={false} width={44} />
          <Tooltip content={<TooltipBox unit={unit} />} labelFormatter={xFormat as never} cursor={{ stroke: p["--text-3"], strokeDasharray: "3 3" }} />
          {series.length > 1 && <Legend iconType="circle" iconSize={8} wrapperStyle={{ fontSize: 12, color: p["--text-2"] }} />}
          {series.map((s, i) => (
            <Line key={s.key} type="monotone" dataKey={s.key} name={s.label} stroke={color(i)} strokeWidth={2} dot={false} activeDot={{ r: 4, stroke: p["--surface"], strokeWidth: 2 }} />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

/** Vertical bars, single series in the brand colour. */
export function Bars<T extends Record<string, unknown>>({
  data,
  x,
  y,
  label,
  height = 220,
  unit,
}: {
  data: T[];
  x: keyof T & string;
  y: keyof T & string;
  label: string;
  height?: number;
  unit?: string;
}) {
  const p = usePalette();
  return (
    <div style={{ height }} className="w-full">
      <ResponsiveContainer>
        <BarChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: -12 }} barCategoryGap="20%">
          <CartesianGrid stroke={p["--border"]} vertical={false} />
          <XAxis dataKey={x} tick={{ fill: p["--text-3"], fontSize: 11 }} tickLine={false} axisLine={{ stroke: p["--border"] }} interval={0} />
          <YAxis tick={{ fill: p["--text-3"], fontSize: 11 }} tickLine={false} axisLine={false} width={44} />
          <Tooltip content={<TooltipBox unit={unit} />} cursor={{ fill: p["--border"], opacity: 0.4 }} />
          <Bar dataKey={y} name={label} fill={p["--brand"]} radius={[4, 4, 0, 0]} maxBarSize={36} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

/** Day-of-week x hour heatmap (counts), sequential brand ramp. */
export function WeekHourHeatmap({ cells }: { cells: { dow: number; hour: number; count: number }[] }) {
  const max = Math.max(...cells.map((c) => c.count), 1);
  const get = (d: number, h: number) => cells.find((c) => c.dow === d && c.hour === h)?.count ?? 0;
  const days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
  const level = (v: number) => (v === 0 ? 0 : Math.min(4, Math.ceil((v / max) * 4)));
  return (
    <div className="overflow-x-auto">
      <table className="border-separate" style={{ borderSpacing: 2 }} aria-label="Activity by weekday and hour">
        <thead>
          <tr>
            <th />
            {Array.from({ length: 24 }, (_, h) => (
              <th key={h} className="w-4 text-[10px] font-normal text-ink-3">
                {h % 3 === 0 ? h : ""}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {days.map((d, i) => (
            <tr key={d}>
              <th className="pr-1 text-right text-[10px] font-normal text-ink-3">{d}</th>
              {Array.from({ length: 24 }, (_, h) => {
                const v = get(i + 1, h);
                return (
                  <td key={h} title={`${d} ${h}:00 · ${v} events`} className="h-4 w-4 rounded-[3px]" style={{ background: `rgb(var(--grid-${level(v)}))` }} />
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
