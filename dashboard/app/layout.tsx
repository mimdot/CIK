import type { Metadata } from "next";
import { Archivo } from "next/font/google";
import ExternalLinks from "@/components/ExternalLinks";
import { ToastProvider } from "@/components/ui/toast";
import { BRAND } from "@/lib/brand";
import "./globals.css";

/**
 * Archivo at 400/600/800 — the three weights the identity spec uses.
 *
 * Loaded through next/font rather than the design system's
 * `@import url(fonts.googleapis.com…)`: next/font fetches at BUILD time and
 * self-hosts the files, so the desktop bundle renders correctly with no
 * network at all. A runtime @import would silently fall back to system-ui
 * inside the Tauri webview, which is exactly where nobody would notice.
 */
const archivo = Archivo({
  subsets: ["latin"],
  weight: ["400", "600", "800"],
  variable: "--font-archivo",
  display: "swap",
});

export const metadata: Metadata = {
  title: BRAND.name,
  description: BRAND.memo,
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className={`${archivo.variable} h-full antialiased`}>
      <body className="min-h-full flex flex-col bg-background text-foreground">
        <ExternalLinks />
        <ToastProvider>{children}</ToastProvider>
      </body>
    </html>
  );
}
