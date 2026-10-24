import type { NextAuthOptions } from "next-auth";
import CredentialsProvider from "next-auth/providers/credentials";

export const devBypass = process.env.DEV_AUTH_BYPASS === "true";

const API = process.env.API_INTERNAL_URL ?? "http://localhost:8000";

/** The browser's IP as seen by this server, for the API's sign-in rate limits. */
function clientIp(headers: Record<string, unknown> | undefined): string {
  const fwd = String(headers?.["x-forwarded-for"] ?? "").split(",")[0].trim();
  return fwd || String(headers?.["x-real-ip"] ?? "");
}

/**
 * Viewer sign-in: Org+ accounts (work email + password + authenticator code). The API
 * checks all three (Argon2id, TOTP, lockout, rate limits) and that the person may open
 * their organisation;
 * the session then carries the account's session version, so a password change signs
 * out every other session.
 */
export const authOptions: NextAuthOptions = {
  providers: [
    CredentialsProvider({
      name: "Org+ account",
      credentials: { email: { type: "email" }, password: { type: "password" }, code: { type: "text" } },
      async authorize(credentials, req) {
        const res = await fetch(`${API}/api/account/login`, {
          method: "POST",
          headers: { "content-type": "application/json", "x-orgplus-client-ip": clientIp(req?.headers) },
          body: JSON.stringify({
            email: credentials?.email ?? "",
            password: credentials?.password ?? "",
            code: credentials?.code ?? "",
          }),
          cache: "no-store",
        });
        const body = await res.json().catch(() => ({}));
        if (!res.ok) {
          // Shown on the sign-in page as is: the API's messages are written for people.
          throw new Error(body?.detail?.message ?? "Sign-in failed. Try again.");
        }
        return { id: body.email, email: body.email, name: body.name, sv: body.sv };
      },
    }),
  ],
  session: { strategy: "jwt", maxAge: 8 * 60 * 60 },
  pages: { signIn: "/signin", error: "/signin" },
  callbacks: {
    async jwt({ token, user }) {
      if (user) token.sv = (user as { sv?: number }).sv;
      return token;
    },
    async session({ session, token }) {
      return { ...session, sv: token.sv };
    },
  },
};
