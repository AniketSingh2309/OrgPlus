import { SignJWT } from "jose";
import { getToken } from "next-auth/jwt";
import type { NextRequest } from "next/server";
import { devBypass } from "@/lib/auth";

export type Who = { email: string; name: string; sv?: number };

/** Short-lived HS256 token the FastAPI backend verifies (audience "orgpulse-api"). */
export async function apiToken(who: Who): Promise<string> {
  const secret = new TextEncoder().encode(process.env.NEXTAUTH_SECRET ?? "");
  return new SignJWT({ email: who.email, name: who.name, ...(who.sv !== undefined ? { sv: who.sv } : {}) })
    .setProtectedHeader({ alg: "HS256" })
    .setAudience("orgpulse-api")
    .setIssuedAt()
    .setExpirationTime("5m")
    .sign(secret);
}

/** The signed-in viewer (or the dev user when DEV_AUTH_BYPASS is on), else null. */
export async function viewer(req: NextRequest): Promise<Who | null> {
  if (devBypass) {
    const email = process.env.DEV_USER_EMAIL ?? `dev@${process.env.ALLOWED_DOMAIN}`;
    return { email, name: "Developer" };
  }
  const token = await getToken({ req, secret: process.env.NEXTAUTH_SECRET });
  if (!token?.email) return null;
  return { email: token.email, name: token.name ?? token.email, sv: token.sv as number | undefined };
}

/** The browser's IP, passed to the API for its sign-up / password-link rate limits. */
export function clientIp(req: NextRequest): string {
  // Next 15 has no req.ip: the proxy in front (Caddy / nginx) sets X-Forwarded-For.
  return (req.headers.get("x-forwarded-for") ?? "").split(",")[0].trim() || (req.headers.get("x-real-ip") ?? "");
}
