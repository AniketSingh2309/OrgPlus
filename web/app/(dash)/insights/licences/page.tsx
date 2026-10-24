"use client";

import Link from "next/link";
import { BarList, Card, Chip, DataTable, ErrorState, ExportButton, Kpi, PageHeader, PageSkeleton, PersonLink } from "@/components/ui";
import { useApi } from "@/lib/api";
import { fmtInr, timeAgo } from "@/lib/format";

type Licences = {
  source: string;
  purchased: number;
  assigned: number;
  active_30d: number;
  unassigned: number;
  idle: number;
  price_inr: number;
  monthly_waste_inr: number;
  by_sku: { sku: string; count: number }[];
  inactive: { id: string | null; email: string; name: string | null; department: string | null; suspended: boolean; last_login: string | null }[];
};

export default function LicencesPage() {
  const { data, error, mutate } = useApi<Licences>("/insights/licences");
  if (error) return <ErrorState error={error} retry={() => mutate()} />;
  if (!data) return <PageSkeleton />;
  return (
    <>
      <PageHeader title="Licence utilisation" subtitle={`Bought vs assigned vs active in the last 30 days · source: ${data.source}`} action={<ExportButton dataset="licences" />} />
      <div className="mb-4 grid grid-cols-2 gap-3 lg:grid-cols-5">
        <Kpi label="Bought" value={data.purchased} hint={<Link href="/settings" className="hover:underline">set in Settings</Link>} />
        <Kpi label="Assigned" value={data.assigned} hint={data.unassigned ? `${data.unassigned} unassigned` : "all assigned"} />
        <Kpi label="Active · 30d" value={data.active_30d} />
        <Kpi label="Idle licences" value={data.idle} tone={data.idle ? "critical" : "good"} />
        <Kpi
          label="Est. monthly waste"
          value={data.price_inr ? fmtInr(data.monthly_waste_inr) : "—"}
          hint={data.price_inr ? `${fmtInr(data.price_inr)} per licence` : <Link href="/settings" className="text-brand hover:underline">Enter licence price</Link>}
        />
      </div>
      <div className="grid gap-4 lg:grid-cols-3">
        <Card title="Licences by SKU">
          <BarList items={data.by_sku.map((s) => ({ key: s.sku, label: s.sku, value: s.count }))} />
        </Card>
        <Card className="lg:col-span-2" title="Licences to reclaim" subtitle="Licensed, but no sign-in or activity in 30 days">
          <DataTable
            rows={data.inactive}
            rowKey={(r) => r.email}
            empty="Every licence is in use"
            columns={[
              { header: "Person", cell: (r) => <PersonLink id={r.id} name={r.name} email={r.email} /> },
              { header: "Department", cell: (r) => r.department ?? "—", hideOnMobile: true },
              { header: "Last sign-in", cell: (r) => timeAgo(r.last_login) },
              { header: "", cell: (r) => (r.suspended ? <Chip tone="serious">Suspended</Chip> : null) },
            ]}
          />
        </Card>
      </div>
    </>
  );
}
