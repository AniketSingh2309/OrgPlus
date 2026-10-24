"use client";

import clsx from "clsx";
import { AlertOctagon, AlertTriangle, CheckCircle2, Download, Info, Inbox, RefreshCw } from "lucide-react";
import Link from "next/link";
import { type ReactNode, useState } from "react";
import { type ApiError, useApi } from "@/lib/api";
import { initials } from "@/lib/format";

export function Card({
  title,
  subtitle,
  action,
  children,
  className,
  bodyClass,
}: {
  title?: ReactNode;
  subtitle?: ReactNode;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
  bodyClass?: string;
}) {
  return (
    <section className={clsx("rounded-card border border-line bg-surface", className)}>
      {(title || action) && (
        <header className="flex flex-wrap items-start justify-between gap-2 border-b border-line px-4 py-3">
          <div className="min-w-0">
            {title && <h2 className="text-sm font-semibold text-ink">{title}</h2>}
            {subtitle && <p className="mt-0.5 text-xs text-ink-3">{subtitle}</p>}
          </div>
          {action && <div className="flex items-center gap-2">{action}</div>}
        </header>
      )}
      <div className={clsx("p-4", bodyClass)}>{children}</div>
    </section>
  );
}

export function PageHeader({ title, subtitle, action }: { title: string; subtitle?: ReactNode; action?: ReactNode }) {
  return (
    <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="text-xl font-semibold tracking-tight text-ink sm:text-2xl">{title}</h1>
        {subtitle && <p className="mt-1 text-sm text-ink-2">{subtitle}</p>}
      </div>
      {action && <div className="no-print flex flex-wrap items-center gap-2">{action}</div>}
    </div>
  );
}

export function Kpi({
  label,
  value,
  hint,
  tone,
}: {
  label: string;
  value: ReactNode;
  hint?: ReactNode;
  tone?: "good" | "warning" | "critical";
}) {
  return (
    <div className="rounded-card border border-line bg-surface p-4">
      <div className="text-xs font-medium uppercase tracking-wide text-ink-3">{label}</div>
      <div className="mt-1.5 text-2xl font-semibold tabular-nums text-ink">{value}</div>
      {hint && (
        <div
          className={clsx(
            "mt-1 flex items-center gap-1 text-xs",
            tone === "good" && "text-good",
            tone === "warning" && "text-ink-2",
            tone === "critical" && "text-critical",
            !tone && "text-ink-3",
          )}
        >
          {tone === "critical" && <AlertTriangle size={12} aria-hidden />}
          {hint}
        </div>
      )}
    </div>
  );
}

export function Chip({
  children,
  tone = "neutral",
  className,
}: {
  children: ReactNode;
  tone?: "neutral" | "brand" | "good" | "warning" | "serious" | "critical";
  className?: string;
}) {
  return (
    <span
      className={clsx(
        "inline-flex items-center gap-1 whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-medium",
        tone === "neutral" && "bg-surface-2 text-ink-2",
        tone === "brand" && "bg-brand-soft text-brand-strong",
        tone === "good" && "bg-good/10 text-good",
        tone === "warning" && "bg-warning/15 text-ink",
        tone === "serious" && "bg-serious/15 text-ink",
        tone === "critical" && "bg-critical/10 text-critical",
        className,
      )}
    >
      {children}
    </span>
  );
}

/** Severity is never colour alone: icon + label. */
export function Severity({ level }: { level: "high" | "medium" | "low" }) {
  const map = {
    high: { tone: "critical", icon: AlertOctagon, label: "High" },
    medium: { tone: "serious", icon: AlertTriangle, label: "Medium" },
    low: { tone: "neutral", icon: Info, label: "Low" },
  } as const;
  const { tone, icon: Icon, label } = map[level];
  return (
    <Chip tone={tone}>
      <Icon size={12} aria-hidden />
      {label}
    </Chip>
  );
}

export function RiskChip({ risk }: { risk: string }) {
  if (risk === "high") return <Severity level="high" />;
  if (risk === "medium") return <Severity level="medium" />;
  return (
    <Chip tone="good">
      <CheckCircle2 size={12} aria-hidden />
      Low
    </Chip>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={clsx("animate-pulse rounded-md bg-surface-2", className)} />;
}

export function CardSkeleton({ rows = 4 }: { rows?: number }) {
  return (
    <div className="rounded-card border border-line bg-surface p-4">
      <Skeleton className="mb-4 h-4 w-40" />
      {Array.from({ length: rows }).map((_, i) => (
        <Skeleton key={i} className="mb-2 h-8 w-full" />
      ))}
    </div>
  );
}

export function PageSkeleton() {
  return (
    <div aria-busy="true" aria-label="Loading">
      <Skeleton className="mb-6 h-7 w-56" />
      <div className="mb-4 grid grid-cols-2 gap-3 lg:grid-cols-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <Skeleton key={i} className="h-24" />
        ))}
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        <CardSkeleton />
        <CardSkeleton />
      </div>
    </div>
  );
}

