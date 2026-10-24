"use client";

import clsx from "clsx";
import { ChevronDown, ChevronRight, ShieldAlert } from "lucide-react";
import { Fragment, useState } from "react";
import { Card, Chip, Empty, ErrorState, ExportButton, Kpi, PageHeader, PageSkeleton, PersonLink } from "@/components/ui";
import { useApi } from "@/lib/api";
import { fmtDate, fmtNum, timeAgo } from "@/lib/format";

type Member = {
  id: string;
  name: string;
  email: string;
  title: string | null;
  score: number;
  active_days: number;
  meet_hours_per_week: number;
  twosv: boolean;
  admin: boolean;
  last_login: string | null;
};
type Team = {
  department: string;
  users: number;
  avg_score: number;
  active_pct: number;
  twosv_pct: number;
  adoption: Record<string, number>;
  meet_hours_per_week: number;
  after_hours_pct: number | null;
  weekend_pct: number | null;
  external_shares_30d: number;
  storage_gb: number;
  inactive_30d: number;
  admins: number;
  no_2sv: number;
  members: Member[];
};
type Data = { teams: Team[]; window: { start: string; end: string }; team_rule: string };

const APPS = ["drive", "gmail", "meet", "chat", "calendar"] as const;
const SORTS = {
  users: { label: "Team size", key: (t: Team) => -t.users },
  avg_score: { label: "Avg activity score", key: (t: Team) => -t.avg_score },
  active_pct: { label: "Active share", key: (t: Team) => -t.active_pct },
  twosv_pct: { label: "2-Step coverage (lowest first)", key: (t: Team) => t.twosv_pct },
  meet: { label: "Meeting load", key: (t: Team) => -t.meet_hours_per_week },
} as const;

/** Percent with an inline bar so columns compare at a glance. */
function Pct({ v, warnBelow }: { v: number | null; warnBelow?: number }) {
  if (v === null) return <span className="text-ink-3" title="Hidden for teams under 3 people">—</span>;
  return (
    <span className="flex items-center gap-2">
      <span className="h-1.5 w-12 shrink-0 rounded-full bg-surface-2">
        <span className="block h-1.5 rounded-full bg-brand" style={{ width: `${Math.min(v, 100)}%` }} />
      </span>
      <span className={clsx("tabular-nums", warnBelow !== undefined && v < warnBelow && "text-critical")}>{v}%</span>
    </span>
  );
}

