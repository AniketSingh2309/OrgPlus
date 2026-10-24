"use client";

import clsx from "clsx";
import { CheckCircle2, Copy, Loader2, Lock, Upload, XCircle } from "lucide-react";
import { type FormEvent, useState } from "react";
import { Button, Card, Chip, ErrorState, PageHeader, PageSkeleton } from "@/components/ui";
import { isLive, send, useApi } from "@/lib/api";
import { fmtDate, timeAgo } from "@/lib/format";
import type { Capabilities } from "@/lib/types";

type ScopeRow = { scope: string; purpose: string; required: boolean; granted: boolean; error: string | null };
type ScopeCheck = { diagnosis?: string | null; client_id: string; client_email: string; scopes: ScopeRow[]; core_ok: boolean; missing_csv: string };
type Connection = {
  connected: boolean;
  source: "env" | "uploaded" | null;
  client_email?: string;
  client_id?: string;
  admin_email?: string;
  bigquery_project?: string | null;
  bigquery_dataset?: string | null;
  scope_check?: ScopeCheck | null;
  updated_at?: string | null;
};
type SyncStatus = {
  running: string[];
  derived_metrics?: string[];
  jobs: { key: string; status: string | null; last_success: string | null; error: string | null; progress: { done: number; total: number } | null; missing_metrics: Record<string, string[]> | null }[];
};

function Step({ n, title, done, children }: { n: number; title: string; done?: boolean; children: React.ReactNode }) {
  return (
    <Card
      title={
        <span className="flex items-center gap-2">
          <span className={clsx("inline-flex h-6 w-6 items-center justify-center rounded-full text-xs font-semibold", done ? "bg-good text-white" : "bg-brand-soft text-brand-strong")}>
            {done ? "✓" : n}
          </span>
          {title}
        </span>
      }
    >
      {children}
    </Card>
  );
}

function CopyButton({ text, label = "Copy" }: { text: string; label?: string }) {
  const [ok, setOk] = useState(false);
  return (
    <Button
      variant="ghost"
      onClick={() => {
        navigator.clipboard.writeText(text).then(() => {
          setOk(true);
          setTimeout(() => setOk(false), 1500);
        });
      }}
    >
      <Copy size={14} aria-hidden /> {ok ? "Copied" : label}
    </Button>
  );
}

function ScopeChecklist({ check }: { check: ScopeCheck }) {
  const missing = check.scopes.filter((s) => !s.granted);
  return (
    <div>
      {check.diagnosis && (
        <p role="alert" className="mb-3 rounded-lg border border-critical/30 bg-critical/5 p-3 text-sm text-ink">
          {check.diagnosis}
        </p>
      )}
      <div className="mb-3 flex flex-wrap items-center gap-2 text-sm">
        <span className="text-ink-2">Client ID for domain-wide delegation:</span>
        <code className="rounded bg-surface-2 px-2 py-0.5 font-mono text-xs">{check.client_id}</code>
        <CopyButton text={check.client_id} />
      </div>
      <ul className="divide-y divide-line rounded-lg border border-line">
        {check.scopes.map((s) => (
          <li key={s.scope} className="flex items-start gap-3 px-3 py-2 text-sm">
            {s.granted ? <CheckCircle2 size={16} className="mt-0.5 shrink-0 text-good" aria-label="granted" /> : <XCircle size={16} className={clsx("mt-0.5 shrink-0", s.required ? "text-critical" : "text-ink-3")} aria-label="missing" />}
            <div className="min-w-0 flex-1">
              <code className="break-all font-mono text-xs text-ink">{s.scope}</code>
              <div className="text-xs text-ink-3">
                {s.purpose}
                {!s.required && " · optional"}
                {s.error && !s.granted && <span className="block text-ink-2">{s.error}</span>}
              </div>
            </div>
          </li>
        ))}
      </ul>
      {missing.length > 0 && (
        <div className="mt-3 rounded-lg bg-surface-2 p-3 text-sm">
          <p className="mb-2 text-ink-2">
            Add these in Admin console → Security → API controls → Domain-wide delegation → edit the client ID above (comma-separated):
          </p>
          <div className="flex items-start gap-2">
            <code className="block flex-1 break-all font-mono text-xs">{check.missing_csv}</code>
            <CopyButton text={check.missing_csv} />
          </div>
        </div>
      )}
    </div>
  );
}