export function Empty({ title, children, icon }: { title: string; children?: ReactNode; icon?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center px-4 py-10 text-center">
      <div className="mb-3 rounded-full bg-surface-2 p-3 text-ink-3">{icon ?? <Inbox size={20} aria-hidden />}</div>
      <p className="text-sm font-medium text-ink">{title}</p>
      {children && <div className="mt-1 max-w-sm text-sm text-ink-3">{children}</div>}
    </div>
  );
}

export function ErrorState({ error, retry }: { error: ApiError | Error; retry?: () => void }) {
  return (
    <div className="rounded-card border border-critical/30 bg-critical/5 p-4 text-sm">
      <div className="flex items-center gap-2 font-medium text-critical">
        <AlertOctagon size={16} aria-hidden /> Couldn&apos;t load this
      </div>
      <p className="mt-1 text-ink-2">{error.message}</p>
      {retry && (
        <button onClick={retry} className="mt-2 inline-flex items-center gap-1 text-brand hover:underline">
          <RefreshCw size={14} aria-hidden /> Try again
        </button>
      )}
    </div>
  );
}

export function Button({
  children,
  onClick,
  variant = "secondary",
  disabled,
  type = "button",
  className,
}: {
  children: ReactNode;
  onClick?: () => void;
  variant?: "primary" | "secondary" | "ghost";
  disabled?: boolean;
  type?: "button" | "submit";
  className?: string;
}) {
  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
      className={clsx(
        "inline-flex items-center justify-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-medium transition disabled:opacity-50",
        variant === "primary" && "bg-brand text-on-brand hover:bg-brand-strong",
        variant === "secondary" && "border border-line bg-surface text-ink hover:bg-surface-2",
        variant === "ghost" && "text-ink-2 hover:bg-surface-2",
        className,
      )}
    >
      {children}
    </button>
  );
}

export function Tabs<T extends string>({
  tabs,
  value,
  onChange,
}: {
  tabs: { id: T; label: ReactNode }[];
  value: T;
  onChange: (id: T) => void;
}) {
  return (
    <div role="tablist" className="no-print -mx-1 mb-4 flex gap-1 overflow-x-auto border-b border-line px-1">
      {tabs.map((t) => (
        <button
          key={t.id}
          role="tab"
          aria-selected={value === t.id}
          onClick={() => onChange(t.id)}
          className={clsx(
            "-mb-px whitespace-nowrap border-b-2 px-3 py-2 text-sm font-medium transition",
            value === t.id ? "border-brand text-brand" : "border-transparent text-ink-2 hover:text-ink",
          )}
        >
          {t.label}
        </button>
      ))}
    </div>
  );
}

/** email -> profile photo URL for everyone who has one (one small request, shared by all avatars). */
function usePhotos(): Record<string, string> {
  const { data } = useApi<Record<string, string>>("/people/photos", { refreshInterval: 10 * 60_000, revalidateOnFocus: false });
  return data ?? {};
}

/**
 * Profile photo when the person has one in Google (looked up by email), else initials.
 * Falls back to initials if the photo fails to load.
 */
export function Avatar({ name, email, photo, size = 32 }: { name: string | null | undefined; email?: string | null; photo?: string | null; size?: number }) {
  const photos = usePhotos();
  const src = photo || (email ? photos[email.toLowerCase()] : undefined);
  const [broken, setBroken] = useState<string | null>(null);
  if (src && broken !== src) {
    return (
      // eslint-disable-next-line @next/next/no-img-element
      <img
        src={src}
        alt=""
        width={size}
        height={size}
        referrerPolicy="no-referrer"
        loading="lazy"
        onError={() => setBroken(src)}
        style={{ width: size, height: size }}
        className="shrink-0 rounded-full object-cover"
      />
    );
  }
  return (
    <span
      aria-hidden
      style={{ width: size, height: size, fontSize: size * 0.38 }}
      className="inline-flex shrink-0 items-center justify-center rounded-full bg-brand-soft font-semibold text-brand-strong"
    >
      {initials(name)}
    </span>
  );
}

