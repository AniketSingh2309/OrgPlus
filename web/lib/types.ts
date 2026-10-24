export type Cell = { date: string; score: number; level: number; pending: boolean };
export type Person = { id: string | null; email: string; name: string | null };

export type Alert = {
  id: string;
  severity: "high" | "medium" | "low";
  kind: string;
  title: string;
  detail: string;
  users: Person[];
  count: number;
  link: string;
};

export type Me = {
  email: string;
  name: string;
  role: "admin" | "manager";
  domain: string | null;
  connected: boolean;
  /** Just signed up: the organisation's private database is still being created. */
  provisioning?: boolean;
  plan_badge: string;
  hide_locked: boolean;
  sync: SyncInfo;
};

export type SyncInfo = { last_synced: string | null; running: string[]; errors: Record<string, string | null> };

export type FeatureInfo = {
  enabled: boolean;
  status: "on" | "locked" | "error" | "not_configured" | "unknown";
  reason: string;
  requires: string;
  title: string;
  description: string;
  how_to_enable: string;
  page: string;
  paid: boolean;
  cards: { id: string; title: string; description: string }[];
  checked_at: string | null;
};

export type Capabilities = {
  edition: string;
  tier: string;
  badge: string;
  detected_at: string | null;
  licensing_error: string | null;
  sku_breakdown: Record<string, { edition: string; tier: string; count: number; known: boolean }>;
  licences_total: number | null;
  licences_assigned: number | null;
  features: Record<string, FeatureInfo>;
  changes: { id: number; key: string; old: string | null; new: string; at: string }[];
};
