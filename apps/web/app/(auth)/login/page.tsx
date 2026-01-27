"use client";

import { signIn } from "next-auth/react";
import { useSearchParams } from "next/navigation";
import { useState } from "react";

export default function LoginPage() {
  const [email, setEmail] = useState("");
  const [loading, setLoading] = useState(false);
  const search = useSearchParams();
  const check = search.get("check");

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    await signIn("email", { email, callbackUrl: "/dashboard" });
    setLoading(false);
  }

  return (
    <main style={{ maxWidth: 420 }}>
      <h1>Sign in</h1>
      <p>Enter your email to receive a magic link.</p>

      {check ? <p>Check your email for a sign-in link.</p> : null}

      <form onSubmit={onSubmit} style={{ display: "grid", gap: 12 }}>
        <input
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          placeholder="you@osu.edu"
          type="email"
          required
          style={{ padding: 10, fontSize: 14 }}
        />
        <button disabled={loading} style={{ padding: 10 }}>
          {loading ? "Sending..." : "Send magic link"}
        </button>
      </form>
    </main>
  );
}