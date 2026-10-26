/** @type {import('next').NextConfig} */

const isDev = process.env.NODE_ENV !== "production";

// The live-update socket may be on another origin than the web app (API_PUBLIC_URL).
function socketOrigins() {
  try {
    const u = new URL(process.env.API_PUBLIC_URL ?? "");
    const ws = u.protocol === "https:" ? "wss:" : "ws:";
    return [u.origin, `${ws}//${u.host}`];
  } catch {
    return [];
  }
}

// Content Security Policy. Everything is served from this site (the font is self-hosted
// by next/font); only profile photos come from Google. Next.js injects small inline
// scripts, hence 'unsafe-inline' for scripts; dev mode also needs 'unsafe-eval'.
const csp = [
  "default-src 'self'",
  `script-src 'self' 'unsafe-inline'${isDev ? " 'unsafe-eval'" : ""}`,
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data: blob: https://*.googleusercontent.com https://*.google.com",
  "font-src 'self' data:",
  `connect-src 'self' ${socketOrigins().join(" ")}${isDev ? " ws: http://localhost:* http://127.0.0.1:*" : ""}`.trim(),
  "frame-ancestors 'none'",
  "frame-src 'none'",
  "object-src 'none'",
  "base-uri 'self'",
  "form-action 'self'",
  ...(isDev ? [] : ["upgrade-insecure-requests"]),
].join("; ");

const securityHeaders = [
  { key: "Content-Security-Policy", value: csp },
  // Browsers ignore HSTS over plain http, so this is harmless in local development.
  { key: "Strict-Transport-Security", value: "max-age=31536000; includeSubDomains" },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=(), usb=(), payment=(), interest-cohort=()" },
  { key: "Cross-Origin-Opener-Policy", value: "same-origin" },
];

const nextConfig = {
  reactStrictMode: true,
  // Don't advertise the framework (no "X-Powered-By: Next.js").
  poweredByHeader: false,
  // Browser calls to /api/* go through app/api/[...path]/route.ts, which adds the
  // signed session token the FastAPI backend expects.
  async headers() {
    return [{ source: "/:path*", headers: securityHeaders }];
  },
};

export default nextConfig;
