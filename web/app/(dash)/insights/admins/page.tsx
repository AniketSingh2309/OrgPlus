"use client";

import { ShieldAlert, ShieldCheck } from "lucide-react";
import { Card, Chip, DataTable, ErrorState, ExportButton, Kpi, PageHeader, PageSkeleton, PersonLink } from "@/components/ui";
import { RoleList } from "@/components/roles";
import { useApi } from "@/lib/api";
import { timeAgo } from "@/lib/format";

type Data = {
  admins: { id: string; email: string; name: string | null; roles: string[]; super_admin: boolean; last_login: string | null; days_since_login: number | null; twosv: boolean; suspended: boolean }[];
  without_2sv: number;
};

export default function AdminsPage() {
  const { data, error, mutate } = useApi<Data>("/insights/admins");
  if (error) return <ErrorState error={error} retry={() => mutate()} />;
  if (!data) return <PageSkeleton />;
  return (
    <>
      <PageHeader title="Admin role audit" subtitle="Who holds admin rights, when they last signed in, and whether they use 2-Step" action={<ExportButton dataset="admins" />} />
      <div className="mb-4 grid grid-cols-3 gap-3">
        <Kpi label="Admins" value={data.admins.length} />
        <Kpi label="Super admins" value={data.admins.filter((a) => a.super_admin).length} />
        <Kpi label="Admins without 2-Step" value={data.without_2sv} tone={data.without_2sv ? "critical" : "good"} />
      </div>
      <Card>
        <DataTable
          rows={data.admins}
          rowKey={(r) => r.id}
          empty="No admins found"
          columns={[
            { header: "Admin", cell: (r) => <PersonLink id={r.id} name={r.name} email={r.email} /> },
            { header: "Roles", cell: (r) => <RoleList roles={r.roles} /> },
            {
              header: "Last sign-in",
              cell: (r) => <span className={r.days_since_login !== null && r.days_since_login > 30 ? "text-critical" : ""}>{timeAgo(r.last_login)}</span>,
            },
            {
              header: "2-Step",
              cell: (r) =>
                r.twosv ? (
                  <Chip tone="good">
                    <ShieldCheck size={12} aria-hidden /> On
                  </Chip>
                ) : (
                  <Chip tone="critical">
                    <ShieldAlert size={12} aria-hidden /> Off
                  </Chip>
                ),
            },
          ]}
        />
      </Card>
    </>
  );
}
