"use client";

import clsx from "clsx";
import {
  Activity,
  AppWindow,
  BadgeCheck,
  BarChart3,
  Clock,
  CreditCard,
  FolderLock,
  Globe2,
  HardDrive,
  LayoutDashboard,
  Lock,
  LogOut,
  Map,
  Menu,
  Monitor,
  Moon,
  PlugZap,
  RefreshCw,
  Settings,
  Share2,
  ShieldCheck,
  Sparkles,
  Sun,
  UserPlus,
  Users,
  UsersRound,
  Video,
  X,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { signOut } from "next-auth/react";
import { type ReactNode, useEffect, useRef, useState } from "react";
import { useSWRConfig } from "swr";
import { ApiError, isLive, send, useApi } from "@/lib/api";
import { timeAgo } from "@/lib/format";
import type { Capabilities, Me } from "@/lib/types";
import { BrandLogo } from "./brand";
import { CapabilitiesCtx } from "./feature";
import { RealtimeProvider, useRealtimeStatus } from "./realtime";
import { useTheme } from "./providers";
import { Avatar, Button, Chip, ErrorState, PageSkeleton } from "./ui";

type NavItem = { href: string; label: string; icon: typeof Users; admin?: boolean; locked?: boolean };

const MAIN: NavItem[] = [
  { href: "/", label: "Overview", icon: LayoutDashboard },
  { href: "/people", label: "People", icon: Users },
  { href: "/apps", label: "Apps", icon: AppWindow, admin: true },
  { href: "/security", label: "Security", icon: ShieldCheck, admin: true },
  { href: "/devices", label: "Devices", icon: Monitor, admin: true },
];

const INSIGHTS: NavItem[] = [
  { href: "/insights/licences", label: "Licences", icon: CreditCard, admin: true },
  { href: "/insights/onboarding", label: "Joiners & leavers", icon: UserPlus, admin: true },
  { href: "/insights/storage", label: "Storage", icon: HardDrive, admin: true },
  { href: "/insights/meetings", label: "Meeting load", icon: Video },
  { href: "/insights/wellbeing", label: "After-hours", icon: Clock },
  { href: "/insights/sharing", label: "External sharing", icon: Share2, admin: true },
  { href: "/insights/groups", label: "Groups hygiene", icon: UsersRound, admin: true },
  { href: "/insights/admins", label: "Admin roles", icon: BadgeCheck, admin: true },
  { href: "/insights/map", label: "Sign-in map", icon: Map, admin: true },
  { href: "/insights/teams", label: "Teams", icon: BarChart3 },
];

const MODULE_ICONS: Record<string, typeof Users> = {
  bigquery_logs: Activity,
  gmail_logs: Globe2,
  vault: FolderLock,
  alert_center: ShieldCheck,
  dlp_events: FolderLock,
  context_aware_access: Lock,
  gemini_usage: Sparkles,
  chrome_mgmt: Globe2,
  classroom: Users,
};

function NavSection({ title, items, path, onNavigate }: { title?: string; items: NavItem[]; path: string; onNavigate: () => void }) {
  if (!items.length) return null;
  return (
    <div className="mb-4">
      {title && <div className="mb-1 px-3 text-[11px] font-semibold uppercase tracking-wider text-ink-3">{title}</div>}
      <ul>
        {items.map((it) => {
          const active = it.href === "/" ? path === "/" : path.startsWith(it.href);
          const Icon = it.icon;
          return (
            <li key={it.href}>
              <Link
                href={it.href}
                onClick={onNavigate}
                aria-current={active ? "page" : undefined}
                className={clsx(
                  "flex items-center gap-2.5 rounded-lg px-3 py-1.5 text-sm transition",
                  active ? "bg-brand-soft font-medium text-brand-strong" : "text-ink-2 hover:bg-surface-2 hover:text-ink",
                )}
              >
                <Icon size={16} aria-hidden />
                <span className="flex-1 truncate">{it.label}</span>
                {it.locked && <Lock size={12} className="text-ink-3" aria-label="locked" />}
              </Link>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

/** Green while pushes arrive over the socket; amber while it reconnects (pages still poll). */
function LiveBadge() {
  const status = useRealtimeStatus();
  const live = status === "live";
  return (
    <span
      className="inline-flex items-center gap-1.5"
      title={live ? "Real-time: changes appear instantly, no need to reload" : "Reconnecting; pages refresh every 30 seconds meanwhile"}
    >
      <span className="relative flex h-2 w-2" aria-hidden>
        {live && <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-good opacity-60" />}
        <span className={clsx("relative inline-flex h-2 w-2 rounded-full", live ? "bg-good" : "bg-warning")} />
      </span>
      {live ? "Live" : status === "connecting" ? "Connecting…" : "Reconnecting…"}
    </span>
  );
}

function ThemeToggle() {
  const { theme, setTheme } = useTheme();
  const next = theme === "dark" ? "light" : theme === "light" ? "system" : "dark";
  const Icon = theme === "dark" ? Moon : theme === "light" ? Sun : Monitor;
  return (
    <button
      onClick={() => setTheme(next)}
      className="rounded-lg p-2 text-ink-2 hover:bg-surface-2"
      aria-label={`Theme: ${theme}. Switch to ${next}`}
      title={`Theme: ${theme}`}
    >
      <Icon size={18} aria-hidden />
    </button>
  );
}

function ChangeBanner({ caps, isAdmin, onAck }: { caps: Capabilities; isAdmin: boolean; onAck: () => void }) {
  if (!caps.changes?.length) return null;
  const parts = caps.changes.map((c) => `${caps.features[c.key]?.title ?? c.key}: ${c.old ?? "?"} → ${c.new}`);
  return (
    <div className="no-print mb-4 flex flex-wrap items-center justify-between gap-2 rounded-card border border-brand/30 bg-brand-soft px-4 py-3 text-sm text-ink">
      <span>
        <strong>Your Workspace plan changed.</strong> {parts.join(" · ")}
      </span>
      {isAdmin && (
        <Button variant="ghost" onClick={onAck}>
          Dismiss
        </Button>
      )}
    </div>
  );
}

export function AppShell({ children }: { children: ReactNode }) {
  const path = usePathname();
  const [open, setOpen] = useState(false);
  // Pushed live over Socket.IO; this poll only matters while the socket is down.
  const me = useApi<Me>("/me", {
    refreshInterval: (d) => (d?.provisioning ? 2_000 : isLive() ? 60_000 : d?.sync.running.length ? 3_000 : 10_000),
  });
  const caps = useApi<Capabilities>("/capabilities");
  const { mutate: mutateAll } = useSWRConfig();
  const wasRunning = useRef(false);
  const lastSynced = useRef<string | null | undefined>(undefined);

  // When a sync finishes (or new data lands), reload every page's data at once.
  useEffect(() => {
    const sync = me.data?.sync;
    if (!sync) return;
    const running = sync.running.length > 0;
    const finished = wasRunning.current && !running;
    const newData = lastSynced.current !== undefined && sync.last_synced !== lastSynced.current;
    if (finished || newData) mutateAll((key) => typeof key === "string" && key !== "/me");
    wasRunning.current = running;
    lastSynced.current = sync.last_synced;
  }, [me.data?.sync, mutateAll]);

  useEffect(() => setOpen(false), [path]);

  // Session revoked (password changed elsewhere, account removed): back to sign-in.
  const expired = me.error instanceof ApiError && me.error.status === 401;
  useEffect(() => {
    if (expired) void signOut({ callbackUrl: "/signin?expired=1" });
  }, [expired]);

  if (expired) {
    return (
      <div className="mx-auto max-w-6xl p-6">
        <PageSkeleton />
      </div>
    );
  }
  if (me.error) {
    return (
      <div className="mx-auto max-w-lg p-8">
        <ErrorState error={me.error} retry={() => me.mutate()} />
      </div>
    );
  }
  if (!me.data) {
    return (
      <div className="mx-auto max-w-6xl p-6">
        <PageSkeleton />
      </div>
    );
  }

  if (me.data.provisioning) {
    // New organisation: the worker is creating its private database (a few seconds).
    // /me is polled every 2 s meanwhile (the live socket starts with the dashboard).
    return (
      <main className="flex min-h-screen items-center justify-center bg-bg px-4">
        <div className="w-full max-w-sm rounded-card border border-line bg-surface p-6 text-center">
          <div className="flex justify-center">
            <BrandLogo height={56} />
          </div>
          <div className="mx-auto mt-5 h-8 w-8 animate-spin rounded-full border-2 border-line border-t-brand" aria-hidden />
          <h1 className="mt-4 text-lg font-semibold text-ink">Setting up {me.data.domain}</h1>
          <p className="mt-1 text-sm text-ink-2">
            Creating your organisation&apos;s own private database. This takes a few seconds.
          </p>
          <button onClick={() => signOut({ callbackUrl: "/signin" })} className="mt-5 text-xs font-medium text-ink-3 hover:underline">
            Sign out
          </button>
        </div>
      </main>
    );
  }

  const isAdmin = me.data.role === "admin";
  const hideLocked = me.data.hide_locked;
  const filter = (items: NavItem[]) => items.filter((i) => isAdmin || !i.admin);
  const modules: NavItem[] = Object.entries(caps.data?.features ?? {})
    .filter(([, f]) => isAdmin && (f.enabled || !hideLocked))
    .map(([key, f]) => ({ href: `/m/${key}`, label: f.title, icon: MODULE_ICONS[key] ?? Sparkles, locked: !f.enabled }));
  const settings: NavItem[] = isAdmin
    ? [
        { href: "/plan", label: "Plan & features", icon: BadgeCheck },
        { href: "/connect", label: "Connect", icon: PlugZap },
        { href: "/settings", label: "Settings", icon: Settings },
      ]
    : [];
  const sync = me.data.sync;

  const sidebar = (
    <nav aria-label="Main" className="flex h-full flex-col">
      <Link href="/" className="mb-5 block px-1 pt-1" aria-label="Org+ home">
        <BrandLogo fill />
      </Link>
      <div className="flex-1 overflow-y-auto">
        <NavSection items={filter(MAIN)} path={path} onNavigate={() => setOpen(false)} />
        <NavSection title="Insights" items={filter(INSIGHTS)} path={path} onNavigate={() => setOpen(false)} />
        <NavSection title="Premium" items={modules} path={path} onNavigate={() => setOpen(false)} />
        <NavSection title="Admin" items={settings} path={path} onNavigate={() => setOpen(false)} />
      </div>
      <div className="border-t border-line px-3 pt-3">
        <div className="flex items-center gap-2">
          <Avatar name={me.data.name} email={me.data.email} size={28} />
          <div className="min-w-0 flex-1">
            <div className="truncate text-sm font-medium text-ink">{me.data.name}</div>
            <div className="truncate text-xs text-ink-3">{isAdmin ? "Org admin" : `Manager · ${me.data.email}`}</div>
          </div>
          <button onClick={() => signOut({ callbackUrl: "/signin" })} className="rounded p-1.5 text-ink-3 hover:bg-surface-2" aria-label="Sign out">
            <LogOut size={16} aria-hidden />
          </button>
        </div>
      </div>
    </nav>
  );

  return (
    <RealtimeProvider>
    <CapabilitiesCtx.Provider value={{ caps: caps.data, hideLocked }}>
      <div className="flex min-h-screen">
        <aside className="no-print sticky top-0 hidden h-screen w-60 shrink-0 border-r border-line bg-surface px-2 py-4 lg:block">{sidebar}</aside>

        {open && (
          <div className="no-print fixed inset-0 z-40 lg:hidden">
            <div className="absolute inset-0 bg-black/40" onClick={() => setOpen(false)} />
            <aside className="absolute inset-y-0 left-0 w-72 bg-surface px-2 py-4 shadow-xl">
              <button className="absolute right-3 top-3 rounded p-1 text-ink-2" onClick={() => setOpen(false)} aria-label="Close menu">
                <X size={18} />
              </button>
              {sidebar}
            </aside>
          </div>
        )}

        <div className="flex min-w-0 flex-1 flex-col">
          <header className="no-print sticky top-0 z-30 flex items-center gap-2 border-b border-line bg-surface/90 px-4 py-2 backdrop-blur">
            <button className="rounded-lg p-2 text-ink-2 hover:bg-surface-2 lg:hidden" onClick={() => setOpen(true)} aria-label="Open menu">
              <Menu size={18} />
            </button>
            <div className="flex min-w-0 flex-1 flex-wrap items-center gap-2 text-xs text-ink-3">
              <LiveBadge />
              <span className="inline-flex items-center gap-1" title={sync.last_synced ?? "never"}>
                <RefreshCw size={12} className={clsx(sync.running.length > 0 && "animate-spin text-brand")} aria-hidden />
                {sync.running.length ? "Syncing…" : `Last synced ${timeAgo(sync.last_synced)}`}
              </span>
              {Object.keys(sync.errors).length > 0 && isAdmin && (
                <Link href="/connect" className="text-critical hover:underline">
                  {Object.keys(sync.errors).length} sync error(s)
                </Link>
              )}
            </div>
            <Link href={isAdmin ? "/plan" : "#"} className="hidden sm:block">
              <Chip tone="brand">{me.data.plan_badge}</Chip>
            </Link>
            <ThemeToggle />
          </header>

          <main className="print-full mx-auto w-full max-w-7xl flex-1 px-4 py-5 sm:px-6">
            {!me.data.connected && isAdmin && path !== "/connect" && (
              <div className="no-print mb-4 flex flex-wrap items-center justify-between gap-2 rounded-card border border-line bg-surface px-4 py-3 text-sm">
                <span>Google Workspace isn&apos;t connected yet, so there&apos;s no live data.</span>
                <Link href="/connect" className="font-medium text-brand hover:underline">
                  Connect now →
                </Link>
              </div>
            )}
            {caps.data && (
              <ChangeBanner
                caps={caps.data}
                isAdmin={isAdmin}
                onAck={async () => {
                  await send("/capabilities/changes/ack", "POST");
                  caps.mutate();
                }}
              />
            )}
            {children}
          </main>
        </div>
      </div>
    </CapabilitiesCtx.Provider>
    </RealtimeProvider>
  );
}
