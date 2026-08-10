"use client";

import { useEffect, useState } from "react";
import LoginForm from "@/components/LoginForm";
import { getToken } from "@/lib/api";

export default function AuthGate({ children }: { children: React.ReactNode }) {
  const [authed, setAuthed] = useState<boolean | null>(null);

  useEffect(() => {
    // Check for a session on mount via the token (read from the cookie /
    // in-memory session, not localStorage). Safe because getToken() returns
    // null on the server, so the initial render stays consistent.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setAuthed(Boolean(getToken()));
  }, []);

  if (authed === null) return null;

  if (!authed) return <LoginForm onAuth={() => setAuthed(true)} />;

  return <>{children}</>;
}
