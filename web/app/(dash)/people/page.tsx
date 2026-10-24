"use client";

import { Search, ShieldAlert } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { Card, Chip, DataTable, ErrorState, ExportButton, PageHeader, PageSkeleton, PersonLink, Sparkline } from "@/components/ui";
import { RoleList } from "@/components/roles";
import { useApi } from "@/lib/api";
import { fmtNum, timeAgo } from "@/lib/format";

type Row = {
  id: string;
  name: string;
  email: string;
  department: string | null;
  title: string | null;
  org_unit: string | null;
  last_login: string | null;
  status: "active" | "inactive" | "suspended";
  twosv: boolean;
  roles: string[];
  score: number;
  active_days: number;
  spark: number[];
};

const STATUSES = [
  ["", "Everyone"],
  ["active", "Active"],
  ["inactive", "No sign-in 30d+"],
  ["suspended", "Suspended"],
  ["no2sv", "No 2-Step"],
  ["admin", "Admins"],
] as const;

function StatusChip({ s }: { s: Row["status"] }) {
  if (s === "active") return <Chip tone="good">Active</Chip>;
  if (s === "inactive") return <Chip tone="warning">Inactive</Chip>;
  return <Chip>Suspended</Chip>;
}

function PeopleInner() {
  const params = useSearchParams();
  const router = useRouter();
  const [q, setQ] = useState(params.get("q") ?? "");
  const dept = params.get("dept") ?? "";
  const status = params.get("status") ?? "";
  const sort = params.get("sort") ?? "score";
  const [debounced, setDebounced] = useState(q);
  useEffect(() => {
    const t = setTimeout(() => setDebounced(q), 250);
    return () => clearTimeout(t);
  }, [q]);

  const setParam = (k: string, v: string) => {
    const next = new URLSearchParams(params.toString());
    if (v) next.set(k, v);
    else next.delete(k);
    router.replace(`/people?${next.toString()}`);
  };

  const qs = new URLSearchParams({ q: debounced, dept, status, sort });
  const { data, error, mutate, isLoading } = useApi<{ people: Row[]; departments: string[]; total: number }>(`/people?${qs}`, {
    keepPreviousData: true,
  });

  if (error) return <ErrorState error={error} retry={() => mutate()} />;
  if (!data) return <PageSkeleton />;

  const select = "rounded-lg border border-line bg-surface px-3 py-1.5 text-sm text-ink";
  return (
    <>
      <PageHeader title="People" subtitle={`${data.people.length} of ${data.total} people`} action={<ExportButton dataset="people" />} />
      <Card bodyClass="p-0">
        <div className="no-print flex flex-wrap gap-2 border-b border-line p-3">
          <label className="relative min-w-[200px] flex-1">
            <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-ink-3" aria-hidden />
            <input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Search name, email or title"
              className="w-full rounded-lg border border-line bg-surface py-1.5 pl-8 pr-3 text-sm text-ink placeholder:text-ink-3"
              aria-label="Search people"
            />
          </label>
          <select className={select} value={dept} onChange={(e) => setParam("dept", e.target.value)} aria-label="Department">
            <option value="">All departments</option>
            {data.departments.map((d) => (
              <option key={d}>{d}</option>
            ))}
          </select>
          <select className={select} value={status} onChange={(e) => setParam("status", e.target.value)} aria-label="Status">
            {STATUSES.map(([v, l]) => (
              <option key={v} value={v}>
                {l}
              </option>
            ))}
          </select>
          <select className={select} value={sort} onChange={(e) => setParam("sort", e.target.value)} aria-label="Sort">
            <option value="score">Sort: activity</option>
            <option value="name">Sort: name</option>
            <option value="last_login">Sort: last sign-in</option>
            <option value="department">Sort: department</option>
          </select>
        </div>
        <div className={isLoading ? "p-4 opacity-60" : "p-4"}>
          <DataTable
            rows={data.people}
            rowKey={(r) => r.id}
            initial={50}
            empty="No one matches these filters"
            columns={[
              { header: "Person", cell: (r) => <PersonLink id={r.id} name={r.name} email={r.email} sub={r.title ?? r.email} /> },
              { header: "Department", cell: (r) => r.department ?? "—", hideOnMobile: true },
              { header: "Last sign-in", cell: (r) => <span className="whitespace-nowrap text-ink-2">{timeAgo(r.last_login)}</span> },
              { header: "Status", cell: (r) => <StatusChip s={r.status} /> },
              {
                header: "Security",
                hideOnMobile: true,
                cell: (r) => (
                  <span className="flex flex-wrap gap-1">
                    {!r.twosv && r.status !== "suspended" && (
                      <Chip tone="critical">
                        <ShieldAlert size={12} aria-hidden /> No 2SV
                      </Chip>
                    )}
                    <RoleList roles={r.roles} />
                  </span>
                ),
              },
              { header: "12 weeks", cell: (r) => <Sparkline values={r.spark} />, hideOnMobile: true },
              { header: "Score · 30d", cell: (r) => <span className="font-medium tabular-nums">{fmtNum(r.score)}</span>, className: "text-right" },
            ]}
          />
        </div>
      </Card>
    </>
  );
}

export default function PeoplePage() {
  return (
    <Suspense fallback={<PageSkeleton />}>
      <PeopleInner />
    </Suspense>
  );
}
