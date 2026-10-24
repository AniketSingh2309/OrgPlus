"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { type FormEvent, Suspense, useEffect, useState } from "react";
import { AuthCard, Field, Notice, Submit, postAccount } from "@/components/auth-card";

type LinkInfo = { email: string; purpose: "reset" | "enroll" };

/** Opened from the emailed password-reset link. */
function SetupInner() {
  const params = useSearchParams();
  const router = useRouter();
  const token = params.get("token") ?? "";
  const [info, setInfo] = useState<LinkInfo | null>(null);
  const [linkError, setLinkError] = useState<string | null>(null);
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!token) {
      setLinkError("This link is incomplete. Open it again from the email.");
      return;
    }
    postAccount<LinkInfo>("link", { token }).then(setInfo, (err: Error) => setLinkError(err.message));
  }, [token]);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (password !== confirm) {
      setError("The two passwords don't match.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const r = await postAccount<{ email: string }>("password", { token, password });
      router.replace(`/signin?set=1&email=${encodeURIComponent(r.email)}`);
    } catch (err) {
      setError((err as Error).message);
      setBusy(false);
    }
  }

  return (
    <AuthCard
      title="Choose a new password"
      subtitle={info ? info.email : undefined}
      footer={
        <Link href="/signin" className="font-medium text-brand hover:underline">
          Back to sign in
        </Link>
      }
    >
      {linkError ? (
        <>
          <Notice tone="error">{linkError}</Notice>
          <Link href="/forgot" className="text-sm font-medium text-brand hover:underline">
            Send me a new link
          </Link>
        </>
      ) : !info ? (
        <p className="text-center text-sm text-ink-3">Checking your link…</p>
      ) : (
        <form onSubmit={submit} noValidate>
          {error && <Notice tone="error">{error}</Notice>}
          {/* Lets password managers save the right username. */}
          <input type="hidden" name="username" autoComplete="username" value={info.email} readOnly />
          <Field
            label="Password"
            type="password"
            autoComplete="new-password"
            required
            minLength={10}
            maxLength={128}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            hint="At least 10 characters. A short phrase is easiest to remember."
          />
          <Field label="Confirm password" type="password" autoComplete="new-password" required value={confirm} onChange={(e) => setConfirm(e.target.value)} />
          <Submit busy={busy}>Save new password</Submit>
          <p className="mt-3 text-xs text-ink-3">
            Saving signs you out everywhere else. You&apos;ll still need your authenticator code to sign in.
          </p>
        </form>
      )}
    </AuthCard>
  );
}

export default function Setup() {
  return (
    <Suspense>
      <SetupInner />
    </Suspense>
  );
}
