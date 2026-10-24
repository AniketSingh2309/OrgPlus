"use client";

import { createContext, type ReactNode, useContext, useEffect, useState } from "react";
import { io, type Socket } from "socket.io-client";
import { useSWRConfig } from "swr";
import { setLive } from "@/lib/api";

type Status = "connecting" | "live" | "offline";
const RealtimeCtx = createContext<Status>("connecting");
export const useRealtimeStatus = () => useContext(RealtimeCtx);

// Forms keep their own edits; never refetch underneath someone typing.
const NEVER_REFRESH = new Set(["/settings", "/weights"]);
// Sync states that mean "a job just finished, data may have changed".
const DONE = new Set(["ok", "error", "skipped", "interrupted"]);

/**
 * One Socket.IO connection for the whole app. The server pushes small notices
 * ("sync job X finished", "settings changed"); we refetch whatever is on screen,
 * so pages update the moment data changes without anyone reloading.
 */
export function RealtimeProvider({ children }: { children: ReactNode }) {
  const { mutate } = useSWRConfig();
  const [status, setStatus] = useState<Status>("connecting");

  useEffect(() => {
    let socket: Socket | null = null;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | null = null;

    // Many jobs can finish together; batch them into one refresh.
    const refreshAll = () => {
      if (timer) clearTimeout(timer);
      timer = setTimeout(() => {
        mutate((key) => typeof key === "string" && !NEVER_REFRESH.has(key));
      }, 800);
    };

    (async () => {
      let first: { url: string; token: string };
      try {
        const res = await fetch("/api/realtime", { cache: "no-store" });
        if (!res.ok) throw new Error(String(res.status));
        first = await res.json();
      } catch {
        setStatus("offline");
        return;
      }
      if (cancelled) return;
      socket = io(first.url, {
        path: "/socket.io",
        transports: ["websocket", "polling"],
        // Fresh short-lived token on every (re)connect.
        auth: (cb) => {
          fetch("/api/realtime", { cache: "no-store" })
            .then((r) => r.json())
            .then((d) => cb({ token: d.token }))
            .catch(() => cb({ token: first.token }));
        },
        reconnectionDelayMax: 10_000,
      });
      socket.on("connect", () => {
        setStatus("live");
        setLive(true);
        refreshAll(); // catch up on anything missed while disconnected
      });
      socket.on("disconnect", () => {
        setStatus("offline");
        setLive(false);
      });
      socket.on("connect_error", () => {
        setStatus("offline");
        setLive(false);
      });
      socket.on("sync", (msg: { key: string; status: string | null; changed?: number | null }) => {
        mutate("/sync/status");
        mutate("/me");
        // A finished job refreshes pages unless it reports finding nothing new.
        const nothingNew = typeof msg.changed === "number" && msg.changed === 0;
        if (msg.status && DONE.has(msg.status) && !nothingNew) refreshAll();
      });
      socket.on("changed", () => refreshAll());
    })();

    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
      setLive(false);
      socket?.disconnect();
    };
  }, [mutate]);

  return <RealtimeCtx.Provider value={status}>{children}</RealtimeCtx.Provider>;
}
