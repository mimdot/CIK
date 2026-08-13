"use client";

import { useCallback, useEffect, useState } from "react";
import LoginForm from "@/components/LoginForm";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError, fetchMe } from "@/lib/api";

export default function AuthGate({ children }: { children: React.ReactNode }) {
  const [authed, setAuthed] = useState<boolean | null>(null);
  const [offline, setOffline] = useState(false);

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
        <div className="mx-auto mt-16 flex max-w-sm flex-col items-center gap-3 p-6 text-center">
          <p className="text-sm text-destructive">
            Cannot reach the API server. Is it running?
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
