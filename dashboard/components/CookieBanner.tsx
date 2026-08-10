"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";

const CONSENT_KEY = "cik_cookie_consent";

export default function CookieBanner() {
  const [visible, setVisible] = useState(
    () =>
      typeof window !== "undefined" &&
      localStorage.getItem(CONSENT_KEY) === null,
  );

  function accept() {
    localStorage.setItem(CONSENT_KEY, "accepted");
    setVisible(false);
  }

  if (!visible) return null;

  return (
    <div
      role="region"
      aria-label="Cookie consent"
      className="fixed inset-x-0 bottom-0 z-50 border-t bg-popover p-4 shadow-lg"
    >
      <div className="mx-auto flex max-w-6xl flex-col items-start gap-3 sm:flex-row sm:items-center sm:justify-between">
        <p className="text-sm text-muted-foreground">
          This site only sets functional cookies (your session) and stores
          nothing for tracking or advertising. Read our{" "}
          <a href="/privacy" className="underline">
            Privacy Policy
          </a>
          .
        </p>
        <Button size="sm" onClick={accept}>
          Accept
        </Button>
      </div>
    </div>
  );
}
