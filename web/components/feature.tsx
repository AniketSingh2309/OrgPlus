"use client";

import { ExternalLink, Lock } from "lucide-react";
import { createContext, type ReactNode, useContext } from "react";
import type { Capabilities, FeatureInfo } from "@/lib/types";
import { Chip } from "./ui";

type Ctx = { caps: Capabilities | undefined; hideLocked: boolean };
export const CapabilitiesCtx = createContext<Ctx>({ caps: undefined, hideLocked: false });
export const useCapabilities = () => useContext(CapabilitiesCtx);

const STATUS_TEXT: Record<FeatureInfo["status"], string> = {
  on: "On",
  locked: "Locked",
  error: "Check failed",
  not_configured: "Not set up",
  unknown: "Not checked",
};

export function LockedCard({ feature, compact }: { feature: FeatureInfo; compact?: boolean }) {
  const short = feature.requires.replace(/ \(.*\)$/, "");
  return (
    <section
      aria-label={`${feature.title} (locked)`}
      className="rounded-card border border-dashed border-line bg-surface-2/50 p-4 text-ink-3"
    >
      <div className="flex items-start gap-3">
        <span className="rounded-full bg-surface p-2">
          <Lock size={16} aria-hidden />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-sm font-semibold text-ink-2">{feature.title}</h3>
            <span className="rounded-full bg-surface-2 px-2 py-0.5 text-xs font-medium text-ink-2">Needs {short}</span>
            {feature.status !== "locked" && <Chip>{STATUS_TEXT[feature.status]}</Chip>}
          </div>
          <p className="mt-1 text-sm">{feature.cards[0]?.description ?? feature.description}</p>
          {!compact && feature.reason && feature.status !== "locked" && (
            <p className="mt-1 text-xs">Status: {feature.reason}</p>
          )}
          <a
            href={feature.how_to_enable}
            target="_blank"
            rel="noreferrer"
            className="mt-2 inline-flex items-center gap-1 text-sm font-medium text-brand hover:underline"
          >
            How to enable <ExternalLink size={12} aria-hidden />
          </a>
        </div>
      </div>
    </section>
  );
}

/**
 * Renders children only if the capability is on. Locked features stay visible
 * as a greyed card unless the admin switched on "hide locked features".
 */
export function Feature({ name, children, fallback }: { name: string; children: ReactNode; fallback?: ReactNode }) {
  const { caps, hideLocked } = useCapabilities();
  const feature = caps?.features[name];
  if (!caps) return null;
  if (feature?.enabled) return <>{children}</>;
  if (hideLocked || !feature) return <>{fallback ?? null}</>;
  return <LockedCard feature={feature} />;
}
