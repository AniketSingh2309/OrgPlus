"use client";

import { CheckCircle2, ExternalLink, Loader2 } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { LockedCard } from "@/components/feature";
import { Button, Card, Chip, DataTable, ErrorState, PageHeader, PageSkeleton } from "@/components/ui";
import { send, useApi } from "@/lib/api";
import { fmtDate } from "@/lib/format";
import type { Capabilities } from "@/lib/types";

const FREE = [
  "Directory, groups, org units, admin roles, devices",
  "Daily usage and the 6-month activity grid",
  "Sign-ins, Drive, Meet, Calendar, Chat and admin events",
  "Licence waste, joiners & leavers, storage, meeting load",
  "After-hours by team, external sharing, shared drives",
  "Groups hygiene, admin audit, sign-in map, risky apps",
  "Team comparison, weekly digest, CSV / PDF exports, manager view",
];

export default function PlanPage() {
  const { data, error, mutate } = useApi<Capabilities>("/capabilities");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  if (error) return <ErrorState error={error} retry={() => mutate()} />;
  if (!data) return <PageSkeleton />;
  const features = Object.entries(data.features);

  return (
    <>
      <PageHeader
        title="Plan & features"
        subtitle={data.detected_at ? `Detected ${fmtDate(data.detected_at, true)}` : "Not detected yet"}
        action={
          <Button
            onClick={async () => {
              setBusy(true);
              setErr(null);
              try {
                mutate(await send<Capabilities>("/capabilities/recheck", "POST"));
              } catch (e) {
                setErr((e as Error).message);
              } finally {
                setBusy(false);
              }
            }}
            disabled={busy}
          >
            {busy && <Loader2 size={14} className="animate-spin" aria-hidden />} Re-check plan
          </Button>
        }
      />
      {err && <p className="mb-4 text-sm text-critical">{err}</p>}
      <div className="grid gap-4 lg:grid-cols-3">
        <Card title="Edition">
          <div className="text-xl font-semibold">{data.edition}</div>
          <Chip tone="brand" className="mt-1">{data.badge}</Chip>
          {data.licensing_error && <p className="mt-2 text-xs text-ink-3">Licensing API: {data.licensing_error}. Features are still detected by probing.</p>}
        </Card>
        <Card className="lg:col-span-2" title="Licences by SKU" subtitle="Mixed-licence domains show every SKU">
          <DataTable
            rows={Object.entries(data.sku_breakdown)}
            rowKey={([sku]) => sku}
            empty="No licence data"
            columns={[
              { header: "SKU", cell: ([sku]) => <code className="font-mono text-xs">{sku}</code> },
              { header: "Edition", cell: ([, s]) => <span>{s.edition}{!s.known && <Chip className="ml-2">unmapped</Chip>}</span> },
              { header: "Tier", cell: ([, s]) => s.tier },
              { header: "Licences", cell: ([, s]) => s.count, className: "tabular-nums" },
            ]}
          />
        </Card>
        <Card className="lg:col-span-3" title="Included with every edition">
          <ul className="grid gap-2 text-sm sm:grid-cols-2">
            {FREE.map((f) => (
              <li key={f} className="flex items-start gap-2">
                <CheckCircle2 size={16} className="mt-0.5 shrink-0 text-good" aria-hidden /> {f}
              </li>
            ))}
          </ul>
        </Card>
      </div>
      <h2 className="mb-3 mt-6 text-sm font-semibold uppercase tracking-wide text-ink-3">Premium features</h2>
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
        {features.map(([key, f]) =>
          f.enabled ? (
            <section key={key} className="rounded-card border border-line bg-surface p-4">
              <div className="flex items-center gap-2">
                <CheckCircle2 size={16} className="text-good" aria-hidden />
                <h3 className="text-sm font-semibold">{f.title}</h3>
                <Chip tone="good" className="ml-auto">On</Chip>
              </div>
              <p className="mt-1 text-sm text-ink-2">{f.description}</p>
              <Link href={f.page} className="mt-2 inline-flex items-center gap-1 text-sm font-medium text-brand hover:underline">
                Open <ExternalLink size={12} aria-hidden />
              </Link>
            </section>
          ) : (
            <LockedCard key={key} feature={f} />
          ),
        )}
      </div>
    </>
  );
}
