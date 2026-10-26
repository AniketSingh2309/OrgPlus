"use client";

import { ArrowLeft, Flame, Mail, ShieldAlert, ShieldCheck, Trophy } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import { ActivityGrid } from "@/components/activity-grid";
import { Bars } from "@/components/charts";
import {
  Avatar,
  BarList,
  Card,
  CardSkeleton,
  Chip,
  DataTable,
  Empty,
  ErrorState,
  Kpi,
  PageSkeleton,
  PersonLink,
  RiskChip,
  Tabs,
} from "@/components/ui";
import { RoleList } from "@/components/roles";
import { Timeline } from "@/components/timeline";
import { useApi } from "@/lib/api";
import { fmtDate, fmtMb, fmtNum, timeAgo, titleCase } from "@/lib/format";
import type { Cell } from "@/lib/types";

type Profile = {
  id: string;
  name: string;
  email: string;
  photo: string | null;
  department: string | null;
  title: string | null;
  org_unit: string | null;
  status: string;
  suspension_reason: string | null;
  created: string | null;
  last_login: string | null;
  twosv: { enrolled: boolean; enforced: boolean };
  roles: string[];
  aliases: string[];
  score30: number;
  rank: number;
  ranked_of: number;
  totals30: { metric: string; label: string; value: number }[];
  streaks: { current: number; longest: number; active_days: number };
  manager: { id: string | null; email: string; name: string | null } | null;
  reports: { id: string; email: string; name: string | null; title: string | null }[];
  groups: { id: string; email: string; name: string | null; role: string | null }[];
  storage: { used_mb: number | null; total_mb: number | null; drive_mb: number | null; gmail_mb: number | null; trend: { date: string; used_mb: number }[] };
  licences: { sku: string }[];
};

type TabId = "overview" | "drive" | "meet" | "signins" | "apps";
const GRID_APPS = [
  ["all", "All apps"],
  ["drive", "Drive"],
  ["gmail", "Gmail"],
  ["meet", "Meet"],
  ["chat", "Chat"],
  ["calendar", "Calendar"],
] as const;

