"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense } from "react";
import { AuthCard, Notice } from "@/components/auth-card";
import { AuthenticatorSetup } from "@/components/authenticator";

/** Opened from a one-time link an admin hands over after resetting someone's authenticator. */
function EnrollInner() {
  const token = useSearchParams().get("token") ?? "";
  return (
    <AuthCard
      title="Set up your authenticator again"
      subtitle="Your admin reset two-step sign-in for your account."
      footer={
        <Link href="/signin" className="font-medium text-brand hover:underline">
          Back to sign in
        </Link>
      }
    >
      {token ? <AuthenticatorSetup token={token} /> : <Notice tone="error">This link is incomplete. Ask your admin for a new one.</Notice>}
    </AuthCard>
  );
}

export default function Enroll() {
  return (
    <Suspense>
      <EnrollInner />
    </Suspense>
  );
}
