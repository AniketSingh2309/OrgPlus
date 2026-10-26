"use client";

import { useParams } from "next/navigation";
import type { JSX } from "react";
import { TrendChart } from "@/components/charts";
import { Feature, LockedCard, useCapabilities } from "@/components/feature";
import { BarList, Card, CardSkeleton, Chip, DataTable, Empty, ErrorState, Kpi, PageHeader, PageSkeleton, PersonLink } from "@/components/ui";
import { useApi } from "@/lib/api";
import { fmtDate, timeAgo, titleCase } from "@/lib/format";

/* eslint-disable @typescript-eslint/no-explicit-any */
type Any = any;

const keyed = (rows: { key: string; [k: string]: Any }[], field: string) =>
  rows.map((r) => ({ key: r.key, label: r.key, value: r[field] as number }));

function useModule(key: string, path = "") {
  return useApi<Any>(`/m/${key}${path}`);
}

function Loading({ error }: { error?: Error }) {
  return error ? <ErrorState error={error} /> : <CardSkeleton />;
}

function Dlp() {
  const { data, error } = useModule("dlp_events");
  if (!data) return <Loading error={error} />;
  return (
    <div className="grid gap-4 lg:grid-cols-3">
      <Card title="By person"><BarList items={keyed(data.by_person, "hits")} /></Card>
      <Card title="By rule"><BarList items={keyed(data.by_rule, "hits")} /></Card>
      <Card title="By file"><BarList items={keyed(data.by_file, "hits")} /></Card>
      <Card className="lg:col-span-3" title="Recent rule hits">
        <DataTable rows={data.recent} rowKey={(_, i) => String(i)} empty="No DLP hits in 30 days" columns={[
          { header: "When", cell: (r: Any) => fmtDate(r.time, true) },
          { header: "User", cell: (r: Any) => r.user },
          { header: "Rule", cell: (r: Any) => r.rule ?? "—" },
          { header: "File", cell: (r: Any) => r.title ?? "—" },
        ]} />
      </Card>
    </div>
  );
}

function Caa() {
  const { data, error } = useModule("context_aware_access");
  if (!data) return <Loading error={error} />;
  return (
    <div className="grid gap-4 lg:grid-cols-3">
      <Kpi label="Blocked attempts · 30d" value={data.total} />
      <Card title="By person"><BarList items={keyed(data.by_user, "blocks")} /></Card>
      <Card title="By rule"><BarList items={keyed(data.by_reason, "blocks")} /></Card>
      <Card className="lg:col-span-3" title="Recent blocks">
        <DataTable rows={data.recent} rowKey={(_, i) => String(i)} empty="No blocked access in 30 days" columns={[
          { header: "When", cell: (r: Any) => fmtDate(r.time, true) },
          { header: "User", cell: (r: Any) => r.user },
          { header: "Event", cell: (r: Any) => titleCase(r.event) },
          { header: "Location", cell: (r: Any) => r.country ?? r.ip ?? "—" },
        ]} />
      </Card>
    </div>
  );
}

function Gemini() {
  const { data, error } = useModule("gemini_usage");
  if (!data) return <Loading error={error} />;
  return (
    <div className="grid gap-4 lg:grid-cols-3">
      <Kpi label="People using Gemini · 90d" value={data.adopters} hint={`${data.adoption_pct}% of active accounts`} />
      <Card className="lg:col-span-2" title="Weekly Gemini users">
        {data.trend.length ? <TrendChart data={data.trend} x="week" series={[{ key: "users", label: "People" }]} unit="people" xFormat={(v) => fmtDate(v).replace(/ \d{4}$/, "")} /> : <Empty title="No Gemini use yet" />}
      </Card>
      <Card title="By app"><BarList items={data.by_app.map((a: Any) => ({ key: a.app, label: titleCase(a.app), value: a.uses }))} /></Card>
      <Card className="lg:col-span-2" title="By person">
        <DataTable rows={data.people} rowKey={(r: Any) => r.user} columns={[
          { header: "Person", cell: (r: Any) => r.user },
          { header: "Uses", cell: (r: Any) => r.uses, className: "tabular-nums" },
          { header: "Last used", cell: (r: Any) => timeAgo(r.last) },
        ]} />
      </Card>
    </div>
  );
}

