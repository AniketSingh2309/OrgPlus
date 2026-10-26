import { type NextRequestWithAuth, withAuth } from "next-auth/middleware";
import { type NextFetchEvent, NextResponse } from "next/server";

const bypass = process.env.DEV_AUTH_BYPASS === "true";

// Scanners probe for secrets and backups (/.env, /.git/config, /backup.sql, /wp-login.php…).
// Org+ serves none of these: answer a plain 404 instead of the sign-in redirect.
const PROBE = /(^|\/)\.[^/]|\.(env|sql|bak|backup|old|orig|save|swp|zip|tar|gz|tgz|7z|rar|php\d?|aspx?|jsp|cgi|pl|ini|conf|cfg|config|log|ya?ml|toml|sh|py|rb|db|sqlite3?|pem|key|crt|p12)$|(^|\/)(wp-admin|wp-login|wp-content|wp-includes|phpmyadmin|cgi-bin|server-status)(\/|$)/i;

const requireSignIn = withAuth({ pages: { signIn: "/signin" } });

// Every page needs a signed-in Org+ account (unless the local dev bypass is on).
export default function middleware(req: NextRequestWithAuth, event: NextFetchEvent) {
  if (PROBE.test(req.nextUrl.pathname)) {
    return new NextResponse("Not found", { status: 404, headers: { "content-type": "text/plain" } });
  }
  return bypass ? NextResponse.next() : requireSignIn(req, event);
}

export const config = {
  // Pages only: API routes, sign-in, Next internals and public images stay open.
  matcher: ["/((?!api/|signin|signup|setup|enroll|forgot|_next/|favicon.ico|.*\.(?:png|svg|ico)$).*)"],
};
