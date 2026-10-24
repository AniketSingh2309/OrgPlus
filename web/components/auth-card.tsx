"use client";

import type { InputHTMLAttributes, ReactNode } from "react";
import { BrandLogo } from "./brand";

/** The centred card every sign-in / sign-up page uses. */
export function AuthCard({ title, subtitle, children, footer }: { title: string; subtitle?: string; children: ReactNode; footer?: ReactNode }) {
  return (
    <main className="flex min-h-screen items-center justify-center bg-bg px-4 py-10">
      <div className="w-full max-w-sm">
        <div className="rounded-card border border-line bg-surface p-6">
          <div className="flex justify-center">
            <BrandLogo height={56} />
          </div>
          <h1 className="mt-3 text-center text-lg font-semibold text-ink">{title}</h1>
          {subtitle && <p className="mt-1 text-center text-sm text-ink-2">{subtitle}</p>}
          <div className="mt-5">{children}</div>
        </div>
        {footer && <div className="mt-4 text-center text-sm text-ink-2">{footer}</div>}
        <p className="mt-4 text-center text-xs text-ink-3">Read-only. Org+ never reads email or file content.</p>
      </div>
    </main>
  );
}

export function Field({ label, hint, ...input }: { label: string; hint?: string } & InputHTMLAttributes<HTMLInputElement>) {
  return (
    <label className="mb-3 block text-left">
      <span className="text-sm font-medium text-ink">{label}</span>
      <input
        {...input}
        className="mt-1 w-full rounded-lg border border-line bg-surface px-3 py-2 text-sm text-ink outline-none placeholder:text-ink-3 focus:border-brand focus:ring-2 focus:ring-brand/30"
      />
      {hint && <span className="mt-1 block text-xs text-ink-3">{hint}</span>}
    </label>
  );
}

export function Submit({ busy, children }: { busy: boolean; children: ReactNode }) {
  return (
    <button
      type="submit"
      disabled={busy}
      className="mt-2 w-full rounded-lg bg-brand px-4 py-2 text-sm font-medium text-on-brand hover:bg-brand-strong disabled:opacity-60"
    >
      {busy ? "Please wait…" : children}
    </button>
  );
}

export function Notice({ tone, children }: { tone: "error" | "ok"; children: ReactNode }) {
  return (
    <p
      role={tone === "error" ? "alert" : "status"}
      className={
        tone === "error"
          ? "mb-3 rounded-md bg-critical/10 px-3 py-2 text-sm text-critical"
          : "mb-3 rounded-md bg-brand-soft px-3 py-2 text-sm text-brand-strong"
      }
    >
      {children}
    </p>
  );
}

/** POST to a public account endpoint; returns the JSON body or throws its message. */
export async function postAccount<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`/api/account/${path}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const d = data?.detail;
    throw new Error(typeof d === "string" ? d : d?.message ?? "Something went wrong. Try again.");
  }
  return data as T;
}