function EmailFlow() {
  const { data, error } = useModule("gmail_logs");
  if (!data) return <Loading error={error} />;
  return (
    <div className="grid gap-4 lg:grid-cols-4">
      <Kpi label="Messages · 7d" value={data.messages} />
      <Kpi label="Internal" value={data.internal} />
      <Kpi label="External" value={data.external} />
      <Kpi label="Bounce rate" value={`${data.bounce_rate_pct}%`} />
      <Card className="lg:col-span-2" title="Top external domains"><BarList items={data.top_external_domains.map((d: Any) => ({ key: d.domain, label: d.domain, value: d.messages }))} /></Card>
      <Card className="lg:col-span-2" title="Emails sent per person" subtitle="Metadata only">
        <DataTable rows={data.sent_by_hour} rowKey={(r: Any) => r.user} columns={[
          { header: "Person", cell: (r: Any) => r.user },
          { header: "Sent", cell: (r: Any) => r.total, className: "tabular-nums" },
          { header: "Busiest hour", cell: (r: Any) => `${r.hours.indexOf(Math.max(...r.hours))}:00` },
        ]} />
      </Card>
    </div>
  );
}

function Vault() {
  const { data, error } = useModule("vault");
  if (!data) return <Loading error={error} />;
  return (
    <div className="grid gap-4 lg:grid-cols-3">
      <Kpi label="Open matters" value={data.open_matters} />
      <Kpi label="Closed matters" value={data.closed_matters} />
      <Kpi label="People on hold" value={data.users_on_hold.length} />
      <Card className="lg:col-span-3" title="Accounts under legal hold" subtitle="No content is read">
        <DataTable rows={data.users_on_hold} rowKey={(r: Any) => r.email} empty="Nobody is on hold" columns={[
          { header: "Account", cell: (r: Any) => r.email },
          { header: "Holds", cell: (r: Any) => r.holds.join("; ") },
        ]} />
      </Card>
    </div>
  );
}

function AlertCenter() {
  const { data, error } = useModule("alert_center");
  if (!data) return <Loading error={error} />;
  return (
    <div className="grid gap-4 lg:grid-cols-3">
      <Card title="By type"><BarList items={Object.entries(data.by_type as Record<string, number>).map(([k, v]) => ({ key: k, label: k, value: v }))} /></Card>
      <Card className="lg:col-span-2" title="Alerts · 30 days">
        <DataTable rows={data.alerts} rowKey={(r: Any) => r.alertId} empty="No alerts" columns={[
          { header: "When", cell: (r: Any) => fmtDate(r.createTime, true) },
          { header: "Type", cell: (r: Any) => r.type },
          { header: "Severity", cell: (r: Any) => <Chip tone={r.severity === "HIGH" ? "critical" : "neutral"}>{r.severity ?? "—"}</Chip> },
          { header: "Status", cell: (r: Any) => r.status ?? "—" },
        ]} />
      </Card>
    </div>
  );
}

