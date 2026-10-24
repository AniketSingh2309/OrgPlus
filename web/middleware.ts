import { withAuth } from "next-auth/middleware";
import { NextResponse } from "next/server";

const bypass = process.env.DEV_AUTH_BYPASS === "true";

// Every page needs a signed-in Org+ account (unless the local dev bypass is on).
export default bypass
  ? () => NextResponse.next()
  : withAuth({ pages: { signIn: "/signin" } });

export const config = {
  // Pages only: API routes, sign-in, Next internals and public images stay open.
  matcher: ["/((?!api/|signin|signup|setup|enroll|forgot|_next/|favicon.ico|.*\.(?:png|svg|ico)$).*)"],
};
