"use client";

import clsx from "clsx";
import { ArrowDownRight, ArrowUpRight, ChevronDown, ChevronRight, Info, Lock } from "lucide-react";
import Link from "next/link";
import { Fragment, useState } from "react";
import { TrendChart, WeekHourHeatmap } from "@/components/charts";
import { BarList, Card, Empty, ErrorState, Kpi, PageHeader, PageSkeleton } from "@/components/ui";
import { useApi } from "@/lib/api";
import { fmtDate, fmtNum, titleCase } from "@/lib/format";

type Heat = { dow: number; hour: number; count: number };
type Summary = {
  people: number;
  events: number;
  outside_pct: number;
  after_hours_pct: number;
  weekend_pct: number;
  late_night_pct: number;
  early_pct: number;
  people_outside: number;
  people_outside_pct: number;
  prev_outside_pct: number | null;
  change_pts: number | null;
  peak: { dow: number; hour: number } | null;
  trend: { week: string; outside_pct: number; events: number }[];
  heatmap: Heat[];
  by_app: { app: string; events: number; outside: number; outside_pct: number }[];
};
type Data = {
  window_days: number;
  work_hours: { start: string; end: string; timezone: string };
  org: Summary;
  teams: ({ team: string } & Summary)[];
  hidden_teams: { team: string; people: number }[];
  min_team_size: number;
};

