"use client";

import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  ApiError,
  fetchAuthConfig,
  login,
  registerWithInvite,
  signInWithAccessCode,
} from "@/lib/api";

const EMAIL_KEY = "cik_email";

/** The last email that signed in on this computer, so it is not asked again. */
function readSavedEmail(): string {
  if (typeof window === "undefined") return "";
  try {
    return localStorage.getItem(EMAIL_KEY) ?? "";
  } catch {
    return "";
  }
}

function rememberEmail(value: string) {
  if (typeof window === "undefined") return;
  try {
    localStorage.setItem(EMAIL_KEY, value);
  } catch {
    // Private browsing / full storage: remembering is a nicety, never fatal.
  }
}

export default function LoginForm({
  onAuth,
}: {
  onAuth?: () => void;
}) {
  const [email, setEmail] = useState<string>(readSavedEmail);
  const [password, setPassword] = useState("");
  const [accessCode, setAccessCode] = useState("");
  const [inviteCode, setInviteCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<"login" | "register" | null>(null);
  const [intent, setIntent] = useState<"login" | "register">("login");
  // null until the API has told us. Rendering the password form first and
  // swapping it would flash a field the desktop user must not fill in.
  const [mode, setMode] = useState<"access_code" | "password" | null>(null);

  useEffect(() => {
    let live = true;
    fetchAuthConfig()
      .then((cfg) => {
        if (live) setMode(cfg.auth_mode);
      })
      // An unreachable API is AuthGate's problem to report, not this form's.
      // Falling back to the password form keeps a server deployment working
      // even if this one call fails.
      .catch(() => {
        if (live) setMode("password");
      });
    return () => {
      live = false;
    };
  }, []);

  async function submitAccessCode() {
    setError(null);
    setBusy("login");
    try {
      await signInWithAccessCode(email, accessCode.trim());
      rememberEmail(email.trim());
      onAuth?.();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Something went wrong");
    } finally {
      setBusy(null);
    }
  }

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
      rememberEmail(email.trim());
      onAuth?.();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Something went wrong");
    } finally {
      setBusy(null);
    }
  }

  if (mode === null) {
    return (
      <div className="mx-auto mt-8 w-full max-w-sm rounded-lg border bg-card p-6 shadow-sm">
        <p className="text-sm text-muted-foreground">Loading…</p>
      </div>
    );
  }

  if (mode === "access_code") {
    return (
      <div className="mx-auto mt-8 w-full max-w-sm rounded-lg border bg-card p-6 shadow-sm">
        <h2 className="mb-1 text-lg font-semibold">Welcome</h2>
        <p className="mb-4 text-sm text-muted-foreground">
          Enter your email and the access code to get started.
        </p>
        <form
          className="flex flex-col gap-4"
          onSubmit={(e) => {
            e.preventDefault();
            void submitAccessCode();
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
            <Label htmlFor="accessCode">Access code</Label>
            <Input
              id="accessCode"
              inputMode="numeric"
              autoComplete="off"
              value={accessCode}
              onChange={(e) => setAccessCode(e.target.value)}
              placeholder="The code you were given"
              required
            />
          </div>
          <p className="text-xs text-muted-foreground">
            Your email is stored on this computer so you are not asked again.
            You can sign out at any time.
          </p>
          {error && (
            <p role="alert" className="text-sm text-destructive">
              {error}
            </p>
          )}
          <Button type="submit" disabled={busy !== null} aria-label="Continue">
            {busy ? "Signing in…" : "Continue"}
          </Button>
        </form>
      </div>
    );
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
