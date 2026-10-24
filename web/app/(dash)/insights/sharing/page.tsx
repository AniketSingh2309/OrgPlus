"use client";

import { BarList, Card, Chip, DataTable, ErrorState, ExportButton, Kpi, PageHeader, PageSkeleton } from "@/components/ui";
import { useApi } from "@/lib/api";
import { actorLabel, fmtDate, titleCase } from "@/lib/format";

type External = {
  files: number;
  people: number;
  public_links: number;
  top_domains: { domain: string; files: number; people: number }[];
  public: { doc_id: string; title: string | null; type: string | null; visibility: string; user: string | null; time: string }[];
  top_sharers: { user: string; files: number }[];
};
type Drives = { drives: { id: string; name: string; created: string | null; members: number | null; external_members: number | null; organizers: string[] }[] };

export default function SharingPage() {
  const ext = useApi<External>("/insights/external");
  const drives = useApi<Drives>("/insights/shared-drives");
  if (ext.error) return <ErrorState error={ext.error} retry={() => ext.mutate()} />;
  if (!ext.data) return <PageSkeleton />;
  const d = ext.data;
  return (
    <>
      <PageHeader title="External collaboration" subtitle="Files shared outside the domain, public links and shared drives, last 30 days" action={<ExportButton dataset="external-shares" />} />
      <div className="mb-4 grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Kpi label="Files shared externally" value={d.files} />
        <Kpi label="People sharing" value={d.people} />
        <Kpi label="Public / anyone-with-link" value={d.public_links} tone={d.public_links ? "critical" : "good"} />
        <Kpi label="Shared drives with outsiders" value={drives.data?.drives.filter((x) => (x.external_members ?? 0) > 0).length ?? "—"} />
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Top external domains">
          <BarList items={d.top_domains.map((x) => ({ key: x.domain, label: x.domain, value: x.files, hint: `${x.people} people sharing` }))} format={(v) => `${v} files`} />
        </Card>
        <Card title="Who shares most">
          <BarList items={d.top_sharers.map((x) => ({ key: x.user, label: x.user, value: x.files }))} format={(v) => `${v} files`} />
        </Card>
        <Card className="lg:col-span-2" title="Public and anyone-with-the-link files">
          <DataTable
            rows={d.public}
            rowKey={(r) => r.doc_id}
            empty="No public links"
            columns={[
              { header: "File", cell: (r) => <span className="font-medium">{r.title ?? "Untitled"}</span> },
              { header: "Visibility", cell: (r) => <Chip tone="critical">{titleCase(r.visibility)}</Chip> },
              { header: "Owner / sharer", cell: (r) => actorLabel(r.user) },
              { header: "When", cell: (r) => fmtDate(r.time, true), hideOnMobile: true },
            ]}
          />
        </Card>
        <Card className="lg:col-span-2" title="Shared drives" subtitle="Metadata only (names and members)" action={<ExportButton dataset="shared-drives" />}>
          <DataTable
            rows={drives.data?.drives ?? []}
            rowKey={(r) => r.id}
            empty={drives.data ? "No shared drives, or drive.readonly isn't granted" : "Loading…"}
            columns={[
              { header: "Drive", cell: (r) => <span className="font-medium">{r.name}</span> },
              { header: "Members", cell: (r) => r.members ?? "—", className: "tabular-nums" },
              { header: "External", cell: (r) => ((r.external_members ?? 0) > 0 ? <Chip tone="serious">{r.external_members}</Chip> : 0) },
              { header: "Organisers", cell: (r) => r.organizers.join(", ") || "—", hideOnMobile: true },
            ]}
          />
        </Card>
      </div>
    </>
  );
}
