import { type NextRequest, NextResponse } from "next/server";
import { apiToken, clientIp, viewer } from "@/lib/server-auth";

export const dynamic = "force-dynamic";

const API = process.env.API_INTERNAL_URL ?? "http://localhost:8000";
const PASS_HEADERS = ["content-type", "content-disposition"];

async function proxy(req: NextRequest, { params }: { params: { path: string[] } }) {
  // Account endpoints (sign-up, authenticator setup, password links) are public;
  // everything else needs a session. Sign-in itself only goes through NextAuth.
  const isPublic = params.path[0] === "account" && req.method === "POST" && params.path[1] !== "login";
  const who = isPublic ? null : await viewer(req);
  if (!isPublic && !who) return NextResponse.json({ detail: "sign in required" }, { status: 401 });

  const url = `${API}/api/${params.path.map(encodeURIComponent).join("/")}${req.nextUrl.search}`;
  const headers: Record<string, string> = who
    ? { authorization: `Bearer ${await apiToken(who)}` }
    : { "x-orgplus-client-ip": clientIp(req) };
  const type = req.headers.get("content-type");
  if (type) headers["content-type"] = type;

  const res = await fetch(url, {
    method: req.method,
    headers,
    body: ["GET", "HEAD"].includes(req.method) ? undefined : await req.arrayBuffer(),
    cache: "no-store",
  });
  const out = new Headers();
  for (const h of PASS_HEADERS) {
    const v = res.headers.get(h);
    if (v) out.set(h, v);
  }
  return new NextResponse(res.body, { status: res.status, headers: out });
}

export { proxy as GET, proxy as POST, proxy as PUT, proxy as DELETE };
