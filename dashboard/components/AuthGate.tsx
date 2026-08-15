"use client";

import { useCallback, useEffect, useState } from "react";
import LoginForm from "@/components/LoginForm";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError, apiBase, apiStartupError, fetchMe } from "@/lib/api";

export default function AuthGate({ children }: { children: React.ReactNode }) {
  const [authed, setAuthed] = useState<boolean | null>(null);
  const [offline, setOffline] = useState(false);
  const [reason, setReason] = useState<string | null>(null);

  const check = useCallback(async () => {
    // Verify the session by asking the API instead of reading the token:
    // the session cookie is httpOnly (invisible to JS), so getToken() is null
    // after a reload even when a valid cookie session exists. The request
    // includes credentials, so the API resolves the cookie and returns 200
    // for a real session, 401 otherwise.
    try {
      await fetchMe();
      setAuthed(true);
    } catch (e) {
      // A network failure (status 0) is NOT "logged out": the user may have a
      // valid session. Show an error + retry instead of dumping them on the
      // login form, which would only fail to submit anyway.
      if (e instanceof ApiError && e.status === 0) {
        // "Is it running?" is the one question the user cannot answer — the
        // desktop shell is what starts the backend. If it told us why it could
        // not, show that instead of asking them.
        setReason(apiStartupError());
        setOffline(true);
      } else {
        setAuthed(false);
      }
    }
  }, []);

  useEffect(() => {
    queueMicrotask(() => void check());
  }, [check]);

  if (authed === null) {
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