function DayPanel({ id, date }: { id: string; date: string }) {
  const { data } = useApi<{
    date: string;
    score: number;
    breakdown: { metric: string; label: string; value: number; weight: number; points: number }[];
    signins: { time: string; event: string; ip: string | null; country: string | null; city: string | null }[];
  }>(`/people/${id}/day/${date}`);
  if (!data) return <CardSkeleton rows={3} />;
  return (
    <div className="mt-4 rounded-lg border border-line bg-surface-2/40 p-4">
      <div className="mb-3 flex items-baseline justify-between">
        <h3 className="text-sm font-semibold">{fmtDate(date)}</h3>
        <span className="text-sm text-ink-2">
          Score <strong className="text-ink">{data.score}</strong>
        </span>
      </div>
      {data.breakdown.length ? (
        <ul className="grid gap-1 text-sm sm:grid-cols-2">
          {data.breakdown.map((b) => (
            <li key={b.metric} className="flex justify-between gap-2">
              <span className="text-ink-2">{b.label}</span>
              <span className="tabular-nums">
                {fmtNum(b.value, 1)} × {b.weight} = <strong>{b.points}</strong>
              </span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-sm text-ink-3">No recorded activity this day.</p>
      )}
      <h4 className="mb-1 mt-4 text-xs font-semibold uppercase tracking-wide text-ink-3">Sign-ins</h4>
      {data.signins.length ? (
        <ul className="text-sm">
          {data.signins.map((s, i) => (
            <li key={i} className="flex flex-wrap gap-x-3 text-ink-2">
              <span className="tabular-nums">{new Date(s.time).toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" })}</span>
              <span>{titleCase(s.event)}</span>
              <span>{[s.city, s.country].filter(Boolean).join(", ") || s.ip}</span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-sm text-ink-3">No sign-ins recorded.</p>
      )}
    </div>
  );
}

function OverviewTab({ p }: { p: Profile }) {
  const [app, setApp] = useState<(typeof GRID_APPS)[number][0]>("all");
  const [day, setDay] = useState<string | null>(null);
  const grid = useApi<{ weeks: Cell[][]; total: number; active_days: number }>(`/people/${p.id}/grid?app=${app}`);
  const usedPct = p.storage.used_mb && p.storage.total_mb ? Math.round((100 * p.storage.used_mb) / p.storage.total_mb) : null;

  return (
    <div className="grid gap-4 xl:grid-cols-3">
      <Card
        className="xl:col-span-3"
        title="Activity, last 6 months"
        subtitle={grid.data ? `${grid.data.active_days} active days · click a day for details` : undefined}
        action={
          <select
            value={app}
            onChange={(e) => {
              setApp(e.target.value as typeof app);
              setDay(null);
            }}
            className="rounded-lg border border-line bg-surface px-2 py-1 text-sm"
            aria-label="App"
          >
            {GRID_APPS.map(([v, l]) => (
              <option key={v} value={v}>
                {l}
              </option>
            ))}
          </select>
        }
      >
        {grid.data ? (
          <ActivityGrid weeks={grid.data.weeks} onSelect={setDay} selected={day} unit={app === "all" ? "points" : "actions"} />
        ) : (
          <CardSkeleton rows={2} />
        )}
        {day && <DayPanel id={p.id} date={day} />}
      </Card>

      <Card title="Last 30 days">
        <BarList items={p.totals30.filter((t) => t.value > 0).map((t) => ({ key: t.metric, label: t.label, value: t.value }))} format={(v) => fmtNum(v, 1)} />
      </Card>

      <Card title="Organisation">
        <dl className="space-y-3 text-sm">
          <div>
            <dt className="text-xs text-ink-3">Manager</dt>
            <dd className="mt-1">{p.manager ? <PersonLink id={p.manager.id} name={p.manager.name} email={p.manager.email} /> : "—"}</dd>
          </div>
          <div>
            <dt className="text-xs text-ink-3">Direct reports ({p.reports.length})</dt>
            <dd className="mt-1 space-y-2">
              {p.reports.length ? p.reports.slice(0, 8).map((r) => <PersonLink key={r.id} id={r.id} name={r.name} email={r.email} sub={r.title ?? r.email} />) : "None"}
            </dd>
          </div>
          <div>
            <dt className="text-xs text-ink-3">Groups ({p.groups.length})</dt>
            <dd className="mt-1 flex flex-wrap gap-1">
              {p.groups.length ? p.groups.map((g) => <Chip key={g.id}>{g.name ?? g.email}{g.role === "OWNER" ? " · owner" : ""}</Chip>) : "None"}
            </dd>
          </div>
        </dl>
      </Card>

      <Card title="Storage & licence">
        <div className="text-2xl font-semibold tabular-nums">{fmtMb(p.storage.used_mb)}</div>
        <div className="text-sm text-ink-3">of {p.storage.total_mb ? fmtMb(p.storage.total_mb) : "pooled storage"}</div>
        {usedPct !== null && (
          <div className="mt-2 h-2 rounded-full bg-surface-2" role="progressbar" aria-valuenow={usedPct} aria-valuemin={0} aria-valuemax={100}>
            <div className={usedPct >= 90 ? "h-2 rounded-full bg-critical" : "h-2 rounded-full bg-brand"} style={{ width: `${Math.min(usedPct, 100)}%` }} />
          </div>
        )}
        <div className="mt-3 grid grid-cols-2 gap-2 text-sm">
          <div>
            <div className="text-xs text-ink-3">Drive</div>
            {fmtMb(p.storage.drive_mb)}
          </div>
          <div>
            <div className="text-xs text-ink-3">Gmail</div>
            {fmtMb(p.storage.gmail_mb)}
          </div>
        </div>
        <div className="mt-3 flex flex-wrap gap-1">
          {p.licences.length ? p.licences.map((l) => <Chip key={l.sku} tone="brand">{l.sku}</Chip>) : <span className="text-sm text-ink-3">No licence data</span>}
        </div>
      </Card>

      <Card className="xl:col-span-3" title="Timeline" subtitle="Everything they did in the last 2 months · repeated actions are grouped">
        <Timeline userId={p.id} />
      </Card>
    </div>
  );
}

function DriveTab({ id }: { id: string }) {
  const { data } = useApi<{
    events: { time: string; event: string; title: string | null; type: string | null; visibility: string | null; external: boolean | null; target: string | null }[];
    by_event: Record<string, number>;
    by_type: Record<string, number>;
    external_count: number;
  }>(`/people/${id}/drive`);
  if (!data) return <CardSkeleton />;
  return (
    <div className="grid gap-4 lg:grid-cols-3">
      <Card title="Actions · 14 days">
        <BarList items={Object.entries(data.by_event).map(([k, v]) => ({ key: k, label: titleCase(k), value: v }))} />
      </Card>
      <Card title="File types">
        <BarList items={Object.entries(data.by_type).map(([k, v]) => ({ key: k, label: titleCase(k), value: v }))} />
      </Card>
      <Kpi label="Shared outside the domain" value={data.external_count} hint="file events with external visibility, 14 days" tone={data.external_count ? "critical" : undefined} />
      <Card className="lg:col-span-3" title="File activity" subtitle="Titles and metadata only; content is never read">
        <DataTable
          rows={data.events}
          rowKey={(r, i) => `${r.time}-${i}`}
          empty="No Drive activity in the last 14 days"
          columns={[
            { header: "When", cell: (r) => <span className="whitespace-nowrap text-ink-2">{fmtDate(r.time, true)}</span> },
            { header: "Action", cell: (r) => titleCase(r.event) },
            { header: "File", cell: (r) => <span className="font-medium">{r.title ?? "Untitled"}</span> },
            { header: "Type", cell: (r) => r.type ?? "—", hideOnMobile: true },
            {
              header: "Visibility",
              cell: (r) => (r.external ? <Chip tone="critical">{titleCase(r.visibility ?? "external")}</Chip> : <span className="text-ink-3">{titleCase(r.visibility ?? "—")}</span>),
            },
          ]}
        />
      </Card>
    </div>
  );
}

function MeetTab({ id }: { id: string }) {
  const { data } = useApi<{
    calls: { time: string; minutes: number; meeting_code: string | null; organizer: string | null; is_organizer: boolean; device: string | null; external: boolean }[];
    hours_by_week: { week: string; hours: number }[];
    total_hours: number;
    organized: number;
  }>(`/people/${id}/meet`);
  if (!data) return <CardSkeleton />;
  return (
    <div className="grid gap-4 lg:grid-cols-3">
      <Kpi label="Meeting hours" value={fmtNum(data.total_hours, 1)} hint={`${data.calls.length} recent calls`} />
      <Kpi label="Calls organised" value={data.organized} />
      <Kpi label="With external guests" value={data.calls.filter((c) => c.external).length} />
      <Card className="lg:col-span-3" title="Hours in Meet per week">
        {data.hours_by_week.length ? (
          <Bars data={data.hours_by_week.map((w) => ({ ...w, label: fmtDate(w.week).replace(/ \d{4}$/, "") }))} x="label" y="hours" label="Hours" unit="h" />
        ) : (
          <Empty title="No calls recorded" />
        )}
      </Card>
      <Card className="lg:col-span-3" title="Recent calls">
        <DataTable
          rows={data.calls}
          rowKey={(r, i) => `${r.time}-${i}`}
          empty="No calls recorded"
          columns={[
            { header: "When", cell: (r) => <span className="whitespace-nowrap text-ink-2">{fmtDate(r.time, true)}</span> },
            { header: "Length", cell: (r) => `${Math.round(r.minutes)} min`, className: "tabular-nums" },
            { header: "Meeting", cell: (r) => r.meeting_code ?? "—", hideOnMobile: true },
            { header: "Organiser", cell: (r) => (r.is_organizer ? <Chip tone="brand">You</Chip> : r.organizer ?? "—") },
            { header: "Device", cell: (r) => r.device ?? "—", hideOnMobile: true },
            { header: "", cell: (r) => r.external && <Chip>External</Chip> },
          ]}
        />
      </Card>
    </div>
  );
}

function SigninsTab({ id }: { id: string }) {
  const { data } = useApi<{
    signins: { time: string; event: string; ip: string | null; country: string | null; city: string | null; login_type: string | null; challenge: string | null; suspicious: boolean; app: string | null }[];
    success: number;
    failure: number;
    countries: string[];
  }>(`/people/${id}/signins`);
  if (!data) return <CardSkeleton />;
  return (
    <div className="grid gap-4 lg:grid-cols-3">
      <Kpi label="Successful · 30d" value={data.success} />
      <Kpi label="Failed · 30d" value={data.failure} tone={data.failure >= 3 ? "critical" : undefined} hint={data.failure >= 3 ? "3 or more failures" : undefined} />
      <Kpi label="Countries" value={data.countries.length} hint={data.countries.join(", ") || "—"} />
      <Card className="lg:col-span-3" title="Sign-in log · 30 days">
        <DataTable
          rows={data.signins}
          rowKey={(r, i) => `${r.time}-${i}`}
          empty="No sign-ins in the last 30 days"
          columns={[
            { header: "When", cell: (r) => <span className="whitespace-nowrap text-ink-2">{fmtDate(r.time, true)}</span> },
            {
              header: "Result",
              cell: (r) =>
                r.suspicious ? (
                  <Chip tone="critical">
                    <ShieldAlert size={12} aria-hidden /> Suspicious
                  </Chip>
                ) : r.event === "login_failure" ? (
                  <Chip tone="serious">Failed</Chip>
                ) : (
                  <span className="text-ink-2">{r.app ? `SSO: ${r.app}` : titleCase(r.event)}</span>
                ),
            },
            { header: "Location", cell: (r) => [r.city, r.country].filter(Boolean).join(", ") || "—" },
            { header: "IP", cell: (r) => <span className="font-mono text-xs">{r.ip ?? "—"}</span>, hideOnMobile: true },
            { header: "Method", cell: (r) => titleCase(r.login_type ?? "—"), hideOnMobile: true },
          ]}
        />
      </Card>
    </div>
  );
}

function AppsTab({ id }: { id: string }) {
  const { data } = useApi<{
    tokens: { client_id: string; name: string; scopes: string[]; risk: string; unverified: boolean; last_used: string | null }[];
    sso_apps: { app: string; signins: number; last: string | null }[];
    devices: { kind: string; id: string; model: string | null; os: string | null; status: string | null; type: string | null; last_sync: string | null }[];
  }>(`/people/${id}/apps`);
  if (!data) return <CardSkeleton />;
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card className="lg:col-span-2" title="Third-party apps with access" subtitle="OAuth grants on this account">
        <DataTable
          rows={data.tokens}
          rowKey={(r) => r.client_id}
          empty="No third-party apps"
          columns={[
            { header: "App", cell: (r) => <span className="font-medium">{r.name}</span> },
            { header: "Risk", cell: (r) => <RiskChip risk={r.risk} /> },
            {
              header: "Access",
              cell: (r) => (
                <span className="text-xs text-ink-2">
                  {r.scopes.map((s) => s.replace("https://www.googleapis.com/auth/", "")).join(", ")}
                </span>
              ),
            },
            { header: "Last used", cell: (r) => timeAgo(r.last_used), hideOnMobile: true },
          ]}
        />
      </Card>
      <Card title="SSO apps">
        <DataTable
          rows={data.sso_apps}
          rowKey={(r) => r.app}
          empty="No SAML sign-ins"
          columns={[
            { header: "App", cell: (r) => r.app },
            { header: "Sign-ins", cell: (r) => r.signins, className: "tabular-nums" },
            { header: "Last", cell: (r) => timeAgo(r.last) },
          ]}
        />
      </Card>
      <Card title="Devices">
        <DataTable
          rows={data.devices}
          rowKey={(r) => `${r.kind}-${r.id}`}
          empty="No managed devices"
          columns={[
            { header: "Device", cell: (r) => <span className="font-medium">{r.model ?? r.type ?? "Unknown"}</span> },
            { header: "OS", cell: (r) => r.os ?? "—" },
            { header: "Status", cell: (r) => <Chip tone={r.status === "APPROVED" || r.status === "ACTIVE" ? "good" : "neutral"}>{titleCase((r.status ?? "unknown").toLowerCase())}</Chip> },
            { header: "Last sync", cell: (r) => timeAgo(r.last_sync), hideOnMobile: true },
          ]}
        />
      </Card>
    </div>
  );
}

export default function PersonPage() {
  const params = useParams<{ id: string }>();
  const { data: p, error, mutate } = useApi<Profile>(`/people/${params.id}`);
  const [tab, setTab] = useState<TabId>("overview");

  if (error) return <ErrorState error={error} retry={() => mutate()} />;
  if (!p) return <PageSkeleton />;

  return (
    <>
      <Link href="/people" className="no-print mb-3 inline-flex items-center gap-1 text-sm text-ink-2 hover:text-ink">
        <ArrowLeft size={14} aria-hidden /> People
      </Link>
      <div className="mb-5 flex flex-col gap-4 sm:flex-row sm:items-center">
        <Avatar name={p.name} email={p.email} photo={p.photo} size={64} />
        <div className="min-w-0 flex-1">
          <h1 className="text-xl font-semibold tracking-tight sm:text-2xl">{p.name}</h1>
          <p className="text-sm text-ink-2">{[p.title, p.department, p.org_unit].filter(Boolean).join(" · ")}</p>
          <div className="mt-2 flex flex-wrap items-center gap-2 text-sm">
            <span className="inline-flex items-center gap-1 text-ink-2">
              <Mail size={14} aria-hidden /> {p.email}
            </span>
            <Chip tone={p.status === "active" ? "good" : p.status === "inactive" ? "warning" : "neutral"}>{titleCase(p.status)}</Chip>
            {p.twosv.enrolled ? (
              <Chip tone="good">
                <ShieldCheck size={12} aria-hidden /> 2-Step on
              </Chip>
            ) : (
              <Chip tone="critical">
                <ShieldAlert size={12} aria-hidden /> No 2-Step
              </Chip>
            )}
            <RoleList roles={p.roles} />
          </div>
        </div>
      </div>

      <div className="mb-5 grid grid-cols-2 gap-3 lg:grid-cols-5">
        <Kpi label="Score · 30d" value={fmtNum(p.score30)} hint={`#${p.rank} of ${p.ranked_of}`} />
        <Kpi
          label="Current streak"
          value={
            <span className="inline-flex items-center gap-1">
              <Flame size={18} className="text-serious" aria-hidden /> {p.streaks.current}d
            </span>
          }
          hint="weekends don't break it"
        />
        <Kpi
          label="Longest streak"
          value={
            <span className="inline-flex items-center gap-1">
              <Trophy size={18} className="text-ink-3" aria-hidden /> {p.streaks.longest}d
            </span>
          }
        />
        <Kpi label="Last sign-in" value={<span className="text-lg">{timeAgo(p.last_login)}</span>} hint={fmtDate(p.last_login, true)} />
        <Kpi label="Account created" value={<span className="text-lg">{fmtDate(p.created)}</span>} />
      </div>

      <Tabs<TabId>
        value={tab}
        onChange={setTab}
        tabs={[
          { id: "overview", label: "Overview" },
          { id: "drive", label: "Drive activity" },
          { id: "meet", label: "Meetings" },
          { id: "signins", label: "Sign-ins" },
          { id: "apps", label: "Apps & devices" },
        ]}
      />
      {tab === "overview" && <OverviewTab p={p} />}
      {tab === "drive" && <DriveTab id={p.id} />}
      {tab === "meet" && <MeetTab id={p.id} />}
      {tab === "signins" && <SigninsTab id={p.id} />}
      {tab === "apps" && <AppsTab id={p.id} />}
    </>
  );
}
