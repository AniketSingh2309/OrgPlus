"use client";

import { KeyRound, Loader2, Trash2 } from "lucide-react";
import { useState } from "react";
import { send, useApi } from "@/lib/api";
import { timeAgo } from "@/lib/format";
import { Button, Card, Chip, ErrorState } from "./ui";

type Account = {
  id: string;
  email: string;
  name: string;
  status: "active" | "setup_incomplete";
  created_at: string;
  last_login_at: string | null;
};

const STATUS: Record<Account["status"], { label: string; tone: "good" | "neutral" }> = {
  active: { label: "Active", tone: "good" },
  setup_incomplete: { label: "Setup not finished", tone: "neutral" },
};

/** Admins: everyone who signed up; reset a lost authenticator, remove accounts. */
export function AccountsCard() {
  const { data, error, mutate } = useApi<{ accounts: Account[]; me: string }>("/accounts");
  const [busy, setBusy] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [link, setLink] = useState<{ email: string; url: string } | null>(null);

  async function act(id: string, what: "reset" | "remove", email: string) {
    if (what === "remove" && !window.confirm(`Remove ${email}'s Org+ account? They'll be signed out.`)) return;
    if (what === "reset" && !window.confirm(`Reset ${email}'s authenticator? They'll be signed out and need a new QR code.`)) return;
    setBusy(id + what);
    setNotice(null);
    setLink(null);
    try {
      if (what === "remove") await send(`/accounts/${id}`, "DELETE");
      if (what === "reset") {
        const r = await send<{ enroll_path: string }>(`/accounts/${id}/reset-mfa`, "POST");
        setLink({ email, url: window.location.origin + r.enroll_path });
      }
      await mutate();
    } catch (err) {
      setNotice((err as Error).message);
    } finally {
      setBusy(null);
    }
  }

  if (error) return <ErrorState error={error} retry={() => mutate()} />;
  const rows = data?.accounts ?? [];

  return (
    <Card
      title="Accounts"
      subtitle="Everyone from your organisation who signed up for Org+"
    >
      {notice && <p className="mb-3 rounded-md bg-critical/10 px-3 py-2 text-sm text-critical">{notice}</p>}
      {link && (
        <div className="mb-3 rounded-md bg-brand-soft px-3 py-2 text-sm text-brand-strong">
          Send this one-time link to {link.email} (valid 24 hours) to set up their authenticator again:
          <code className="mt-1 block select-all break-all font-mono text-xs">{link.url}</code>
        </div>
      )}
      {!data ? (
        <p className="text-sm text-ink-3">Loading…</p>
      ) : (
        <ul className="divide-y divide-line">
          {rows.map((a) => (
            <li key={a.id} className="flex flex-wrap items-center gap-x-3 gap-y-2 py-2.5">
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium text-ink">
                  {a.name} {a.email === data.me && <span className="text-ink-3">(you)</span>}
                </p>
                <p className="truncate text-xs text-ink-3">
                  {a.email} · {a.last_login_at ? `last sign-in ${timeAgo(a.last_login_at)}` : `signed up ${timeAgo(a.created_at)}`}
                </p>
              </div>
              <Chip tone={STATUS[a.status].tone}>{STATUS[a.status].label}</Chip>
              <div className="flex gap-1.5">
                {a.status !== "setup_incomplete" && (
                  <Button onClick={() => act(a.id, "reset", a.email)} disabled={busy !== null}>
                    {busy === a.id + "reset" ? <Loader2 size={14} className="animate-spin" aria-hidden /> : <KeyRound size={14} aria-hidden />} Reset authenticator
                  </Button>
                )}
                {a.email !== data.me && (
                  <Button variant="ghost" onClick={() => act(a.id, "remove", a.email)} disabled={busy !== null}>
                    <Trash2 size={14} aria-hidden />
                    <span className="sr-only">Remove {a.email}</span>
                  </Button>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
