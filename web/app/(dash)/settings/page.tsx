"use client";

import { Loader2, Mail } from "lucide-react";
import { type FormEvent, useEffect, useState } from "react";
import { AccountsCard } from "@/components/accounts-card";
import { Button, Card, ErrorState, PageHeader, PageSkeleton } from "@/components/ui";
import { send, useApi } from "@/lib/api";

type Settings = {
  licence_price_inr: number;
  licences_purchased: number | null;
  work_start: string;
  work_end: string;
  timezone: string;
  hide_locked: boolean;
  digest_recipients: string[];
};

export default function SettingsPage() {
  // A form: never refresh underneath someone who is typing.
  const { data, error, mutate } = useApi<Settings>("/settings", { refreshInterval: 0, revalidateOnFocus: false });
  const [form, setForm] = useState<Settings | null>(null);
  const [status, setStatus] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  useEffect(() => {
    if (data && !form) setForm(data);
  }, [data, form]);

  if (error) return <ErrorState error={error} retry={() => mutate()} />;
  if (!data || !form) return <PageSkeleton />;

  const save = async (e: FormEvent) => {
    e.preventDefault();
    setBusy("save");
    setStatus(null);
    try {
      mutate(await send<Settings>("/settings", "PUT", form));
      setStatus("Saved.");
    } catch (err) {
      setStatus((err as Error).message);
    } finally {
      setBusy(null);
    }
  };

  const input = "w-full rounded-lg border border-line bg-surface px-3 py-2 text-sm text-ink";
  const label = "mb-1 block text-sm font-medium";

  return (
    <>
      <PageHeader title="Settings" />
      <div className="mb-4">
        <AccountsCard />
      </div>
      <form onSubmit={save} className="grid gap-4 lg:grid-cols-2">
        <Card title="Licences">
          <div className="grid gap-3 sm:grid-cols-2">
            <label>
              <span className={label}>Price per licence (₹ / month)</span>
              <input type="number" min={0} step="1" className={input} value={form.licence_price_inr} onChange={(e) => setForm({ ...form, licence_price_inr: Number(e.target.value) })} />
            </label>
            <label>
              <span className={label}>Licences bought</span>
              <input
                type="number"
                min={0}
                className={input}
                placeholder="defaults to assigned"
                value={form.licences_purchased ?? ""}
                onChange={(e) => setForm({ ...form, licences_purchased: e.target.value === "" ? null : Number(e.target.value) })}
              />
            </label>
          </div>
          <p className="mt-2 text-xs text-ink-3">Google&apos;s Licensing API only reports assignments, so enter the number you pay for to see unassigned seats.</p>
        </Card>
        <Card title="Working hours" subtitle="Used for after-hours and weekend activity">
          <div className="grid gap-3 sm:grid-cols-3">
            <label>
              <span className={label}>Start</span>
              <input type="time" className={input} value={form.work_start} onChange={(e) => setForm({ ...form, work_start: e.target.value })} />
            </label>
            <label>
              <span className={label}>End</span>
              <input type="time" className={input} value={form.work_end} onChange={(e) => setForm({ ...form, work_end: e.target.value })} />
            </label>
            <label>
              <span className={label}>Time zone</span>
              <input className={input} value={form.timezone} onChange={(e) => setForm({ ...form, timezone: e.target.value })} />
            </label>
          </div>
        </Card>
        <Card title="Features">
          <label className="flex items-center gap-3 text-sm">
            <input type="checkbox" className="h-4 w-4 accent-[rgb(var(--brand))]" checked={form.hide_locked} onChange={(e) => setForm({ ...form, hide_locked: e.target.checked })} />
            Hide locked premium features from the menu and pages
          </label>
        </Card>
        <Card title="Weekly digest" subtitle="Sent Monday 08:00 IST: top changes, alerts and licence waste">
          <label>
            <span className={label}>Recipients (comma-separated)</span>
            <input
              className={input}
              value={form.digest_recipients.join(", ")}
              onChange={(e) => setForm({ ...form, digest_recipients: e.target.value.split(",").map((s) => s.trim()).filter(Boolean) })}
              placeholder="head@yourdomain.com"
            />
          </label>
          <div className="mt-3 flex flex-wrap gap-2">
            <a href="/api/digest/preview" target="_blank" rel="noreferrer" className="inline-flex items-center gap-1.5 rounded-lg border border-line px-3 py-1.5 text-sm font-medium hover:bg-surface-2">
              Preview
            </a>
            <Button
              onClick={async () => {
                setBusy("digest");
                try {
                  const r = await send<{ sent: boolean; reason?: string; to?: string[] }>("/digest/send", "POST");
                  setStatus(r.sent ? `Digest sent to ${r.to?.join(", ")}` : `Not sent: ${r.reason}`);
                } catch (err) {
                  setStatus((err as Error).message);
                } finally {
                  setBusy(null);
                }
              }}
              disabled={busy !== null}
            >
              {busy === "digest" ? <Loader2 size={14} className="animate-spin" aria-hidden /> : <Mail size={14} aria-hidden />} Send now
            </Button>
          </div>
        </Card>
        <div className="flex items-center gap-3 lg:col-span-2">
          <Button type="submit" variant="primary" disabled={busy !== null}>
            {busy === "save" && <Loader2 size={14} className="animate-spin" aria-hidden />} Save settings
          </Button>
          {status && <span className="text-sm text-ink-2" role="status">{status}</span>}
        </div>
      </form>
    </>
  );
}
