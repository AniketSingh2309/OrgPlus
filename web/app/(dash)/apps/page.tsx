"use client";

import { useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { TrendChart } from "@/components/charts";
import { BarList, Card, Chip, DataTable, ErrorState, ExportButton, Kpi, PageHeader, PageSkeleton, RiskChip } from "@/components/ui";
import { useApi } from "@/lib/api";
import { fmtDate, timeAgo } from "@/lib/format";

type ThirdParty = {
  client_id: string;
  name: string;
  users: number;
  emails: string[];
  scopes: string[];
  risk: "high" | "medium" | "low";
  risk_score: number;
  unverified: boolean;
  native: boolean;
  last_used: string | null;
  unused_90d: boolean;
};
type AppsData = {
  google_apps: { app: string; users: number; pct: number }[];
  adoption_trend: ({ week: string } & Record<string, number | string>)[];
  sso_apps: { app: string; users: number; signins: number; failures: number; last: string | null }[];
  third_party: ThirdParty[];
  risk_counts: Record<string, number>;
};

const APPS = [
  { key: "drive", label: "Drive" },
  { key: "gmail", label: "Gmail" },
  { key: "meet", label: "Meet" },
  { key: "chat", label: "Chat" },
  { key: "calendar", label: "Calendar" },
];
const short = (s: string) => s.replace("https://www.googleapis.com/auth/", "");

function AppsInner() {
  const params = useSearchParams();
  const [risk, setRisk] = useState(params.get("risk") ?? "");
  const { data, error, mutate } = useApi<AppsData>("/apps");
  if (error) return <ErrorState error={error} retry={() => mutate()} />;
  if (!data) return <PageSkeleton />;
  const shown = data.third_party.filter((a) => !risk || a.risk === risk || (risk === "unused" && a.unused_90d));

  return (
    <>
      <PageHeader title="Apps" subtitle="Google app adoption, SSO apps and third-party apps with access to your data" action={<ExportButton dataset="apps" />} />
      <div className="mb-4 grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Kpi label="Third-party apps" value={data.third_party.length} />
        <Kpi label="High risk" value={data.risk_counts.high ?? 0} tone={(data.risk_counts.high ?? 0) > 0 ? "critical" : "good"} hint="full Drive/Gmail access or unverified" />
        <Kpi label="Medium risk" value={data.risk_counts.medium ?? 0} />
        <Kpi label="Unused 90+ days" value={data.third_party.filter((a) => a.unused_90d).length} hint="still holding access" />
      </div>
      <div className="grid gap-4 xl:grid-cols-3">
        <Card title="Google apps" subtitle="Share of active people, last 30 days">
          <BarList items={data.google_apps.map((a) => ({ key: a.app, label: APPS.find((x) => x.key === a.app)?.label ?? a.app, value: a.pct, hint: `${a.users} people` }))} format={(v) => `${v}%`} max={100} />
        </Card>
        <Card className="xl:col-span-2" title="Weekly active people per app" subtitle="Last 6 months">
          <TrendChart data={data.adoption_trend} x="week" series={APPS} unit="people" xFormat={(v) => fmtDate(v).replace(/ \d{4}$/, "")} height={240} />
        </Card>
        <Card
          className="xl:col-span-3"
          title="Third-party apps"
          subtitle="Grouped by OAuth client. Risk: full Drive or Gmail access, or unverified = high; full Calendar or Drive read-only = medium."
          action={
            <select value={risk} onChange={(e) => setRisk(e.target.value)} className="rounded-lg border border-line bg-surface px-2 py-1 text-sm" aria-label="Filter by risk">
              <option value="">All risks</option>
              <option value="high">High</option>
              <option value="medium">Medium</option>
              <option value="low">Low</option>
              <option value="unused">Unused 90d+</option>
            </select>
          }
        >
          <DataTable
            rows={shown}
            rowKey={(r) => r.client_id}
            empty="No third-party apps match"
            columns={[
              {
                header: "App",
                cell: (r) => (
                  <div>
                    <div className="font-medium">{r.name}</div>
                    <div className="flex flex-wrap gap-1 pt-1">
                      {r.unverified && <Chip tone="critical">Unverified</Chip>}
                      {r.unused_90d && <Chip>Unused 90d+</Chip>}
                    </div>
                  </div>
                ),
              },
              { header: "Risk", cell: (r) => <RiskChip risk={r.risk} /> },
              { header: "Score", cell: (r) => r.risk_score, className: "tabular-nums", hideOnMobile: true },
              { header: "Users", cell: (r) => <span title={r.emails.join("\n")}>{r.users}</span>, className: "tabular-nums" },
              { header: "Access", cell: (r) => <span className="text-xs text-ink-2">{r.scopes.map(short).join(", ")}</span>, hideOnMobile: true },
              { header: "Last used", cell: (r) => timeAgo(r.last_used) },
            ]}
          />
        </Card>
        <Card className="xl:col-span-3" title="SSO apps" subtitle="SAML sign-ins, last 30 days">
          <DataTable
            rows={data.sso_apps}
            rowKey={(r) => r.app}
            empty="No SAML apps in use"
            columns={[
              { header: "App", cell: (r) => <span className="font-medium">{r.app}</span> },
              { header: "People", cell: (r) => r.users, className: "tabular-nums" },
              { header: "Sign-ins", cell: (r) => r.signins, className: "tabular-nums" },
              { header: "Failures", cell: (r) => (r.failures ? <Chip tone="serious">{r.failures}</Chip> : 0) },
              { header: "Last", cell: (r) => timeAgo(r.last) },
            ]}
          />
        </Card>
      </div>
    </>
  );
}

export default function AppsPage() {
  return (
    <Suspense fallback={<PageSkeleton />}>
      <AppsInner />
    </Suspense>
  );
}
