"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ApiError, login, registerWithInvite } from "@/lib/api";

export default function LoginForm({
  onAuth,
}: {
  onAuth?: () => void;
}) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [inviteCode, setInviteCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<"login" | "register" | null>(null);
  const [intent, setIntent] = useState<"login" | "register">("login");

  async function submit(mode: "login" | "register") {
    setIntent(mode);
    setError(null);
    setBusy(mode);
    try {
      if (mode === "register") {
        await registerWithInvite(
          email,
          password,
          inviteCode.trim() || undefined,
        );
        await login(email, password);
      } else {
        await login(email, password);
      }
      onAuth?.();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Something went wrong");
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="mx-auto mt-8 w-full max-w-sm rounded-lg border bg-card p-6 shadow-sm">
      <h2 className="mb-1 text-lg font-semibold">Sign in</h2>
      <p className="mb-4 text-sm text-muted-foreground">
        Log in or create an account to build your profile and see matches.
      </p>
      <form
        className="flex flex-col gap-4"
        onSubmit={(e) => {
          e.preventDefault();
          void submit("login");
        }}
      >
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="email">Email</Label>
          <Input
            id="email"
            type="email"
            autoComplete="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="you@example.com"
            required
          />
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="password">Password</Label>
          <Input
            id="password"
            type="password"
            minLength={8}
            autoComplete={intent === "register" ? "new-password" : "current-password"}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="At least 8 chars, incl. upper & lowercase + a digit"
            required
          />
          <p className="text-xs text-muted-foreground">
            Must be at least 8 characters with at least one uppercase letter,
            one lowercase letter, and one digit.
          </p>
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="inviteCode">Invite code (optional)</Label>
          <Input
            id="inviteCode"
            value={inviteCode}
            onChange={(e) => setInviteCode(e.target.value)}
            placeholder="Optional: enter invite code if you have one"
            autoComplete="off"
          />
        </div>
        {error && (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        )}
        <div className="flex gap-2">
          <Button
            type="submit"
            className="flex-1"
            disabled={busy !== null}
            aria-label="Log in"
          >
            {busy === "login" ? "Logging in…" : "Log in"}
          </Button>
          <Button
            type="button"
            variant="outline"
            className="flex-1"
            disabled={busy !== null}
            onClick={() => void submit("register")}
            aria-label="Create account"
          >
            {busy === "register" ? "Creating…" : "Create account"}
          </Button>
        </div>
      </form>
    </div>
  );
}
