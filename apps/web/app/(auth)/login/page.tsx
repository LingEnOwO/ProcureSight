"use client";

import { signIn } from "next-auth/react";
import { useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";

function LoginForm() {
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
    <div className="login-page">
      <div className="login-card">
        <div className="login-brand">
          <div className="login-brand-icon">PS</div>
          <span className="login-brand-name">ProcureSight</span>
        </div>

        {check ? (
          <div className="alert-banner success" style={{ marginBottom: "1.5rem" }}>
            <div className="alert-title">Check your email</div>
            <div style={{ fontSize: "0.8125rem" }}>
              We sent a sign-in link to <strong>{email || "your email"}</strong>.
            </div>
          </div>
        ) : (
          <>
            <h1 className="login-heading">Welcome back</h1>
            <p className="login-subheading">
              Enter your email to receive a magic sign-in link.
            </p>
          </>
        )}

        <form onSubmit={onSubmit} style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
          <div className="form-group" style={{ margin: 0 }}>
            <label htmlFor="email" className="form-label">
              Email address
            </label>
            <input
              id="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="you@company.com"
              type="email"
              required
              disabled={loading}
              className="form-input"
            />
          </div>

          <button
            type="submit"
            disabled={loading}
            className="btn-primary"
            style={{ justifyContent: "center", padding: "0.625rem 1rem", fontSize: "0.9375rem" }}
          >
            {loading && <span className="spinner" />}
            {loading ? "Sending link..." : "Send magic link"}
          </button>
        </form>

        <p
          style={{
            marginTop: "1.5rem",
            fontSize: "0.75rem",
            color: "var(--text-muted)",
            textAlign: "center",
            lineHeight: 1.5,
          }}
        >
          A sign-in link will be sent to your email. No password required.
        </p>
      </div>
    </div>
  );
}

export default function LoginPage() {
  return (
    <Suspense fallback={<div className="login-page"><div style={{ color: "var(--text-muted)" }}>Loading...</div></div>}>
      <LoginForm />
    </Suspense>
  );
}
