"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { type FormEvent, Suspense, useState } from "react";
import { AuthCard, Field, Notice, Submit, postAccount } from "@/components/auth-card";

function ForgotInner() {
  const params = useSearchParams();
  const [email, setEmail] = useState(params.get("email") ?? "");
  const [sent, setSent] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      setSent((await postAccount<{ message: string }>("forgot", { email })).message);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <AuthCard
      title="Reset your password"
      subtitle="We'll email you a link to choose a new one."
      footer={
        <Link href="/signin" className="font-medium text-brand hover:underline">
          Back to sign in
        </Link>
      }
    >
      {sent ? (
        <Notice tone="ok">{sent}</Notice>
      ) : (
        <form onSubmit={submit} noValidate>
          {error && <Notice tone="error">{error}</Notice>}
          <Field label="Work email" type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
          <Submit busy={busy}>Email me a link</Submit>
        </form>
      )}
    </AuthCard>
  );
}

export default function Forgot() {
  return (
    <Suspense>
      <ForgotInner />
    </Suspense>
  );
}
