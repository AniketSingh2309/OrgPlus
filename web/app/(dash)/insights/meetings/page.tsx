"use client";

import { Bars } from "@/components/charts";
import { BarList, Card, DataTable, ErrorState, ExportButton, PageHeader, PageSkeleton, PersonLink } from "@/components/ui";
import { useApi } from "@/lib/api";

type Data = {
  people: { id: string | null; email: string; name: string | null; department: string; hours_per_week: number; calls: number; heavy_days: number }[];
  teams: { department: string; avg_hours_per_week: number; people: number }[];
  by_weekday: { day: string; hours: number }[];
  heavy_day_threshold_hours: number;
};

export default function MeetingsPage() {
  const { data, error, mutate } = useApi<Data>("/insights/meetings");
  if (error) return <ErrorState error={error} retry={() => mutate()} />;
  if (!data) return <PageSkeleton />;
  return (
    <>
      <PageHeader title="Meeting load" subtitle="Hours in Google Meet over the last 8 weeks" action={<ExportButton dataset="meetings" />} />
      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Team averages" subtitle="Hours per person per week">
          <BarList items={data.teams.map((t) => ({ key: t.department, label: `${t.department} (${t.people})`, value: t.avg_hours_per_week }))} format={(v) => `${v} h`} />
        </Card>
        <Card title="Meeting-heavy weekdays" subtitle="Org-wide hours per weekday, weekly average">
          <Bars data={data.by_weekday} x="day" y="hours" label="Hours" unit="h" />
        </Card>
        <Card className="lg:col-span-2" title="Per person" subtitle={`Heavy day = ${data.heavy_day_threshold_hours}+ hours of calls`}>
          <DataTable
            rows={data.people}
            rowKey={(r) => r.email}
            empty="No Meet calls recorded"
            columns={[
              { header: "Person", cell: (r) => <PersonLink id={r.id} name={r.name} email={r.email} sub={r.department} /> },
              { header: "Hours / week", cell: (r) => r.hours_per_week, className: "tabular-nums" },
              { header: "Calls", cell: (r) => r.calls, className: "tabular-nums" },
              { header: "Heavy days", cell: (r) => r.heavy_days, className: "tabular-nums" },
            ]}
          />
        </Card>
      </div>
    </>
  );
}
