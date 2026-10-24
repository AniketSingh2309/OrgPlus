"use client";

import clsx from "clsx";
import { ChevronDown, ChevronRight, Search } from "lucide-react";
import { Fragment, useState } from "react";
import { Card, Chip, Empty, ErrorState, ExportButton, Kpi, PageHeader, PageSkeleton, PersonLink } from "@/components/ui";
import { useApi } from "@/lib/api";
import { titleCase } from "@/lib/format";

type Member = { email: string | null; name: string | null; user_id: string | null; role: string; type: string; status: string | null; external: boolean; suspended: boolean };
type Group = {
  id: string;
  email: string;
  name: string | null;
  description: string | null;
  created_by: "admin" | "user";
  members: number;
  owners: number;
  managers: number;
  nested_groups: number;
  external: number;
  external_emails: string[];
  suspended_members: number;
  issues: string[];
  member_list: Member[];
};
type Data = { total: number; groups: Group[]; members_total: number; healthy: number; empty: Group[]; external: Group[]; no_owner: Group[]; suspended_members: Group[]; owner_suspended: Group[] };

const ISSUES: Record<string, { label: string; tone: "critical" | "serious" | "neutral"; help: string }> = {
  external: { label: "External members", tone: "critical", help: "People outside your domain receive this group's email and shared files." },
  no_owner: { label: "No owner", tone: "serious", help: "Nobody can manage membership or settings except admins." },
  owner_suspended: { label: "Owner suspended", tone: "serious", help: "Every owner is suspended, so in practice nobody owns it." },
  suspended_members: { label: "Suspended members", tone: "neutral", help: "Leavers still listed as members." },
  empty: { label: "Empty", tone: "neutral", help: "No members: delete it or fill it." },
};
const FILTERS = ["all", "issues", "external", "no_owner", "owner_suspended", "suspended_members", "empty"] as const;

