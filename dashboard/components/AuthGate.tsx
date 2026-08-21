"use client";

import { useCallback, useEffect, useState } from "react";
import LoginForm from "@/components/LoginForm";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError, apiBase, apiStartupError, fetchMe } from "@/lib/api";
import { isDesktop } from "@/lib/desktop";

/**
 * True while the desktop shell is still bringing the backend up.
 *
 * The shell publishes `__ASTRA_API_READY__ = false` with no error for as long as
 * the sidecar is starting, and only fills in `__ASTRA_API_ERROR__` once it has
 * genuinely given up. A PyInstaller onefile needs seconds to unpack before
 * uvicorn binds, so the first `fetchMe()` on a cold start always loses that
 * race — without this the app greeted every launch with "Cannot reach the API
 * server", an error the user could only clear by clicking Retry.
 *
 * Read off `window` rather than through lib/api so the web build and the test
 * mocks are untouched: neither defines these globals, `=== false` is therefore
 * never true there, and the old behaviour stands.
 */
function backendStarting(): boolean {
  if (typeof window === "undefined") return false;
  const w = window as unknown as {
    __ASTRA_API_READY__?: boolean;
    __ASTRA_API_ERROR__?: string | null;
  };
  // The shell has genuinely given up: that is an error, not a wait.
  if (w.__ASTRA_API_ERROR__) return false;
  // Explicitly still coming up.
  if (w.__ASTRA_API_READY__ === false) return true;
  // NOT YET PUBLISHED is also "still coming up", and used to be read as a
  // failure. The shell sets these globals from `on_page_load`, whose eval is
  // asynchronous, so on a cold start this component can mount and fire its
  // first fetchMe() BEFORE the eval lands. The flag is then `undefined`, the
  // old `=== false` test was false, and the gate went straight to the terminal
  // "Cannot reach the API server" screen — which never retries, so a backend
  // that came up two seconds later never cleared it. That is the sticky error
  // on every cold launch: the backend was healthy the whole time.
  //
  // Gated on isDesktop() so the web build is untouched: there these globals are
  // never defined and an unreachable API must still report itself immediately.
  // isDesktop() is safe to consult this early because Tauri v2 defines its own
  // `window.isTauri` marker before any page script runs, independently of our
  // injection.
  return isDesktop() && w.__ASTRA_API_READY__ === undefined;
}

export default function AuthGate({ children }: { children: React.ReactNode }) {
  const [authed, setAuthed] = useState<boolean | null>(null);
  const [offline, setOffline] = useState(false);
  const [reason, setReason] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const [tick, setTick] = useState(0);

  const check = useCallback(async () => {
    // Verify the session by asking the API instead of reading the token:
    // the session cookie is httpOnly (invisible to JS), so getToken() is null
    // after a reload even when a valid cookie session exists. The request
    // includes credentials, so the API resolves the cookie and returns 200
    // for a real session, 401 otherwise.
    try {
      await fetchMe();
      setStarting(false);
      setAuthed(true);
    } catch (e) {
      // A network failure (status 0) is NOT "logged out": the user may have a
      // valid session. Show an error + retry instead of dumping them on the
      // login form, which would only fail to submit anyway.
      if (e instanceof ApiError && e.status === 0) {
        // Still booting is not yet a failure — say so and try again shortly.
        if (backendStarting()) {
          setStarting(true);
          return;
        }
        setStarting(false);
        // "Is it running?" is the one question the user cannot answer — the
        // desktop shell is what starts the backend. If it told us why it could
        // not, show that instead of asking them.
        setReason(apiStartupError());
        setOffline(true);
      } else {
        // A real HTTP answer (401, 422, 500...) means the backend is up and
        // talking, so stop any "still starting" retry loop. Without this the
        // 1s re-check kept firing forever behind the login form once `starting`
        // had been set on a cold start — measured at ~50 requests to
        // /api/auth/me in 20 seconds, every one of them a 401.
        setStarting(false);
        setAuthed(false);
      }
    }
  }, []);

  useEffect(() => {
    queueMicrotask(() => void check());
  }, [check, tick]);

  // Re-check on a timer for as long as the shell reports the backend is on its
  // way. The shell gives up after its own health budget and publishes a reason,
  // which the next check turns into the error screen.
  useEffect(() => {
    if (!starting) return;
    const t = setTimeout(() => setTick((n) => n + 1), 1000);
    return () => clearTimeout(t);
  }, [starting, tick]);

  if (authed === null) {
    if (starting) {
      return (
        <div
          className="mx-auto mt-16 flex max-w-xl flex-col items-center gap-2 p-6 text-center"
          data-testid="api-starting"
        >
          <p className="text-sm">Starting the backend…</p>
          <p className="text-xs text-muted-foreground">
            The first launch takes a few seconds while the API unpacks.
          </p>
        </div>
      );
    }
    if (offline) {
      return (
        <div
          className="mx-auto mt-16 flex max-w-xl flex-col items-center gap-3 p-6 text-center"
          data-testid="api-offline"
        >
          <p className="text-sm text-destructive">
            {reason
              ? "The backend could not be started."
              : "Cannot reach the API server. Is it running?"}
          </p>
          {reason && (
            <pre
              className="max-h-64 w-full overflow-auto whitespace-pre-wrap rounded-md border bg-muted/40 p-3 text-left text-xs"
              data-testid="api-offline-reason"
            >
              {reason}
            </pre>
          )}
          <p className="text-xs text-muted-foreground">
            Trying <code className="font-mono">{apiBase()}</code>
          </p>
          <Button variant="outline" onClick={() => void check()}>
            Retry
          </Button>
        </div>
      );
    }
    return (
      <div className="mx-auto mt-16 flex w-full max-w-sm flex-col gap-3">
        <Skeleton className="h-5 w-2/3" />
        <Skeleton className="h-10 w-full" />
        <Skeleton className="h-10 w-full" />
        <Skeleton className="h-10 w-full" />
      </div>
    );
  }

  if (!authed) return <LoginForm onAuth={() => setAuthed(true)} />;

  return <>{children}</>;
}
