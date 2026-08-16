"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import AstraMark from "@/components/AstraMark";
import { BRAND } from "@/lib/brand";
import { fetchMe, logout } from "@/lib/api";
import { Bookmark, KeyRound, LayoutDashboard, LogOut, Settings, Shield, User, Users, Workflow } from "lucide-react";
import { cn } from "@/lib/utils";

// `adminOnly` pages are operator tooling, not features an ordinary user needs.
// The backend already answers 403 on those routes; hiding them stops the app
// advertising things most people cannot use and should not have to think about.
const NAV_ITEMS = [
  { href: "/", label: "Dashboard", icon: LayoutDashboard },
  { href: "/profile", label: "Profile", icon: User },
  { href: "/opportunities", label: "Opportunities", icon: Workflow },
  { href: "/supervisors", label: "Supervisors", icon: Users },
  { href: "/bookmarks", label: "Bookmarks", icon: Bookmark },
  { href: "/settings", label: "Settings", icon: Settings },
  { href: "/keys", label: "API Keys", icon: KeyRound, adminOnly: true },
  { href: "/admin", label: "Admin", icon: Shield, adminOnly: true },
];

export default function Nav() {
  const pathname = usePathname();
  const [isAdmin, setIsAdmin] = useState(false);

  useEffect(() => {
    fetchMe()
      .then((me) => setIsAdmin(me.role === "admin"))
      .catch(() => setIsAdmin(false));
  }, []);

  const items = NAV_ITEMS.filter((item) => !item.adminOnly || isAdmin);

  return (
    <header className="sticky top-0 z-40 w-full border-b bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
      <div className="mx-auto flex max-w-6xl flex-col gap-2 px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
        {/* Lockup B — mark + wordmark + descriptor, per the identity spec.
            Wordmark is uppercase in the heading face at -0.02em; the descriptor
            sits under it at label size. Nothing here is rounded. */}
        <Link href="/" className="flex items-center gap-3">
          <AstraMark size={28} />
          <span className="flex flex-col gap-0.5">
            <span className="font-heading text-xl font-extrabold uppercase leading-none tracking-[-0.02em]">
              {BRAND.name}
            </span>
            <span className="whitespace-nowrap text-[10px] uppercase tracking-[0.2em] text-muted-foreground">
              {BRAND.descriptorLabel}
            </span>
          </span>
        </Link>
        <nav
          aria-label="Main navigation"
          className="flex items-center gap-1 overflow-x-auto"
        >
          {items.map(({ href, label, icon: Icon }) => {
            const active =
              href === "/" ? pathname === "/" : pathname.startsWith(href);
            return (
              <Link
                key={href}
                href={href}
                className={cn(
                  // Dashboard header, per the spec: labels at 12px / 0.12em
                  // uppercase, the active one UNDERLINED in accent rather than
                  // filled with it. A filled pill would spend the view's one
                  // permitted accent on navigation, leaving none for the
                  // primary action — which is where it belongs.
                  "inline-flex shrink-0 items-center gap-1 border-b-2 px-2 py-1.5",
                  "whitespace-nowrap text-[11px] uppercase tracking-[0.08em] transition-colors",
                  active
                    ? "border-primary font-bold text-foreground"
                    : "border-transparent text-muted-foreground hover:text-foreground",
                )}
              >
                <Icon className="size-4" aria-hidden />
                {/* One span: the two responsive variants rendered the SAME
                    text, so the only effect was duplicating every nav label
                    for screen readers. */}
                <span>{label}</span>
              </Link>
            );
          })}
          {/* Sign out lived nowhere before this. The session cookie is
              httpOnly, so a user who signed in with the wrong email had no way
              to get back out short of waiting for the token to expire. */}
          <button
            type="button"
            onClick={() => {
              void logout().finally(() => window.location.assign("/"));
            }}
            className="inline-flex shrink-0 items-center gap-1 whitespace-nowrap border-b-2 border-transparent px-2 py-1.5 text-[11px] uppercase tracking-[0.08em] text-muted-foreground transition-colors hover:text-foreground"
          >
            <LogOut className="size-4" aria-hidden />
            <span>Sign out</span>
          </button>
        </nav>
      </div>
    </header>
  );
}