const DAYS = ["", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const APP_LABEL: Record<string, string> = { login: "Sign-ins", drive: "Drive", meet: "Meet", calendar: "Calendar", chat: "Chat", gmail: "Gmail" };
const peakText = (p: Summary["peak"]) => (p ? `${DAYS[p.dow]} ${String(p.hour).padStart(2, "0")}:00` : "—");
const shortDate = (v: string) => fmtDate(v).replace(/ \d{4}$/, "");

/** Change in percentage points vs the previous period; up = more out-of-hours work (worse). */
function Change({ pts }: { pts: number | null }) {
  if (pts === null) return <span className="text-ink-3">—</span>;
  if (Math.abs(pts) < 0.1) return <span className="text-ink-3">no change</span>;
  const up = pts > 0;
  return (
    <span className={clsx("inline-flex items-center gap-0.5 tabular-nums", up ? "text-critical" : "text-good")}>
      {up ? <ArrowUpRight size={12} aria-hidden /> : <ArrowDownRight size={12} aria-hidden />}
      {up ? "+" : ""}
      {pts} pts
    </span>
  );
}

function TeamDetail({ t }: { t: { team: string } & Summary }) {
  return (
    <div className="grid gap-4 bg-surface-2/40 p-4 xl:grid-cols-3">
      <div className="xl:col-span-2">
        <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-ink-3">When {t.team} works (local hour)</h3>
        <WeekHourHeatmap cells={t.heatmap} />
      </div>
      <div className="space-y-4">
        <div>
          <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-ink-3">Out-of-hours activity by app</h3>
          <BarList
            items={t.by_app.filter((a) => a.outside > 0).map((a) => ({ key: a.app, label: APP_LABEL[a.app] ?? titleCase(a.app), value: a.outside_pct, hint: `${a.outside} of ${a.events} events` }))}
            format={(v) => `${v}%`}
            max={100}
          />
        </div>
        <div>
          <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-ink-3">Weekly trend · outside hours</h3>
          <TrendChart data={t.trend} x="week" series={[{ key: "outside_pct", label: "Outside working hours" }]} unit="%" height={140} xFormat={shortDate} />
        </div>
      </div>
    </div>
  );
}

export default function WellbeingPage() {
  const { data, error, mutate } = useApi<Data>("/insights/after-hours");
  const [open, setOpen] = useState<string | null>(null);
  const [heatTeam, setHeatTeam] = useState<string>("");
  if (error) return <ErrorState error={error} retry={() => mutate()} />;
  if (!data) return <PageSkeleton />;
  const o = data.org;
  const heat = heatTeam ? data.teams.find((t) => t.team === heatTeam)?.heatmap ?? [] : o.heatmap;

  return (
    <>
      <PageHeader
        title="After-hours & weekend activity"
        subtitle={`Working hours ${data.work_hours.start}–${data.work_hours.end} Mon–Fri (${data.work_hours.timezone}) · last ${data.window_days} days`}
        action={<Link href="/settings" className="text-sm text-brand hover:underline">Change working hours</Link>}
      />
      <p className="mb-4 flex items-start gap-2 rounded-card border border-line bg-surface p-3 text-sm text-ink-2">
        <Info size={16} className="mt-0.5 shrink-0 text-brand" aria-hidden />
        A burnout signal shown per team, never as a ranking of individuals. Teams with fewer than {data.min_team_size} people are hidden so no one can be singled out.
        Counts sign-ins, Drive, Meet, Calendar and Chat events.
      </p>

      <div className="mb-4 grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
        <Kpi label="Outside working hours" value={`${o.outside_pct}%`} hint={<Change pts={o.change_pts} />} />
        <Kpi label="Weekday evenings/early" value={`${o.after_hours_pct}%`} hint="before or after hours, Mon–Fri" />
        <Kpi label="Weekends" value={`${o.weekend_pct}%`} hint="Saturday and Sunday" />
        <Kpi label="Late night" value={`${o.late_night_pct}%`} hint="22:00–06:00, any day" tone={o.late_night_pct >= 5 ? "critical" : undefined} />
        <Kpi label="Early starts" value={`${o.early_pct}%`} hint={`before ${data.work_hours.start} on weekdays`} />
        <Kpi label="People working outside hours" value={`${o.people_outside} of ${o.people}`} hint={`${o.people_outside_pct}% did at least once`} />
      </div>

      <div className="mb-4 grid gap-4 xl:grid-cols-3">
        <Card className="xl:col-span-2" title="Weekly trend" subtitle="Share of activity outside working hours, last 12 weeks">
          {o.trend.length ? (
            <TrendChart data={o.trend} x="week" series={[{ key: "outside_pct", label: "Outside working hours" }]} unit="%" xFormat={shortDate} />
          ) : (
            <Empty title="Not enough activity yet" />
          )}
        </Card>
        <Card title="Which apps people use out of hours" subtitle="Share of each app's events outside working hours">
          <BarList
            items={o.by_app.map((a) => ({ key: a.app, label: APP_LABEL[a.app] ?? titleCase(a.app), value: a.outside_pct, hint: `${fmtNum(a.outside)} of ${fmtNum(a.events)} events` }))}
            format={(v) => `${v}%`}
            max={100}
          />
          <p className="mt-3 text-xs text-ink-3">Busiest time overall: <strong className="text-ink-2">{peakText(o.peak)}</strong></p>
        </Card>
      </div>

      <Card className="mb-4" title="By team" subtitle="Sorted by share of out-of-hours activity · click a team for its heatmap, apps and trend" bodyClass="p-0">
        {!data.teams.length ? (
          <Empty title="No team large enough to show yet" />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[920px] text-left text-sm">
              <thead>
                <tr className="border-b border-line text-xs uppercase tracking-wide text-ink-3">
                  <th className="px-4 py-2 font-medium">Team</th>
                  <th className="px-3 py-2 font-medium">People</th>
                  <th className="px-3 py-2 font-medium">Outside hours</th>
                  <th className="px-3 py-2 font-medium">vs prev {data.window_days}d</th>
                  <th className="px-3 py-2 font-medium">Evenings/early</th>
                  <th className="px-3 py-2 font-medium">Weekends</th>
                  <th className="px-3 py-2 font-medium">Late night</th>
                  <th className="px-3 py-2 font-medium">People outside hours</th>
                  <th className="px-3 py-2 font-medium">Busiest</th>
                </tr>
              </thead>
              <tbody>
                {data.teams.map((t) => {
                  const isOpen = open === t.team;
                  return (
                    <Fragment key={t.team}>
                      <tr className={clsx("cursor-pointer border-b border-line/60 hover:bg-surface-2/60", isOpen && "bg-surface-2/60")} onClick={() => setOpen(isOpen ? null : t.team)}>
                        <td className="px-4 py-2.5">
                          <button className="flex items-center gap-1.5 font-medium text-ink" aria-expanded={isOpen}>
                            {isOpen ? <ChevronDown size={14} aria-hidden /> : <ChevronRight size={14} aria-hidden />}
                            {t.team}
                          </button>
                        </td>
                        <td className="px-3 py-2.5 tabular-nums">{t.people}</td>
                        <td className="px-3 py-2.5">
                          <span className="flex items-center gap-2">
                            <span className="h-1.5 w-14 shrink-0 rounded-full bg-surface-2">
                              <span className="block h-1.5 rounded-full bg-brand" style={{ width: `${Math.min(t.outside_pct * 2, 100)}%` }} />
                            </span>
                            <span className="tabular-nums">{t.outside_pct}%</span>
                          </span>
                        </td>
                        <td className="px-3 py-2.5"><Change pts={t.change_pts} /></td>
                        <td className="px-3 py-2.5 tabular-nums">{t.after_hours_pct}%</td>
                        <td className="px-3 py-2.5 tabular-nums">{t.weekend_pct}%</td>
                        <td className={clsx("px-3 py-2.5 tabular-nums", t.late_night_pct >= 5 && "text-critical")}>{t.late_night_pct}%</td>
                        <td className="px-3 py-2.5 tabular-nums">{t.people_outside} of {t.people}</td>
                        <td className="whitespace-nowrap px-3 py-2.5 text-ink-2">{peakText(t.peak)}</td>
                      </tr>
                      {isOpen && (
                        <tr>
                          <td colSpan={9} className="border-b border-line p-0"><TeamDetail t={t} /></td>
                        </tr>
                      )}
                    </Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
        {data.hidden_teams.length > 0 && (
          <p className="flex items-center gap-1.5 border-t border-line px-4 py-3 text-xs text-ink-3">
            <Lock size={12} aria-hidden />
            Hidden (fewer than {data.min_team_size} people): {data.hidden_teams.map((h) => `${h.team} (${h.people})`).join(", ")}. They still count in the organisation totals.
          </p>
        )}
      </Card>

      <Card
        title="When people work"
        subtitle={`Events by weekday and local hour, last ${data.window_days} days`}
        action={
          <select value={heatTeam} onChange={(e) => setHeatTeam(e.target.value)} className="rounded-lg border border-line bg-surface px-2 py-1 text-sm" aria-label="Team for heatmap">
            <option value="">Whole organisation</option>
            {data.teams.map((t) => (
              <option key={t.team} value={t.team}>{t.team}</option>
            ))}
          </select>
        }
      >
        <WeekHourHeatmap cells={heat} />
        <p className="mt-3 text-xs text-ink-3">
          Working hours are {data.work_hours.start}–{data.work_hours.end}; anything outside them, or on Saturday/Sunday, counts as out of hours.
        </p>
      </Card>
    </>
  );
}