function Chrome() {
  const { data, error } = useModule("chrome_mgmt");
  if (!data) return <Loading error={error} />;
  if (!data.versions.length && !data.extensions.length) {
    // The API answers, but only Chrome browsers enrolled in Chrome Enterprise Core report to it.
    return (
      <Card title="No managed Chrome browsers are reporting yet">
        <div className="max-w-2xl space-y-3 text-sm text-ink-2">
          <p>
            Google shares Chrome data only for browsers enrolled in <strong className="text-ink">Chrome Enterprise Core</strong>, which is free.
            Your domain has none enrolled yet, so there are no versions or extensions to report.
          </p>
          <ol className="list-decimal space-y-1 pl-5">
            <li>Admin console → Devices → Chrome → Managed browsers → <strong className="text-ink">Enroll</strong> to get an enrollment token.</li>
            <li>Deploy the token to your computers (Windows registry / macOS profile / Linux policy file), or let users sign in to a managed profile.</li>
            <li>Turn on reporting: Devices → Chrome → Settings → Users &amp; browsers → <strong className="text-ink">Browser reporting</strong>.</li>
          </ol>
          <p>Browsers appear here within a day of enrolling. Org+ checks again every 24 hours.</p>
          <a href="https://support.google.com/chrome/a/answer/9301891" target="_blank" rel="noreferrer" className="inline-block font-medium text-brand hover:underline">
            Google&apos;s enrollment guide →
          </a>
        </div>
      </Card>
    );
  }
  return (
    <div className="grid gap-4 lg:grid-cols-3">
      <Kpi label="Latest Chrome major" value={data.latest_major || "—"} />
      <Kpi label="Outdated browsers" value={data.outdated_devices} hint="more than 2 versions behind" tone={data.outdated_devices ? "critical" : "good"} />
      <Kpi label="Risky extensions" value={data.extensions.filter((e: Any) => e.risky).length} />
      <Card className="lg:col-span-3" title="Extensions">
        <DataTable rows={data.extensions} rowKey={(r: Any) => r.id} columns={[
          { header: "Extension", cell: (r: Any) => r.name },
          { header: "Installs", cell: (r: Any) => r.installs ?? "—" },
          { header: "Risk", cell: (r: Any) => (r.risky ? <Chip tone="critical">Broad permissions</Chip> : <Chip tone="good">OK</Chip>) },
          { header: "Permissions", cell: (r: Any) => <span className="text-xs text-ink-2">{r.permissions.join(", ")}</span>, hideOnMobile: true },
        ]} />
      </Card>
    </div>
  );
}

function BigQuery() {
  const { data, error } = useModule("bigquery_logs", "/yoy");
  if (!data) return <Loading error={error} />;
  const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const rows = months.map((m, i) => ({ month: m, ...Object.fromEntries(data.years.map((y: Any) => [String(y.year), y.monthly_score_per_user[i]])) }));
  return (
    <Card title="Year on year" subtitle="Monthly activity score per person">
      <TrendChart data={rows} x="month" series={data.years.slice(-3).map((y: Any) => ({ key: String(y.year), label: String(y.year) }))} />
    </Card>
  );
}

const CLASSROOM_EVENT: Record<string, string> = {
  created_course: "Created class",
  user_joined_course: "Joined class",
  published_course_work: "Posted classwork",
  created_course_work: "Created classwork",
  updated_course_work: "Edited classwork",
  updated_announcement: "Edited announcement",
  published_announcement: "Posted announcement",
  created_announcement: "Posted announcement",
};

