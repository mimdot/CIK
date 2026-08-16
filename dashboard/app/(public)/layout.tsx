import CookieBanner from "@/components/CookieBanner";
import { SiteFooter } from "@/components/SiteFooter";
import Link from "next/link";

const PUBLIC_LINKS = [
  { href: "/landing", label: "About" },
  { href: "/privacy", label: "Privacy" },
  { href: "/terms", label: "Terms" },
];

export default function PublicLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <div className="flex min-h-dvh flex-col">
      <header className="sticky top-0 z-40 w-full border-b bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-4 py-3">
          <Link
            href="/landing"
            className="flex items-center gap-2 text-base font-semibold"
          >
            <span className="inline-flex size-7 items-center justify-center rounded-md bg-primary text-primary-foreground text-sm">
              C
            </span>
            Astra
          </Link>
          <nav className="flex items-center gap-4 text-sm text-muted-foreground">
            {PUBLIC_LINKS.map(({ href, label }) => (
              <Link key={href} href={href} className="hover:text-foreground">
                {label}
              </Link>
            ))}
            <Link
              href="/"
              className="rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground hover:bg-primary/90"
            >
              Sign in
            </Link>
          </nav>
        </div>
      </header>
      <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-10">
        {children}
      </main>
      <SiteFooter />
      <CookieBanner />
    </div>
  );
}
