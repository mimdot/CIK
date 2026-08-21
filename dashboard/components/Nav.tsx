"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState, useSyncExternalStore } from "react";
import AstraMark from "@/components/AstraMark";
import { BRAND } from "@/lib/brand";
import { fetchMe, logout } from "@/lib/api";
import { Bookmark, Heart, KeyRound, LayoutDashboard, LogOut, Power, Settings, Shield, User, Users, Workflow } from "lucide-react";
import { isDesktop, openExternal, quitApp } from "@/lib/desktop";
import { cn } from "@/lib/utils";

/** Nothing changes `isDesktop()` after load, so there is nothing to subscribe
 *  to. Defined at module scope so the reference is stable across renders. */
const subscribeNever = () => () => {};

/** Where "Support" goes. Funds the servers that will host Astra online, free. */
const SUPPORT_URL = "https://donofa.ir/mimdot";

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
  // Whether we are inside the desktop shell, read the way React wants a value
  // that differs between server and client to be read.
  //
  // Calling isDesktop() during render would hydrate one tree on the server and
  // a different one on the client. Setting it from an effect fixes that but
  // trades it for a synchronous setState inside an effect — a cascading render,
  // and what react-hooks/set-state-in-effect exists to catch.
  // useSyncExternalStore is the construct for exactly this: a server snapshot,
  // a client snapshot, and no extra render pass. Nothing ever changes it after
  // load, so the subscribe function has nothing to do.
  const desktop = useSyncExternalStore(
    subscribeNever,
    () => isDesktop(),
    () => false,
  );

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
          {/* Support the project. Opens in the real browser on desktop — a
              payment page inside a webview with no address bar is something a
              user cannot verify, and should not be asked to trust. */}
          <button
            type="button"
            onClick={() => void openExternal(SUPPORT_URL)}
            className="inline-flex shrink-0 items-center gap-1 whitespace-nowrap border-b-2 border-transparent px-2 py-1.5 text-[11px] uppercase tracking-[0.08em] text-muted-foreground transition-colors hover:text-foreground"
            title="Support Astra — helps fund the servers that will make it free for everyone"
          >
            <Heart className="size-4" aria-hidden />
            <span>Support</span>
          </button>
          {/* Sign out is WEB ONLY. On the desktop the app is a single-user
              local tool: there is nobody to sign out from, the access code is
              a front door rather than a boundary, and the shell mints a new
              signing key every launch anyway — so the button offered nothing
              but a way to lock yourself out of your own machine. */}
          {!desktop && (
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
          )}
          {/* Quit, desktop only. Signing out is not the same as closing the
              app, and closing the window is the window manager's business —
              neither is a deliberate "stop Astra". This one goes through the
              shell, which stops the backend BEFORE exiting, so no API process
              is left holding the port for the next launch to trip over. */}
          {desktop && (
            <button
              type="button"
              onClick={() => void quitApp()}
              className="inline-flex shrink-0 items-center gap-1 whitespace-nowrap border-b-2 border-transparent px-2 py-1.5 text-[11px] uppercase tracking-[0.08em] text-muted-foreground transition-colors hover:text-destructive"
              title="Close Astra and stop its backend"
            >
              <Power className="size-4" aria-hidden />
              <span>Quit</span>
            </button>
          )}
        </nav>
      </div>
    </header>
  );
}