function Classroom() {
  const { data, error } = useModule("classroom");
  if (!data) return <Loading error={error} />;
  const tot = data.totals ?? {};
  if (!data.courses.length) {
    return <Empty title="No classes yet">Classes appear here within 12 hours of being created in Google Classroom.</Empty>;
  }
  return (
    <div className="grid gap-4 lg:grid-cols-3">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6 lg:col-span-3">
        <Kpi label="Classes" value={tot.courses ?? data.courses.length} hint={`${tot.active_courses ?? 0} active`} />
        <Kpi label="Teachers" value={data.teachers.length} />
        <Kpi label="Students enrolled" value={tot.students ?? 0} />
        <Kpi label="Assignments" value={tot.assignments ?? 0} hint="graded classwork" />
        <Kpi label="Posts & announcements" value={(tot.posts ?? 0) + (tot.announcements ?? 0)} hint="from the Classroom activity log" />
        <Kpi label="Students with missing work" value={data.students_missing_work} tone={data.students_missing_work ? "critical" : undefined} />
      </div>

      <Card className="lg:col-span-3" title="Classes">
        <DataTable rows={data.courses} rowKey={(r: Any) => r.id} columns={[
          {
            header: "Class",
            cell: (r: Any) => (
              <div>
                {r.link ? <a href={r.link} target="_blank" rel="noreferrer" className="font-medium hover:underline">{r.name}</a> : <span className="font-medium">{r.name}</span>}
                {r.section && <div className="text-xs text-ink-3">{r.section}</div>}
              </div>
            ),
          },
          { header: "Status", cell: (r: Any) => <Chip tone={r.state === "ACTIVE" ? "good" : "neutral"}>{titleCase((r.state ?? "").toLowerCase())}</Chip> },
          {
            header: "Teachers",
            cell: (r: Any) => (
              <span className="flex flex-col gap-1">
                {r.teachers.map((t: Any, i: number) => <PersonLink key={i} id={t.id} name={t.name} email={t.email} />)}
              </span>
            ),
          },
          { header: "Students", cell: (r: Any) => r.students, className: "tabular-nums" },
          { header: "Assignments", cell: (r: Any) => r.assignments, className: "tabular-nums" },
          { header: "Posts", cell: (r: Any) => r.posts + r.announcements, className: "tabular-nums", hideOnMobile: true },
          { header: "Missing work", cell: (r: Any) => r.students_missing_work || "—", className: "tabular-nums", hideOnMobile: true },
          { header: "Last activity", cell: (r: Any) => timeAgo(r.last_activity ?? r.updated), hideOnMobile: true },
          { header: "Created", cell: (r: Any) => fmtDate(r.created), hideOnMobile: true },
        ]} />
      </Card>

      <Card className="lg:col-span-2" title="Teachers">
        <DataTable rows={data.teachers} rowKey={(r: Any) => r.email ?? r.name} empty="No teachers yet" columns={[
          { header: "Teacher", cell: (r: Any) => <PersonLink id={r.id} name={r.name} email={r.email} /> },
          { header: "Classes", cell: (r: Any) => r.classes, className: "tabular-nums" },
          { header: "Students", cell: (r: Any) => r.students, className: "tabular-nums" },
          { header: "Assignments", cell: (r: Any) => r.assignments, className: "tabular-nums" },
          { header: "Posts", cell: (r: Any) => r.posts + r.announcements, className: "tabular-nums" },
          { header: "Grading time", cell: (r: Any) => (r.median_grading_hours !== null ? `${r.median_grading_hours} h` : "—"), hideOnMobile: true },
        ]} />
      </Card>

      <Card title="Recent activity" subtitle="Classroom activity log">
        {data.recent_activity.length ? (
          <ul className="space-y-3 text-sm">
            {data.recent_activity.slice(0, 15).map((e: Any, i: number) => (
              <li key={i} className="flex gap-3">
                <span className="w-16 shrink-0 text-xs text-ink-3">{timeAgo(e.time)}</span>
                <span className="min-w-0">
                  <span className="text-ink">{CLASSROOM_EVENT[e.event] ?? titleCase(e.event)}</span>
                  {e.title && <span className="text-ink-2"> “{e.title.trim()}”</span>}
                  <span className="block truncate text-xs text-ink-3">{e.course} · {e.user}</span>
                </span>
              </li>
            ))}
          </ul>
        ) : (
          <Empty title="No Classroom activity yet" />
        )}
      </Card>
    </div>
  );
}

const VIEWS: Record<string, () => JSX.Element> = {
  dlp_events: Dlp,
  context_aware_access: Caa,
  gemini_usage: Gemini,
  gmail_logs: EmailFlow,
  vault: Vault,
  alert_center: AlertCenter,
  chrome_mgmt: Chrome,
  bigquery_logs: BigQuery,
  classroom: Classroom,
};

export default function ModulePage() {
  const params = useParams<{ key: string }>();
  const { caps } = useCapabilities();
  if (!caps) return <PageSkeleton />;
  const feature = caps.features[params.key];
  if (!feature) return <Empty title="Unknown feature" />;
  const View = VIEWS[params.key];
  return (
    <>
      <PageHeader title={feature.title} subtitle={feature.description} action={feature.paid ? <Chip tone="brand">Premium</Chip> : undefined} />
      {/* Locked features always show the locked card on their own page, even with "hide locked" on. */}
      <Feature name={params.key} fallback={<LockedCard feature={feature} />}>
        {View ? <View /> : <Empty title="No view for this feature yet" />}
      </Feature>
    </>
  );
}
