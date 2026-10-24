"use client";

import { TrendChart } from "@/components/charts";
import { Card, Chip, DataTable, Empty, ErrorState, ExportButton, Kpi, PageHeader, PageSkeleton, PersonLink } from "@/components/ui";
import { useApi } from "@/lib/api";
import { fmtDate, fmtMb } from "@/lib/format";

type Row = { id: string; email: string; name: string | null; department: string | null; used_mb: number; total_mb: number | null; drive_mb: number; gmail_mb: number; pct: number | null };
type Data = { total_used_mb: number; top: Row[]; near_quota: Row[]; trend: { date: string; used_gb: number }[] };

const columns = [
  { header: "Person", cell: (r: Row) => <PersonLink id={r.id} name={r.name} email={r.email} /> },
  { header: "Used", cell: (r: Row) => fmtMb(r.used_mb), className: "tabular-nums" },
  {
    header: "Quota",
    cell: (r: Row) => (r.pct !== null ? <Chip tone={r.pct >= 90 ? "critical" : "neutral"}>{r.pct}% of {fmtMb(r.total_mb)}</Chip> : "pooled"),
  },
  { header: "Drive", cell: (r: Row) => fmtMb(r.drive_mb), hideOnMobile: true },
  { header: "Gmail", cell: (r: Row) => fmtMb(r.gmail_mb), hideOnMobile: true },
];

export default function StoragePage() {
  const { data, error, mutate } = useApi<Data>("/insights/storage");
  if (error) return <ErrorState error={error} retry={() => mutate()} />;
  if (!data) return <PageSkeleton />;
  return (
    <>
      <PageHeader title="Storage" subtitle="Usage per person and the organisation trend" action={<ExportButton dataset="storage" />} />
      <div className="mb-4 grid grid-cols-2 gap-3 lg:grid-cols-3">
        <Kpi label="Total used" value={fmtMb(data.total_used_mb)} />
        <Kpi label="Near quota (90%+)" value={data.near_quota.length} tone={data.near_quota.length ? "critical" : "good"} />
      </div>
      <div className="grid gap-4">
        <Card title="Organisation storage" subtitle="Weekly total">
          {data.trend.length ? (
            <TrendChart data={data.trend} x="date" series={[{ key: "used_gb", label: "Used" }]} unit="GB" xFormat={(v) => fmtDate(v).replace(/ \d{4}$/, "")} />
          ) : (
            <Empty title="No storage data yet" />
          )}
        </Card>
        {data.near_quota.length > 0 && (
          <Card title="Near quota">
            <DataTable rows={data.near_quota} rowKey={(r) => r.id} columns={columns} />
          </Card>
        )}
        <Card title="Top users by storage">
          <DataTable rows={data.top} rowKey={(r) => r.id} columns={columns} />
        </Card>
      </div>
    </>
  );
}
