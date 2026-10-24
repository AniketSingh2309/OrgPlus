"use client";

import Link from "next/link";
import { signIn } from "next-auth/react";
import { useRouter, useSearchParams } from "next/navigation";
import { type FormEvent, Suspense, useState } from "react";
import { AuthCard, Field, Notice, Submit } from "@/components/auth-card";

function SignInInner() {
  const params = useSearchParams();
  const router = useRouter();
  const [email, setEmail] = useState(params.get("email") ?? "");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(params.get("expired") ? "Your session ended. Sign in again." : null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    const res = await signIn("credentials", { email, password, code, redirect: false });
    setBusy(false);
    if (res?.ok && !res.error) {
      const next = params.get("callbackUrl");
      // Only same-site paths: never bounce a fresh session to another website.
      router.replace(next && next.startsWith("/") && !next.startsWith("//") ? next : "/");
      router.refresh();
    } else {
      setError(res?.error && res.error !== "CredentialsSignin" ? res.error : "Wrong email, password or authenticator code.");
      setCode(""); // a code is single-use: always type the current one
    }
  }

  return (
    <AuthCard
      title="Sign in"
      subtitle="Your organisation's Org+ dashboard."
      footer={
        <>
          New to Org+?{" "}
          <Link href="/signup" className="font-medium text-brand hover:underline">
            Create an account
          </Link>
        </>
      }
    >
      {params.get("set") && <Notice tone="ok">Password saved. Sign in with it now.</Notice>}
      {error && <Notice tone="error">{error}</Notice>}
      <form onSubmit={submit} noValidate>
        <Field label="Work email" type="email" autoComplete="username" required value={email} onChange={(e) => setEmail(e.target.value)} />
        <Field label="Password" type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} />
        <Field
          label="Authenticator code"
          inputMode="numeric"
          autoComplete="one-time-code"
          pattern="[0-9]*"
          maxLength={7}
          required
          value={code}
          onChange={(e) => setCode(e.target.value.replace(/[^0-9]/g, ""))}
          hint="The 6-digit code from your authenticator app."
        />
        <div className="-mt-1 mb-2 text-right">
          <Link href={`/forgot${email ? `?email=${encodeURIComponent(email)}` : ""}`} className="text-xs font-medium text-brand hover:underline">
            Forgot password?
          </Link>
        </div>
        <Submit busy={busy}>Sign in</Submit>
      </form>
    </AuthCard>
  );
}

export default function SignIn() {
  return (
    <Suspense>
      <SignInInner />
    </Suspense>
  );
}
