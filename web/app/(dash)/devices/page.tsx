"use client";

import { AlertOctagon } from "lucide-react";
import { useState } from "react";
import { BarList, Card, Chip, DataTable, ErrorState, ExportButton, Kpi, PageHeader, PageSkeleton, PersonLink } from "@/components/ui";
import { useApi } from "@/lib/api";
import { timeAgo, titleCase } from "@/lib/format";

type Device = {
  kind: string;
  id: string;
  user_email: string | null;
  user_id: string | null;
  user_name: string | null;
  model: string | null;
  os: string | null;
  status: string | null;
  type: string | null;
  serial: string | null;
  last_sync: string | null;
  stale: boolean;
  compromised: boolean;
  encryption: string | null;
};
type Devices = { devices: Device[]; by_type: Record<string, number>; by_status: Record<string, number>; by_os: Record<string, number>; stale: number; compromised: number };

export default function DevicesPage() {
  const { data, error, mutate } = useApi<Devices>("/devices");
  const [kind, setKind] = useState("");
  if (error) return <ErrorState error={error} retry={() => mutate()} />;
  if (!data) return <PageSkeleton />;
  const rows = data.devices.filter((d) => !kind || d.kind === kind || (kind === "stale" && d.stale) || (kind === "compromised" && d.compromised));
  const list = (o: Record<string, number>) => Object.entries(o).map(([k, v]) => ({ key: k, label: titleCase(k.toLowerCase()), value: v }));

  return (
    <>
      <PageHeader title="Devices" subtitle="Managed mobile devices and Chromebooks" action={<ExportButton dataset="devices" />} />
      <div className="mb-4 grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Kpi label="Devices" value={data.devices.length} />
        <Kpi label="Mobile" value={data.devices.filter((d) => d.kind === "mobile").length} />
        <Kpi label="No sync 30d+" value={data.stale} hint="lost, replaced or unused" />
        <Kpi label="Compromised" value={data.compromised} tone={data.compromised ? "critical" : "good"} hint={data.compromised ? "rooted / jailbroken" : "none detected"} />
      </div>
      <div className="grid gap-4 lg:grid-cols-3">
        <Card title="By type"><BarList items={list(data.by_type)} /></Card>
        <Card title="By OS"><BarList items={list(data.by_os).slice(0, 8)} /></Card>
        <Card title="By status"><BarList items={list(data.by_status)} /></Card>
        <Card
          className="lg:col-span-3"
          title="All devices"
          action={
            <select value={kind} onChange={(e) => setKind(e.target.value)} className="rounded-lg border border-line bg-surface px-2 py-1 text-sm" aria-label="Filter devices">
              <option value="">All</option>
              <option value="mobile">Mobile</option>
              <option value="chromeos">Chromebooks</option>
              <option value="stale">No sync 30d+</option>
              <option value="compromised">Compromised</option>
            </select>
          }
        >
          <DataTable
            rows={rows}
            rowKey={(r) => `${r.kind}-${r.id}`}
            initial={50}
            empty="No devices match"
            columns={[
              { header: "Device", cell: (r) => <span className="font-medium">{r.model ?? "Unknown"}</span> },
              { header: "Owner", cell: (r) => (r.user_email ? <PersonLink id={r.user_id} name={r.user_name} email={r.user_email} /> : "—") },
              { header: "OS", cell: (r) => r.os ?? "—", hideOnMobile: true },
              {
                header: "Status",
                cell: (r) => (
                  <span className="flex flex-wrap gap-1">
                    <Chip tone={r.status === "APPROVED" || r.status === "ACTIVE" ? "good" : "neutral"}>{titleCase((r.status ?? "unknown").toLowerCase())}</Chip>
                    {r.compromised && <Chip tone="critical"><AlertOctagon size={12} aria-hidden /> Compromised</Chip>}
                  </span>
                ),
              },
              { header: "Last sync", cell: (r) => <span className={r.stale ? "text-critical" : "text-ink-2"}>{timeAgo(r.last_sync)}</span> },
              { header: "Serial", cell: (r) => <span className="font-mono text-xs">{r.serial ?? "—"}</span>, hideOnMobile: true },
            ]}
          />
        </Card>
      </div>
    </>
  );
}