export function PersonLink({ id, name, email, sub }: { id: string | null; name: string | null; email: string | null; sub?: ReactNode }) {
  const label = name || email || "External or anonymous";
  const body = (
    <span className="flex min-w-0 items-center gap-2">
      <Avatar name={label} email={email} size={28} />
      <span className="min-w-0">
        <span className="block truncate font-medium text-ink">{label}</span>
        <span className="block truncate text-xs text-ink-3">{sub ?? email ?? ""}</span>
      </span>
    </span>
  );
  return id ? (
    <Link href={`/people/${id}`} className="hover:underline">
      {body}
    </Link>
  ) : (
    body
  );
}

/** Tiny inline trend line; values are weekly scores. */
export function Sparkline({ values, width = 84, height = 24 }: { values: number[]; width?: number; height?: number }) {
  if (!values.length) return <span className="text-xs text-ink-3">—</span>;
  const max = Math.max(...values, 1);
  const step = width / Math.max(values.length - 1, 1);
  const pts = values.map((v, i) => `${(i * step).toFixed(1)},${(height - 2 - (v / max) * (height - 4)).toFixed(1)}`);
  return (
    <svg width={width} height={height} className="text-brand" role="img" aria-label={`Weekly trend, latest ${values.at(-1)}`}>
      <polyline points={pts.join(" ")} fill="none" stroke="currentColor" strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
    </svg>
  );
}

export function ExportButton({ dataset }: { dataset: string }) {
  return (
    <a
      href={`/api/export/${dataset}.csv`}
      className="no-print inline-flex items-center gap-1.5 rounded-lg border border-line bg-surface px-3 py-1.5 text-sm font-medium text-ink hover:bg-surface-2"
    >
      <Download size={14} aria-hidden /> CSV
    </a>
  );
}

/** Horizontal bar list (HTML, label + value always visible). */
export function BarList({
  items,
  format = (v) => String(v),
  max,
}: {
  items: { label: ReactNode; value: number; key: string; hint?: string }[];
  format?: (v: number) => string;
  max?: number;
}) {
  const top = max ?? Math.max(...items.map((i) => i.value), 1);
  if (!items.length) return <Empty title="Nothing to show yet" />;
  return (
    <ul className="space-y-2">
      {items.map((i) => (
        <li key={i.key} title={i.hint}>
          <div className="mb-1 flex items-baseline justify-between gap-2 text-sm">
            <span className="min-w-0 truncate text-ink">{i.label}</span>
            <span className="shrink-0 tabular-nums text-ink-2">{format(i.value)}</span>
          </div>
          <div className="h-2 rounded-full bg-surface-2">
            <div className="h-2 rounded-full bg-brand" style={{ width: `${Math.min(100, Math.max((i.value / top) * 100, i.value ? 2 : 0))}%` }} />
          </div>
        </li>
      ))}
    </ul>
  );
}

/** Simple responsive table with an optional row cap + "show all". */
export function DataTable<T>({
  rows,
  columns,
  empty = "Nothing here yet",
  initial = 25,
  rowKey,
}: {
  rows: T[];
  columns: { header: ReactNode; cell: (r: T) => ReactNode; className?: string; hideOnMobile?: boolean }[];
  empty?: string;
  initial?: number;
  rowKey: (r: T, i: number) => string;
}) {
  const [all, setAll] = useState(false);
  if (!rows.length) return <Empty title={empty} />;
  const shown = all ? rows : rows.slice(0, initial);
  return (
    <div className="-mx-4 overflow-x-auto">
      <table className="w-full min-w-[560px] text-left text-sm">
        <thead>
          <tr className="border-b border-line text-xs uppercase tracking-wide text-ink-3">
            {columns.map((c, i) => (
              <th key={i} className={clsx("px-4 py-2 font-medium", c.hideOnMobile && "hidden md:table-cell", c.className)}>
                {c.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {shown.map((r, ri) => (
            <tr key={rowKey(r, ri)} className="border-b border-line/60 last:border-0 hover:bg-surface-2/60">
              {columns.map((c, ci) => (
                <td key={ci} className={clsx("px-4 py-2 align-middle", c.hideOnMobile && "hidden md:table-cell", c.className)}>
                  {c.cell(r)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {rows.length > initial && (
        <div className="px-4 pt-3">
          <button onClick={() => setAll(!all)} className="text-sm font-medium text-brand hover:underline">
            {all ? "Show fewer" : `Show all ${rows.length}`}
          </button>
        </div>
      )}
    </div>
  );
}
