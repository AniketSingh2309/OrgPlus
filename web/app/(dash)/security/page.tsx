"use client";

import { ShieldAlert } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense } from "react";
import { Card, Chip, DataTable, ErrorState, ExportButton, Kpi, PageHeader, PageSkeleton, PersonLink, Tabs } from "@/components/ui";
import { useApi } from "@/lib/api";
import { actorLabel, fmtDate, timeAgo, titleCase } from "@/lib/format";

type Security = {
  twosv: { users: number; enrolled: number; enforced: number; gaps: { id: string; email: string; name: string | null; department: string | null; admin: boolean; last_login: string | null }[] };
  external_shares: { time: string; user: string | null; event: string; title: string | null; type: string | null; visibility: string | null; target: string | null }[];
  signins: { time: string; user: string | null; event: string; ip: string | null; country: string | null; city: string | null; login_type: string | null; suspicious: boolean }[];
  admin_log: { time: string; actor: string; event: string; type: string | null; ip: string | null; target: string | null; setting: string | null; new_value: string | null }[];
};
type Tab = "2sv" | "external" | "signins" | "admin";

function SecurityInner() {
  const params = useSearchParams();
  const router = useRouter();
  const tab = (params.get("tab") as Tab) || "2sv";
  const filter = params.get("filter") ?? "all";
  const { data, error, mutate } = useApi<Security>(`/security?signin_filter=${filter}`, { keepPreviousData: true });
  if (error) return <ErrorState error={error} retry={() => mutate()} />;
  if (!data) return <PageSkeleton />;
  const go = (t: Tab, f = "all") => router.replace(`/security?tab=${t}${f !== "all" ? `&filter=${f}` : ""}`);
  const pct = data.twosv.users ? Math.round((100 * data.twosv.enrolled) / data.twosv.users) : 0;

  return (
    <>
      <PageHeader title="Security" subtitle="2-Step Verification gaps, external sharing, sign-ins and admin changes" />
      <div className="mb-4 grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Kpi label="2-Step enrolled" value={`${pct}%`} hint={`${data.twosv.enrolled} of ${data.twosv.users}`} tone={pct < 90 ? "critical" : "good"} />
        <Kpi label="2-Step enforced" value={data.twosv.enforced} />
        <Kpi label="External shares · 30d" value={data.external_shares.length} />
        <Kpi label="Suspicious sign-ins · 7d" value={data.signins.filter((s) => s.suspicious).length} tone={data.signins.some((s) => s.suspicious) ? "critical" : undefined} />
      </div>
      <Tabs<Tab>
        value={tab}
        onChange={(t) => go(t)}
        tabs={[
          { id: "2sv", label: `2-Step gaps (${data.twosv.gaps.length})` },
          { id: "external", label: "External shares" },
          { id: "signins", label: "Sign-in log" },
          { id: "admin", label: "Admin log" },
        ]}
      />
      {tab === "2sv" && (
        <Card title="People without 2-Step Verification" subtitle="Admins first" action={<ExportButton dataset="2sv-gaps" />}>
          <DataTable
            rows={data.twosv.gaps}
            rowKey={(r) => r.id}
            empty="Everyone has 2-Step Verification"
            columns={[
              { header: "Person", cell: (r) => <PersonLink id={r.id} name={r.name} email={r.email} /> },
              { header: "Department", cell: (r) => r.department ?? "—", hideOnMobile: true },
              { header: "", cell: (r) => r.admin && <Chip tone="critical"><ShieldAlert size={12} aria-hidden /> Admin</Chip> },
              { header: "Last sign-in", cell: (r) => timeAgo(r.last_login) },
            ]}
          />
        </Card>
      )}
      {tab === "external" && (
        <Card title="Files shared outside the domain · 30 days" action={<ExportButton dataset="external-shares" />}>
          <DataTable
            rows={data.external_shares}
            rowKey={(r, i) => `${r.time}-${i}`}
            empty="No external sharing in the last 30 days"
            columns={[
              { header: "When", cell: (r) => <span className="whitespace-nowrap text-ink-2">{fmtDate(r.time, true)}</span> },
              { header: "By", cell: (r) => actorLabel(r.user) },
              { header: "File", cell: (r) => <span className="font-medium">{r.title ?? "Untitled"}</span> },
              { header: "Shared with", cell: (r) => r.target ?? titleCase(r.visibility ?? "—") },
              { header: "Action", cell: (r) => titleCase(r.event), hideOnMobile: true },
            ]}
          />
        </Card>
      )}
      {tab === "signins" && (
        <Card
          title="Sign-ins · 7 days"
          action={
            <>
              <select value={filter} onChange={(e) => go("signins", e.target.value)} className="rounded-lg border border-line bg-surface px-2 py-1 text-sm" aria-label="Filter">
                <option value="all">All</option>
                <option value="failed">Failed</option>
                <option value="suspicious">Suspicious</option>
              </select>
              <ExportButton dataset="signins" />
            </>
          }
        >
          <DataTable
            rows={data.signins}
            rowKey={(r, i) => `${r.time}-${i}`}
            initial={50}
            empty="No sign-ins match"
            columns={[
              { header: "When", cell: (r) => <span className="whitespace-nowrap text-ink-2">{fmtDate(r.time, true)}</span> },
              { header: "User", cell: (r) => actorLabel(r.user) },
              {
                header: "Result",
                cell: (r) =>
                  r.suspicious ? <Chip tone="critical"><ShieldAlert size={12} aria-hidden /> Suspicious</Chip> : r.event === "login_failure" ? <Chip tone="serious">Failed</Chip> : <span className="text-ink-2">{titleCase(r.event)}</span>,
              },
              { header: "Location", cell: (r) => [r.city, r.country].filter(Boolean).join(", ") || "—" },
              { header: "IP", cell: (r) => <span className="font-mono text-xs">{r.ip ?? "—"}</span>, hideOnMobile: true },
            ]}
          />
        </Card>
      )}
      {tab === "admin" && (
        <Card title="Admin console changes · 30 days" action={<ExportButton dataset="admin-log" />}>
          <DataTable
            rows={data.admin_log}
            rowKey={(r, i) => `${r.time}-${i}`}
            empty="No admin changes in the last 30 days"
            columns={[
              { header: "When", cell: (r) => <span className="whitespace-nowrap text-ink-2">{fmtDate(r.time, true)}</span> },
              { header: "Admin", cell: (r) => r.actor },
              { header: "Action", cell: (r) => titleCase(r.event.toLowerCase()) },
              { header: "Target", cell: (r) => r.target ?? r.setting ?? "—" },
              { header: "New value", cell: (r) => r.new_value ?? "—", hideOnMobile: true },
            ]}
          />
        </Card>
      )}
    </>
  );
}

export default function SecurityPage() {
  return (
    <Suspense fallback={<PageSkeleton />}>
      <SecurityInner />
    </Suspense>
  );
}
