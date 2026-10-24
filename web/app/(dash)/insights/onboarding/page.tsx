"use client";

import { Card, Chip, DataTable, ErrorState, ExportButton, PageHeader, PageSkeleton, PersonLink } from "@/components/ui";
import { useApi } from "@/lib/api";
import { fmtDate, fmtMb, fmtNum, timeAgo } from "@/lib/format";

type Data = {
  joiners: {
    id: string;
    email: string;
    name: string | null;
    department: string | null;
    title: string | null;
    created: string;
    first_login: string | null;
    manager: string | null;
    first_week_score: number;
    first_week_active_days: number;
    this_month: boolean;
  }[];
  leavers: { id: string; email: string; name: string | null; department: string | null; reason: string | null; last_login: string | null; licensed: boolean; drive_mb: number | null; owns_files: boolean }[];
};

export default function OnboardingPage() {
  const { data, error, mutate } = useApi<Data>("/insights/onboarding");
  if (error) return <ErrorState error={error} retry={() => mutate()} />;
  if (!data) return <PageSkeleton />;
  return (
    <>
      <PageHeader title="Joiners & leavers" subtitle="New joiners' first week, and suspended accounts still holding licences or files" />
      <div className="grid gap-4">
        <Card title="New joiners" subtitle="Accounts created this month and last" action={<ExportButton dataset="onboarding" />}>
          <DataTable
            rows={data.joiners}
            rowKey={(r) => r.id}
            empty="No new joiners recently"
            columns={[
              { header: "Person", cell: (r) => <PersonLink id={r.id} name={r.name} email={r.email} sub={r.title ?? r.department ?? r.email} /> },
              {
                header: "Joined",
                cell: (r) => (
                  <span className="flex flex-wrap gap-1">
                    {fmtDate(r.created)} {r.this_month && <Chip tone="brand">This month</Chip>}
                  </span>
                ),
              },
              { header: "First sign-in", cell: (r) => (r.first_login ? fmtDate(r.first_login, true) : <Chip tone="serious">Not yet</Chip>) },
              { header: "First week", cell: (r) => `${r.first_week_active_days} active days · score ${fmtNum(r.first_week_score)}` },
              { header: "Manager", cell: (r) => r.manager ?? "—", hideOnMobile: true },
            ]}
          />
        </Card>
        <Card title="Leavers (suspended accounts)" subtitle="Transfer their Drive files before deleting, and remove the licence to stop paying" action={<ExportButton dataset="offboarding" />}>
          <DataTable
            rows={data.leavers}
            rowKey={(r) => r.id}
            empty="No suspended accounts"
            columns={[
              { header: "Person", cell: (r) => <PersonLink id={r.id} name={r.name} email={r.email} /> },
              { header: "Last sign-in", cell: (r) => timeAgo(r.last_login) },
              { header: "Licence", cell: (r) => (r.licensed ? <Chip tone="critical">Still licensed</Chip> : <Chip tone="good">Removed</Chip>) },
              { header: "Drive data", cell: (r) => (r.owns_files ? <Chip tone="serious">{fmtMb(r.drive_mb)} to transfer</Chip> : "—") },
              { header: "Reason", cell: (r) => r.reason ?? "—", hideOnMobile: true },
            ]}
          />
        </Card>
      </div>
    </>
  );
}
