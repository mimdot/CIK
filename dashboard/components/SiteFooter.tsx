import Link from "next/link";
import { BRAND } from "@/lib/brand";

export const GITHUB_URL = "https://github.com/mimdot";
export const CONTACT_EMAIL = "mr.nasirzadeh@live.com";

/**
 * Shared footer — rendered on the dashboard and on the public pages, so the
 * project's author and contact are reachable from every surface, desktop app
 * included (the desktop shell serves this same static export).
 */
export function SiteFooter() {
  return (
    <footer className="mt-auto border-t">
      <div className="mx-auto flex max-w-6xl flex-col gap-3 px-4 py-6 text-sm text-muted-foreground sm:flex-row sm:items-center sm:justify-between">
        <p>{BRAND.topLine}</p>
        <nav aria-label="About and contact" className="flex flex-wrap gap-4">
          <a
            href={GITHUB_URL}
            target="_blank"
            rel="noopener noreferrer"
            className="font-medium underline-offset-4 hover:text-foreground hover:underline"
          >
            GitHub
          </a>
          <a
            href={`mailto:${CONTACT_EMAIL}`}
            className="font-medium underline-offset-4 hover:text-foreground hover:underline"
          >
            {CONTACT_EMAIL}
          </a>
          <Link
            href="/about"
            className="underline-offset-4 hover:text-foreground hover:underline"
          >
            About
          </Link>
          <Link
            href="/privacy"
            className="underline-offset-4 hover:text-foreground hover:underline"
          >
            Privacy
          </Link>
        </nav>
      </div>
    </footer>
  );
}
