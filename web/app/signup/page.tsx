"use client";

import Link from "next/link";
import { type FormEvent, useState } from "react";
import { AuthCard, Field, Notice, Submit, postAccount } from "@/components/auth-card";
import { AuthenticatorSetup } from "@/components/authenticator";

/** Step 1: name, work email, password. Step 2: scan the QR code and confirm a code. */
export default function SignUp() {
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [token, setToken] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (password !== confirm) {
      setError("The two passwords don't match.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      setToken((await postAccount<{ enroll_token: string }>("signup", { name, email, password })).enroll_token);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <AuthCard
      title={token ? "Set up two-step sign-in" : "Create your Org+ account"}
      subtitle={token ? email : "Use your Google Workspace email. Step 1 of 2."}
      footer={
        <>
          Already have an account?{" "}
          <Link href="/signin" className="font-medium text-brand hover:underline">
            Sign in
          </Link>
        </>
      }
    >
      {token ? (
        <AuthenticatorSetup token={token} />
      ) : (
        <form onSubmit={submit} noValidate>
          {error && <Notice tone="error">{error}</Notice>}
          <Field label="Your name" autoComplete="name" required maxLength={100} value={name} onChange={(e) => setName(e.target.value)} />
          <Field label="Work email" type="email" autoComplete="username" required value={email} onChange={(e) => setEmail(e.target.value)} />
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
          <Submit busy={busy}>Continue</Submit>
          <p className="mt-3 text-xs text-ink-3">
            Next you&apos;ll scan a QR code with an authenticator app. Every sign-in needs a code from it.
          </p>
        </form>
      )}
    </AuthCard>
  );
}
