"use client";

import { ArrowDownRight, ArrowUpRight, Printer, SlidersHorizontal } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { ActivityGrid } from "@/components/activity-grid";
import {
  Avatar,
  BarList,
  Button,
  Card,
  DataTable,
  Empty,
  ErrorState,
  ExportButton,
  Kpi,
  PageHeader,
  PageSkeleton,
  PersonLink,
  Severity,
  Sparkline,
} from "@/components/ui";
import { WeightsEditor } from "@/components/weights";
import { useApi } from "@/lib/api";
import { fmtDate, fmtNum, titleCase } from "@/lib/format";
import type { Alert, Cell, Me } from "@/lib/types";

type Overview = {
  kpis: {
    users: number;
    suspended: number;
    signed_in_7d: number;
    active_30d: number;
    avg_score: number;
    avg_score_change_pct: number | null;
    twosv_pct: number;
    external_shares_7d: number;
  };
  window: { start: string; end: string };
  grid: Cell[][];
  alerts: Alert[];
  top_people: { id: string; name: string; email: string; department: string | null; title: string | null; photo: string | null; score: number; active_days: number; spark: number[] }[];
  app_adoption: { app: string; users: number; pct: number }[];
  departments: { department: string; users: number; active_pct: number; avg_score: number; twosv_pct: number }[];
  recent_admin_actions: { time: string; actor: string; event: string; type: string | null; target: string | null }[];
};

const APP_LABEL: Record<string, string> = { drive: "Drive", gmail: "Gmail", meet: "Meet", chat: "Chat", calendar: "Calendar" };

function AlertRow({ a }: { a: Alert }) {
  return (
    <li className="flex flex-col gap-2 py-3 sm:flex-row sm:items-start">
      <Severity level={a.severity} />
      <div className="min-w-0 flex-1">
        <Link href={a.link} className="font-medium text-ink hover:underline">
          {a.title}
        </Link>
        {a.detail && <p className="mt-0.5 text-sm text-ink-3">{a.detail}</p>}
        {a.users.length > 0 && (
          <div className="mt-2 flex items-center">
            {a.users.slice(0, 6).map((u) => (
              <Link key={u.email} href={u.id ? `/people/${u.id}` : "#"} title={u.name ?? u.email} className="-mr-1.5 rounded-full ring-2 ring-surface">
                <Avatar name={u.name || u.email} email={u.email} size={24} />
              </Link>
            ))}
            {a.users.length > 6 && <span className="ml-3 text-xs text-ink-3">+{a.users.length - 6} more</span>}
          </div>
        )}
      </div>
    </li>
  );
}

