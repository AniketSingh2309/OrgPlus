"use client";

import Link from "next/link";
import { type FormEvent, useEffect, useState } from "react";
import { Field, Notice, Submit, postAccount } from "./auth-card";

type Setup = { email: string; secret: string; uri: string; qr: string };
type Done = { email: string; status: "active" };

/** Scan the QR code with an authenticator app, then confirm with its first code. */
export function AuthenticatorSetup({ token }: { token: string }) {
  const [setup, setSetup] = useState<Setup | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState<Done | null>(null);
  const [showKey, setShowKey] = useState(false);

  useEffect(() => {
    postAccount<Setup>("mfa/setup", { token }).then(setSetup, (err: Error) => setLoadError(err.message));
  }, [token]);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      setDone(await postAccount<Done>("mfa/confirm", { token, code }));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  if (loadError) {
    return (
      <>
        <Notice tone="error">{loadError}</Notice>
        <Link href="/signup" className="text-sm font-medium text-brand hover:underline">
          Start again
        </Link>
      </>
    );
  }
  if (done) {
    return (
      <>
        <Notice tone="ok">Two-step sign-in is on. Sign in with your password and a code from the app.</Notice>
        <Link
          href={`/signin?email=${encodeURIComponent(done.email)}`}
          className="block w-full rounded-lg bg-brand px-4 py-2 text-center text-sm font-medium text-on-brand hover:bg-brand-strong"
        >
          Sign in
        </Link>
      </>
    );
  }
  if (!setup) return <p className="text-center text-sm text-ink-3">Preparing your QR code…</p>;

  return (
    <form onSubmit={submit} noValidate>
      <ol className="mb-4 list-decimal space-y-1 pl-5 text-left text-sm text-ink-2">
        <li>Open an authenticator app (Google Authenticator, Microsoft Authenticator, Authy, 1Password…).</li>
        <li>Add an account and scan this code.</li>
        <li>Type the 6-digit code the app shows.</li>
      </ol>
      <div className="mx-auto mb-3 w-fit rounded-lg bg-white p-2">
        {/* eslint-disable-next-line @next/next/no-img-element -- generated locally as a data URI */}
        <img src={setup.qr} alt={`QR code to add Org+ (${setup.email}) to an authenticator app`} width={200} height={200} />
      </div>
      <div className="mb-4 text-center">
        <button type="button" onClick={() => setShowKey(!showKey)} className="text-xs font-medium text-brand hover:underline">
          {showKey ? "Hide the key" : "Can't scan? Enter a key instead"}
        </button>
        {showKey && (
          <code className="mt-2 block select-all break-all rounded bg-surface-2 px-2 py-1 font-mono text-sm tracking-wider text-ink">
            {setup.secret.match(/.{1,4}/g)?.join(" ")}
          </code>
        )}
      </div>
      {error && <Notice tone="error">{error}</Notice>}
      <Field
        label="6-digit code"
        inputMode="numeric"
        autoComplete="one-time-code"
        pattern="[0-9]*"
        maxLength={7}
        required
        value={code}
        onChange={(e) => setCode(e.target.value.replace(/[^0-9]/g, ""))}
      />
      <Submit busy={busy}>Turn on two-step sign-in</Submit>
    </form>
  );
}
