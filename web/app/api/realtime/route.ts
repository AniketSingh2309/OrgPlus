import { type NextRequest, NextResponse } from "next/server";
import { apiToken, viewer } from "@/lib/server-auth";

export const dynamic = "force-dynamic";

/**
 * Where the browser opens the real-time socket, plus a 5-minute token for it.
 * The socket goes straight to the API (route handlers can't proxy websockets);
 * the API checks the token and our domain exactly like REST calls.
 */
export async function GET(req: NextRequest) {
  const who = await viewer(req);
  if (!who) return NextResponse.json({ detail: "sign in required" }, { status: 401 });
  return NextResponse.json(
    { url: process.env.API_PUBLIC_URL ?? "http://localhost:8000", token: await apiToken(who) },
    { headers: { "cache-control": "no-store" } },
  );
}
