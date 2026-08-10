"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Bookmark, KeyRound, LayoutDashboard, Settings, Shield, User, Users, Workflow } from "lucide-react";
import { cn } from "@/lib/utils";

const NAV_ITEMS = [
  { href: "/", label: "Dashboard", icon: LayoutDashboard },
  { href: "/profile", label: "Profile", icon: User },
  { href: "/opportunities", label: "Opportunities", icon: Workflow },
  { href: "/supervisors", label: "Supervisors", icon: Users },
  { href: "/bookmarks", label: "Bookmarks", icon: Bookmark },
  { href: "/settings", label: "Settings", icon: Settings },
  { href: "/keys", label: "API Keys", icon: KeyRound },
  { href: "/admin", label: "Admin", icon: Shield },
];

export default function Nav() {
  const pathname = usePathname();

  return (
    <header className="sticky top-0 z-40 w-full border-b bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
      <div className="mx-auto flex max-w-6xl flex-col gap-2 px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
        <Link href="/" className="flex items-center gap-2 text-base font-semibold">
          <span className="inline-flex size-7 items-center justify-center rounded-md bg-primary text-primary-foreground text-sm">
            C
          </span>
          Career Intelligence
        </Link>
        <nav
          aria-label="Main navigation"
          className="flex items-center gap-1 overflow-x-auto"
        >
          {NAV_ITEMS.map(({ href, label, icon: Icon }) => {
            const active =
              href === "/" ? pathname === "/" : pathname.startsWith(href);
            return (
              <Link
                key={href}
                href={href}
                className={cn(
                  "inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium transition-colors",
                  active
                    ? "bg-primary/10 text-primary"
                    : "text-muted-foreground hover:bg-muted hover:text-foreground",
                )}
              >
                <Icon className="size-4" aria-hidden />
                <span className="hidden sm:inline">{label}</span>
                <span className="sm:hidden">{label}</span>
              </Link>
            );
          })}
        </nav>
      </div>
    </header>
  );
}