export default function OverviewPage() {
  const { data, error, mutate } = useApi<Overview>("/overview");
  const me = useApi<Me>("/me");
  const [editWeights, setEditWeights] = useState(false);

  if (error) return <ErrorState error={error} retry={() => mutate()} />;
  if (!data) return <PageSkeleton />;
  const k = data.kpis;
  const isAdmin = me.data?.role === "admin";
  const change = k.avg_score_change_pct;

  return (
    <>
      <PageHeader
        title="Overview"
        subtitle={`Activity from ${fmtDate(data.window.start)} to ${fmtDate(data.window.end)} (Google reports usage 2–3 days late)`}
        action={
          <>
            <ExportButton dataset="people" />
            <Button onClick={() => window.print()}>
              <Printer size={14} aria-hidden /> PDF
            </Button>
          </>
        }
      />

      <div className="mb-4 grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
        <Kpi label="People" value={fmtNum(k.users)} hint={k.suspended ? `${k.suspended} suspended` : "all active"} />
        <Kpi label="Signed in · 7d" value={fmtNum(k.signed_in_7d)} hint={`${k.users ? Math.round((100 * k.signed_in_7d) / k.users) : 0}% of people`} />
        <Kpi label="Active · 30d" value={fmtNum(k.active_30d)} hint="any Drive, Gmail, Meet, Chat or Calendar use" />
        <Kpi
          label="Avg activity score"
          value={fmtNum(k.avg_score, 1)}
          tone={change === null ? undefined : change >= 0 ? "good" : "warning"}
          hint={
            change === null ? (
              "no earlier data"
            ) : (
              <span className="inline-flex items-center gap-0.5">
                {change >= 0 ? <ArrowUpRight size={12} aria-hidden /> : <ArrowDownRight size={12} aria-hidden />}
                {Math.abs(change)}% vs previous 30d
              </span>
            )
          }
        />
        <Kpi label="2-Step coverage" value={`${k.twosv_pct}%`} tone={k.twosv_pct < 90 ? "critical" : "good"} hint={k.twosv_pct < 90 ? "below 90% target" : "on target"} />
        <Kpi label="External shares · 7d" value={fmtNum(k.external_shares_7d)} hint="files shared outside the domain" />
      </div>

      <div className="grid items-start gap-4 xl:grid-cols-3">
        <Card
          className="xl:col-span-2"
          title="Organisation activity"
          subtitle="Total weighted activity score per day, last 6 months"
          action={
            isAdmin && (
              <Button variant="ghost" onClick={() => setEditWeights(!editWeights)}>
                <SlidersHorizontal size={14} aria-hidden /> Score weights
              </Button>
            )
          }
        >
          {editWeights && (
            <WeightsEditor
              onSaved={() => {
                setEditWeights(false);
                mutate();
              }}
            />
          )}
          {data.grid.flat().some((c) => c.score > 0) ? (
            <ActivityGrid weeks={data.grid} size={16} />
          ) : (
            <Empty title="No usage data yet">Usage appears after the first sync. Google reports it with a 2–3 day delay.</Empty>
          )}
        </Card>

        <Card className="xl:row-span-2" title="Needs attention" subtitle={`${data.alerts.length} item${data.alerts.length === 1 ? "" : "s"}`} bodyClass="py-0">
          {data.alerts.length ? (
            <ul className="divide-y divide-line">
              {data.alerts.map((a) => (
                <AlertRow key={a.id} a={a} />
              ))}
            </ul>
          ) : (
            <Empty title="All clear">Nothing needs attention right now.</Empty>
          )}
        </Card>

        <Card title="Most active people" subtitle="Score over the last 30 reported days" action={<Link href="/people" className="text-sm text-brand hover:underline">All people</Link>}>
          {data.top_people.length ? (
            <ol className="space-y-3">
              {data.top_people.map((p, i) => (
                <li key={p.id} className="flex items-center gap-3">
                  <span className="w-4 text-right text-xs tabular-nums text-ink-3">{i + 1}</span>
                  <div className="min-w-0 flex-1">
                    <PersonLink id={p.id} name={p.name} email={p.email} sub={p.title ?? p.department ?? p.email} />
                  </div>
                  <Sparkline values={p.spark} />
                  <span className="w-14 text-right text-sm font-medium tabular-nums">{fmtNum(p.score)}</span>
                </li>
              ))}
            </ol>
          ) : (
            <Empty title="No activity yet" />
          )}
        </Card>

        <Card title="Google app adoption" subtitle="Share of active people using each app, last 30 days">
          <BarList
            items={data.app_adoption.map((a) => ({ key: a.app, label: APP_LABEL[a.app] ?? a.app, value: a.pct, hint: `${a.users} people` }))}
            format={(v) => `${v}%`}
            max={100}
          />
        </Card>

        <Card className="xl:col-span-3" title="Departments" subtitle="Average score, active share and 2-Step coverage" action={<Link href="/insights/teams" className="text-sm text-brand hover:underline">Compare</Link>}>
          <DataTable
            rows={data.departments}
            rowKey={(r) => r.department}
            initial={8}
            columns={[
              { header: "Department", cell: (r) => <span className="font-medium">{r.department}</span> },
              { header: "People", cell: (r) => r.users, className: "tabular-nums" },
              { header: "Avg score", cell: (r) => fmtNum(r.avg_score), className: "tabular-nums" },
              { header: "Active", cell: (r) => `${r.active_pct}%`, className: "tabular-nums" },
              { header: "2SV", cell: (r) => `${r.twosv_pct}%`, className: "tabular-nums", hideOnMobile: true },
            ]}
          />
        </Card>

        {isAdmin && (
          <Card className="xl:col-span-3" title="Recent admin actions" action={<Link href="/security?tab=admin" className="text-sm text-brand hover:underline">Admin log</Link>}>
            <DataTable
              rows={data.recent_admin_actions}
              rowKey={(r, i) => `${r.time}-${i}`}
              empty="No admin actions recorded yet"
              columns={[
                { header: "When", cell: (r) => fmtDate(r.time, true), className: "whitespace-nowrap text-ink-2" },
                { header: "Admin", cell: (r) => r.actor },
                { header: "Action", cell: (r) => titleCase(r.event.toLowerCase()) },
                { header: "Target", cell: (r) => r.target ?? "—", hideOnMobile: true },
              ]}
            />
          </Card>
        )}
      </div>
    </>
  );
}
