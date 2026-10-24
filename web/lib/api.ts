import useSWR, { type SWRConfiguration } from "swr";

export class ApiError extends Error {
  constructor(
    public status: number,
    public body: unknown,
  ) {
    const detail = (body as { detail?: unknown })?.detail;
    super(typeof detail === "string" ? detail : `Request failed (${status})`);
  }
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api${path}`, { ...init, cache: "no-store" });
  const isJson = res.headers.get("content-type")?.includes("application/json");
  const body = isJson ? await res.json() : await res.text();
  if (!res.ok) throw new ApiError(res.status, body);
  return body as T;
}

export const send = <T,>(path: string, method: "POST" | "PUT" | "DELETE", data?: unknown) =>
  api<T>(path, {
    method,
    headers: data instanceof FormData ? undefined : { "content-type": "application/json" },
    body: data instanceof FormData ? data : data === undefined ? undefined : JSON.stringify(data),
  });

/** Background refresh when the real-time socket is down (ms). */
export const LIVE_REFRESH_MS = 30_000;
/** With the socket up, pushes do the work; this is only a safety net. */
const SOCKET_SAFETY_NET_MS = 5 * 60_000;

let socketLive = false;
/** Set by RealtimeProvider as the Socket.IO connection comes and goes. */
export const setLive = (live: boolean) => {
  socketLive = live;
};
export const isLive = () => socketLive;

/**
 * SWR hook for a GET endpoint; pass null to skip. Pages update the moment the
 * server pushes a change (RealtimeProvider); polling is only a fallback for when
 * the socket is down. Current data stays on screen while it reloads.
 */
export function useApi<T>(path: string | null, config?: SWRConfiguration<T, ApiError>) {
  return useSWR<T, ApiError>(path, (p: string) => api<T>(p), {
    refreshInterval: () => (socketLive ? SOCKET_SAFETY_NET_MS : LIVE_REFRESH_MS),
    revalidateOnFocus: true,
    keepPreviousData: true,
    ...config,
  });
}