function MemberTable({ g }: { g: Group }) {
  if (!g.member_list.length) return <p className="px-4 py-4 text-sm text-ink-3">This group has no members.</p>;
  return (
    <div className="max-h-80 overflow-auto bg-surface-2/40 px-4 py-3">
      <table className="w-full min-w-[520px] text-left text-sm">
        <thead>
          <tr className="text-xs uppercase tracking-wide text-ink-3">
            <th className="py-1.5 font-medium">Member</th>
            <th className="py-1.5 font-medium">Role</th>
            <th className="py-1.5 font-medium">Type</th>
            <th className="py-1.5 font-medium" />
          </tr>
        </thead>
        <tbody>
          {g.member_list.map((m, i) => (
            <tr key={`${m.email}-${i}`} className="border-t border-line/60">
              <td className="py-1.5"><PersonLink id={m.user_id} name={m.name} email={m.email} /></td>
              <td className="py-1.5"><Chip tone={m.role === "OWNER" ? "brand" : "neutral"}>{titleCase(m.role.toLowerCase())}</Chip></td>
              <td className="py-1.5 text-ink-2">{titleCase(m.type.toLowerCase())}</td>
              <td className="py-1.5">
                <span className="flex flex-wrap gap-1">
                  {m.external && <Chip tone="critical">External</Chip>}
                  {m.suspended && <Chip>Suspended</Chip>}
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function GroupsPage() {
  const { data, error, mutate } = useApi<Data>("/insights/groups");
  const [open, setOpen] = useState<string | null>(null);
  const [filter, setFilter] = useState<(typeof FILTERS)[number]>("all");
  const [q, setQ] = useState("");
  if (error) return <ErrorState error={error} retry={() => mutate()} />;
  if (!data) return <PageSkeleton />;

  const ql = q.trim().toLowerCase();
  const shown = data.groups.filter(
    (g) =>
      (filter === "all" || (filter === "issues" ? g.issues.length > 0 : g.issues.includes(filter))) &&
      (!ql || g.email.toLowerCase().includes(ql) || (g.name ?? "").toLowerCase().includes(ql)),
  );

  return (
    <>
      <PageHeader title="Groups hygiene" subtitle={`${data.total} groups · ${data.members_total} memberships · ${data.healthy} with no issues`} action={<ExportButton dataset="groups" />} />
      <div className="mb-4 grid grid-cols-2 gap-3 lg:grid-cols-5">
        <Kpi label="External members" value={data.external.length} tone={data.external.length ? "critical" : "good"} hint="groups reaching outside" />
        <Kpi label="No owner" value={data.no_owner.length} tone={data.no_owner.length ? "critical" : "good"} />
        <Kpi label="Owner suspended" value={data.owner_suspended.length} tone={data.owner_suspended.length ? "critical" : "good"} />
        <Kpi label="Suspended members" value={data.suspended_members.length} hint="groups with leavers" />
        <Kpi label="Empty" value={data.empty.length} />
      </div>

      <Card
        title="All groups"
        subtitle="Click a group to see its members"
        bodyClass="p-0"
        action={
          <>
            <label className="relative">
              <Search size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-ink-3" aria-hidden />
              <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search groups" aria-label="Search groups" className="w-44 rounded-lg border border-line bg-surface py-1 pl-8 pr-2 text-sm" />
            </label>
            <select value={filter} onChange={(e) => setFilter(e.target.value as (typeof FILTERS)[number])} className="rounded-lg border border-line bg-surface px-2 py-1 text-sm" aria-label="Filter groups">
              <option value="all">All groups</option>
              <option value="issues">Any issue</option>
              {Object.entries(ISSUES).map(([k, v]) => (
                <option key={k} value={k}>{v.label}</option>
              ))}
            </select>
          </>
        }
      >
        {!shown.length ? (
          <Empty title={data.total ? "No groups match" : "No groups in this domain yet"} />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[860px] text-left text-sm">
              <thead>
                <tr className="border-b border-line text-xs uppercase tracking-wide text-ink-3">
                  <th className="px-4 py-2 font-medium">Group</th>
                  <th className="px-3 py-2 font-medium">Members</th>
                  <th className="px-3 py-2 font-medium">Owners</th>
                  <th className="px-3 py-2 font-medium">Managers</th>
                  <th className="px-3 py-2 font-medium">External</th>
                  <th className="px-3 py-2 font-medium">Created by</th>
                  <th className="px-3 py-2 font-medium">Issues</th>
                </tr>
              </thead>
              <tbody>
                {shown.map((g) => {
                  const isOpen = open === g.id;
                  return (
                    <Fragment key={g.id}>
                      <tr className={clsx("cursor-pointer border-b border-line/60 hover:bg-surface-2/60", isOpen && "bg-surface-2/60")} onClick={() => setOpen(isOpen ? null : g.id)}>
                        <td className="px-4 py-2.5">
                          <button className="flex items-start gap-1.5 text-left" aria-expanded={isOpen}>
                            {isOpen ? <ChevronDown size={14} className="mt-0.5 shrink-0" aria-hidden /> : <ChevronRight size={14} className="mt-0.5 shrink-0" aria-hidden />}
                            <span>
                              <span className="block font-medium text-ink">{g.name ?? g.email}</span>
                              <span className="block text-xs text-ink-3">{g.email}</span>
                              {g.description && <span className="block text-xs text-ink-3">{g.description}</span>}
                            </span>
                          </button>
                        </td>
                        <td className="px-3 py-2.5 tabular-nums">{g.members}{g.nested_groups > 0 && <span className="text-ink-3"> ({g.nested_groups} groups)</span>}</td>
                        <td className="px-3 py-2.5 tabular-nums">{g.owners}</td>
                        <td className="px-3 py-2.5 tabular-nums">{g.managers}</td>
                        <td className="px-3 py-2.5 tabular-nums">{g.external || "—"}</td>
                        <td className="px-3 py-2.5 text-ink-2">{g.created_by === "admin" ? "Admin" : "User"}</td>
                        <td className="px-3 py-2.5">
                          <span className="flex flex-wrap gap-1">
                            {g.issues.length ? g.issues.map((i) => <Chip key={i} tone={ISSUES[i]?.tone ?? "neutral"}><span title={ISSUES[i]?.help}>{ISSUES[i]?.label ?? i}</span></Chip>) : <Chip tone="good">Healthy</Chip>}
                          </span>
                        </td>
                      </tr>
                      {isOpen && (
                        <tr>
                          <td colSpan={7} className="border-b border-line p-0">
                            <MemberTable g={g} />
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </>
  );
}
