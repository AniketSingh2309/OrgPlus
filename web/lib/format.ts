export function timeAgo(iso: string | null | undefined): string {
  if (!iso) return "never";
  const secs = (Date.now() - new Date(iso).getTime()) / 1000;
  if (secs < 60) return "just now";
  const units: [number, string][] = [
    [60, "min"],
    [3600, "h"],
    [86400, "d"],
    [86400 * 30, "mo"],
    [86400 * 365, "y"],
  ];
  let label = "";
  for (let i = units.length - 1; i >= 0; i--) {
    const [size, name] = units[i];
    if (secs >= size) {
      label = `${Math.floor(secs / size)}${name === "min" ? " min" : name}`;
      break;
    }
  }
  return `${label} ago`;
}

export const fmtDate = (iso: string | null | undefined, withTime = false) =>
  iso
    ? new Date(iso).toLocaleString("en-IN", {
        day: "numeric",
        month: "short",
        year: withTime ? undefined : "numeric",
        ...(withTime ? { hour: "2-digit", minute: "2-digit" } : {}),
      })
    : "—";

export const fmtNum = (n: number | null | undefined, digits = 0) =>
  n === null || n === undefined ? "—" : n.toLocaleString("en-IN", { maximumFractionDigits: digits });

export const fmtInr = (n: number) =>
  n.toLocaleString("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 0 });

export const fmtMb = (mb: number | null | undefined) =>
  mb === null || mb === undefined ? "—" : mb >= 1024 ? `${(mb / 1024).toFixed(1)} GB` : `${Math.round(mb)} MB`;

export const titleCase = (s: string) => s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());

export const initials = (name: string | null | undefined) =>
  (name ?? "")
    .split(/[\s.@]+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((p) => p[0]?.toUpperCase())
    .join("") || "?";

/** Who did it, for events whose actor isn't a user in the domain (external or anonymous). */
export const actorLabel = (email: string | null | undefined) => email || "External or anonymous";