function Members({ team }: { team: Team }) {
  return (
    <div className="grid gap-4 bg-surface-2/40 px-4 py-4 lg:grid-cols-3">
      <div className="space-y-3 text-sm">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-ink-3">App adoption</h3>
        {APPS.map((a) => (
          <div key={a} className="flex items-center justify-between gap-3">
            <span className="capitalize text-ink-2">{a}</span>
            <Pct v={team.adoption[a] ?? 0} />
          </div>
        ))}
        <h3 className="pt-2 text-xs font-semibold uppercase tracking-wide text-ink-3">Work rhythm · 30 days</h3>
        <div className="flex justify-between">
          <span className="text-ink-2">Outside working hours</span>
          <span className="tabular-nums">{team.after_hours_pct ?? "—"}{team.after_hours_pct !== null && "%"}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-ink-2">On weekends</span>
          <span className="tabular-nums">{team.weekend_pct ?? "—"}{team.weekend_pct !== null && "%"}</span>
        </div>
      </div>
      <div className="lg:col-span-2">
        <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-ink-3">Members ({team.members.length})</h3>
        <div className="max-h-96 overflow-auto rounded-lg border border-line bg-surface">
          <table className="w-full min-w-[560px] text-left text-sm">
            <thead className="sticky top-0 bg-surface">
              <tr className="border-b border-line text-xs uppercase tracking-wide text-ink-3">
                <th className="px-3 py-2 font-medium">Person</th>
                <th className="px-3 py-2 font-medium">Score · 30d</th>
                <th className="px-3 py-2 font-medium">Active days</th>
                <th className="px-3 py-2 font-medium">Meet h/wk</th>
                <th className="px-3 py-2 font-medium">Last sign-in</th>
                <th className="px-3 py-2 font-medium" />
              </tr>
            </thead>
            <tbody>
              {team.members.map((m) => (
                <tr key={m.id} className="border-b border-line/60 last:border-0">
                  <td className="px-3 py-2"><PersonLink id={m.id} name={m.name} email={m.email} sub={m.title ?? m.email} /></td>
                  <td className="px-3 py-2 tabular-nums">{fmtNum(m.score)}</td>
                  <td className="px-3 py-2 tabular-nums">{m.active_days}</td>
                  <td className="px-3 py-2 tabular-nums">{m.meet_hours_per_week}</td>
                  <td className="whitespace-nowrap px-3 py-2 text-ink-2">{timeAgo(m.last_login)}</td>
                  <td className="px-3 py-2">
                    <span className="flex flex-wrap gap-1">
                      {!m.twosv && <Chip tone="critical"><ShieldAlert size={12} aria-hidden /> No 2SV</Chip>}
                      {m.admin && <Chip tone="brand">Admin</Chip>}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

export default function TeamsPage() {
  const { data, error, mutate } = useApi<Data>("/insights/teams");
  const [open, setOpen] = useState<string | null>(null);
  const [sort, setSort] = useState<keyof typeof SORTS>("users");
  if (error) return <ErrorState error={error} retry={() => mutate()} />;
  if (!data) return <PageSkeleton />;
  const teams = [...data.teams].sort((a, b) => SORTS[sort].key(a) - SORTS[sort].key(b));
  const people = data.teams.reduce((n, t) => n + t.users, 0);
  const noTwosv = data.teams.reduce((n, t) => n + t.no_2sv, 0);
  const inactive = data.teams.reduce((n, t) => n + t.inactive_30d, 0);

  return (
    <>
      <PageHeader
        title="Team comparison"
        subtitle={`${fmtDate(data.window.start)} – ${fmtDate(data.window.end)} · Team = ${data.team_rule}`}
        action={<ExportButton dataset="teams" />}
      />
      <div className="mb-4 grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Kpi label="Teams" value={data.teams.length} hint={`${people} people`} />
        <Kpi label="Most active team" value={<span className="text-lg">{[...data.teams].sort((a, b) => b.avg_score - a.avg_score)[0]?.department ?? "—"}</span>} hint="by average activity score" />
        <Kpi label="Without 2-Step" value={noTwosv} tone={noTwosv ? "critical" : "good"} hint="across all teams" />
        <Kpi label="No sign-in 30d+" value={inactive} hint="across all teams" />
      </div>
      <Card
        title="Teams"
        subtitle="Click a team to see its members, app adoption and work rhythm"
        bodyClass="p-0"
        action={
          <select value={sort} onChange={(e) => setSort(e.target.value as keyof typeof SORTS)} className="rounded-lg border border-line bg-surface px-2 py-1 text-sm" aria-label="Sort teams">
            {Object.entries(SORTS).map(([k, v]) => (
              <option key={k} value={k}>Sort: {v.label}</option>
            ))}
          </select>
        }
      >
        {!teams.length ? (
          <Empty title="No teams yet" />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[980px] text-left text-sm">
              <thead>
                <tr className="border-b border-line text-xs uppercase tracking-wide text-ink-3">
                  <th className="px-4 py-2 font-medium">Team</th>
                  <th className="px-3 py-2 font-medium">People</th>
                  <th className="px-3 py-2 font-medium">Avg score</th>
                  <th className="px-3 py-2 font-medium">Active</th>
                  <th className="px-3 py-2 font-medium">2-Step</th>
                  <th className="px-3 py-2 font-medium">Meet h/wk</th>
                  <th className="px-3 py-2 font-medium">After hours</th>
                  <th className="px-3 py-2 font-medium">Ext. shares</th>
                  <th className="px-3 py-2 font-medium">Storage</th>
                  <th className="px-3 py-2 font-medium">Inactive</th>
                  <th className="px-3 py-2 font-medium">Admins</th>
                </tr>
              </thead>
              <tbody>
                {teams.map((t) => {
                  const isOpen = open === t.department;
                  return (
                    <Fragment key={t.department}>
                      <tr
                        className={clsx("cursor-pointer border-b border-line/60 hover:bg-surface-2/60", isOpen && "bg-surface-2/60")}
                        onClick={() => setOpen(isOpen ? null : t.department)}
                      >
                        <td className="px-4 py-2.5">
                          <button className="flex items-center gap-1.5 font-medium text-ink" aria-expanded={isOpen}>
                            {isOpen ? <ChevronDown size={14} aria-hidden /> : <ChevronRight size={14} aria-hidden />}
                            {t.department}
                          </button>
                        </td>
                        <td className="px-3 py-2.5 tabular-nums">{t.users}</td>
                        <td className="px-3 py-2.5 tabular-nums">{fmtNum(t.avg_score)}</td>
                        <td className="px-3 py-2.5"><Pct v={t.active_pct} /></td>
                        <td className="px-3 py-2.5"><Pct v={t.twosv_pct} warnBelow={90} /></td>
                        <td className="px-3 py-2.5 tabular-nums">{t.meet_hours_per_week}</td>
                        <td className="px-3 py-2.5 tabular-nums">{t.after_hours_pct === null ? "—" : `${t.after_hours_pct}%`}</td>
                        <td className="px-3 py-2.5 tabular-nums">{t.external_shares_30d}</td>
                        <td className="px-3 py-2.5 tabular-nums">{t.storage_gb} GB</td>
                        <td className="px-3 py-2.5 tabular-nums">{t.inactive_30d || "—"}</td>
                        <td className="px-3 py-2.5 tabular-nums">{t.admins || "—"}</td>
                      </tr>
                      {isOpen && (
                        <tr>
                          <td colSpan={11} className="border-b border-line p-0">
                            <Members team={t} />
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </>
  );
}