export default function ConnectPage() {
  const conn = useApi<Connection>("/connect");
  const caps = useApi<Capabilities>("/capabilities");
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [check, setCheck] = useState<ScopeCheck | null>(null);
  const [, setBackfillStarted] = useState(false);
  // Pushed live over Socket.IO; polling (2 s while running) only while the socket is down.
  const sync = useApi<SyncStatus>("/sync/status", {
    refreshInterval: (d) => (isLive() ? 60_000 : d?.running.length ? 2_000 : 10_000),
  });

  if (conn.error) return <ErrorState error={conn.error} retry={() => conn.mutate()} />;
  if (!conn.data) return <PageSkeleton />;
  const scopeCheck = check ?? conn.data.scope_check ?? null;
  // An env-file credential has no stored check; let the server decide.
  const coreOk = conn.data.source === "env" || Boolean(scopeCheck?.core_ok);

  const run = async (name: string, fn: () => Promise<void>) => {
    setBusy(name);
    setErr(null);
    try {
      await fn();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(null);
    }
  };

  const upload = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const form = new FormData(e.currentTarget);
    run("upload", async () => {
      const res = await send<Connection>("/connect", "POST", form);
      setCheck(res.scope_check ?? null);
      conn.mutate(res);
    });
  };

  const input = "w-full rounded-lg border border-line bg-surface px-3 py-2 text-sm text-ink placeholder:text-ink-3";
  const c = caps.data;
  const featureList = c ? Object.entries(c.features) : [];

  return (
    <>
      <PageHeader title="Connect Google Workspace" subtitle="Read-only. The key is encrypted at rest and never sent back to the browser." />
      {err && <p className="mb-4 rounded-card border border-critical/30 bg-critical/5 p-3 text-sm text-critical">{err}</p>}
      <div className="grid gap-4">
        <Step n={1} title="Service account" done={conn.data.connected}>
          {conn.data.connected && (
            <p className="mb-4 text-sm text-ink-2">
              Connected as <strong className="text-ink">{conn.data.client_email}</strong>, impersonating <strong className="text-ink">{conn.data.admin_email}</strong>
              {conn.data.source === "env" ? " (from server environment)" : ` · uploaded ${timeAgo(conn.data.updated_at)}`}. Upload again to replace it.
            </p>
          )}
          <form onSubmit={upload} className="grid gap-3 md:grid-cols-2">
            <label className="md:col-span-2">
              <span className="mb-1 block text-sm font-medium">Service account key (JSON)</span>
              <input name="file" type="file" accept="application/json,.json" required className={input} />
            </label>
            <label>
              <span className="mb-1 block text-sm font-medium">Admin email to impersonate</span>
              <input name="admin_email" type="email" required placeholder="orgpulse-admin@yourdomain.com" defaultValue={conn.data.admin_email ?? ""} className={input} />
            </label>
            <div />
            <label>
              <span className="mb-1 block text-sm font-medium">BigQuery project <span className="font-normal text-ink-3">(optional)</span></span>
              <input name="bigquery_project" placeholder="my-gcp-project" defaultValue={conn.data.bigquery_project ?? ""} className={input} />
            </label>
            <label>
              <span className="mb-1 block text-sm font-medium">BigQuery dataset <span className="font-normal text-ink-3">(only if Workspace log export is set up)</span></span>
              <input name="bigquery_dataset" placeholder="workspace_logs" defaultValue={conn.data.bigquery_dataset ?? ""} className={input} />
            </label>
            <div className="md:col-span-2">
              <Button type="submit" variant="primary" disabled={busy !== null}>
                {busy === "upload" ? <Loader2 size={14} className="animate-spin" aria-hidden /> : <Upload size={14} aria-hidden />}
                Save and check scopes
              </Button>
            </div>
          </form>
        </Step>

        <Step n={2} title="Connection check" done={scopeCheck?.core_ok}>
          {scopeCheck ? (
            <ScopeChecklist check={scopeCheck} />
          ) : (
            <p className="text-sm text-ink-3">Upload a key to see which scopes are granted.</p>
          )}
          {conn.data.connected && (
            <Button
              className="mt-3"
              onClick={() => run("check", async () => setCheck(await send<ScopeCheck>("/connect/check", "POST")))}
              disabled={busy !== null}
            >
              {busy === "check" && <Loader2 size={14} className="animate-spin" aria-hidden />} Re-check scopes
            </Button>
          )}
        </Step>

        <Step n={3} title="Plan detection" done={Boolean(c?.detected_at)}>
          {c?.detected_at ? (
            <div className="mb-4">
              <p className="text-base">
                Detected: <strong>Google Workspace {c.edition}</strong>
                {c.licences_assigned ? ` · ${c.licences_assigned} licences` : ""}
              </p>
              <p className="text-xs text-ink-3">
                Checked {fmtDate(c.detected_at, true)}
                {c.licensing_error && ` · edition unknown: ${c.licensing_error}`}
              </p>
              <ul className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
                {featureList.map(([key, f]) => (
                  <li key={key} className="flex items-center gap-2 text-sm">
                    {f.enabled ? <CheckCircle2 size={16} className="text-good" aria-hidden /> : <Lock size={14} className="text-ink-3" aria-hidden />}
                    <span className={f.enabled ? "text-ink" : "text-ink-3"}>{f.title}</span>
                    {!f.enabled && <Chip className="ml-auto">{f.status === "locked" ? "Locked" : f.status === "not_configured" ? "Not set up" : "Retry"}</Chip>}
                  </li>
                ))}
              </ul>
            </div>
          ) : (
            <p className="mb-3 text-sm text-ink-3">Reads your edition from the License Manager API, then checks each paid capability with a cheap read call.</p>
          )}
          <Button
            onClick={() =>
              run("detect", async () => {
                await caps.mutate(await send<Capabilities>("/connect/detect", "POST"));
              })
            }
            disabled={!conn.data.connected || busy !== null}
          >
            {busy === "detect" && <Loader2 size={14} className="animate-spin" aria-hidden />} {c?.detected_at ? "Re-check plan" : "Detect plan"}
          </Button>
        </Step>

        <Step n={4} title="180-day backfill">
          <p className="mb-3 text-sm text-ink-2">
            Google keeps activity logs for about 6 months, so the first sync pulls everything it can. This can take a while for large domains; you can leave this page.
          </p>
          <Button
            variant="primary"
            onClick={() =>
              run("backfill", async () => {
                await send("/connect/backfill", "POST");
                setBackfillStarted(true);
                sync.mutate();
              })
            }
            disabled={!conn.data.connected || !coreOk || busy !== null || (sync.data?.running.length ?? 0) > 0}
          >
            {(sync.data?.running.length ?? 0) > 0 ? "Sync running…" : "Start backfill"}
          </Button>
          {conn.data.connected && !coreOk && (
            <p className="mt-2 text-sm text-ink-3">Available once step 2 shows every core scope as granted.</p>
          )}
          {sync.data?.derived_metrics && sync.data.derived_metrics.length > 0 && (
            <p className="mt-3 text-xs text-ink-3">
              Google&apos;s usage report has no data for {sync.data.derived_metrics.join(", ")} on this domain, so those are counted from Meet, Chat and Calendar activity events instead.
            </p>
          )}
          {sync.data && sync.data.jobs.length > 0 && (
            <ul className="mt-4 divide-y divide-line rounded-lg border border-line text-sm">
              {sync.data.jobs.map((j) => (
                <li key={j.key} className="flex flex-wrap items-center gap-3 px-3 py-2">
                  <span className="w-full truncate font-mono text-xs sm:w-60" title={j.key}>{j.key}</span>
                  {j.status === "running" ? (
                    <span className="inline-flex items-center gap-1 text-brand">
                      <Loader2 size={14} className="animate-spin" aria-hidden /> running
                      {j.progress && ` · ${j.progress.done}/${j.progress.total} days`}
                    </span>
                  ) : j.status === "error" ? (
                    <span className="min-w-0 flex-1 text-critical">{j.error}</span>
                  ) : j.status === "interrupted" ? (
                    <span className="min-w-0 flex-1 text-serious">interrupted · {j.error}</span>
                  ) : j.status === "skipped" ? (
                    <span className="min-w-0 flex-1 text-ink-3">skipped · {j.error}</span>
                  ) : (
                    <span className="text-ink-2">ok · {timeAgo(j.last_success)}</span>
                  )}
                  {j.missing_metrics && Object.keys(j.missing_metrics).length > 0 && (
                    <span className="w-full text-xs text-ink-3">
                      Usage parameters not found for: {Object.keys(j.missing_metrics).join(", ")} (logged on the server with similar names)
                    </span>
                  )}
                </li>
              ))}
            </ul>
          )}
        </Step>
      </div>
    </>
  );
}
