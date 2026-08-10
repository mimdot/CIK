import type { Metadata } from "next";
import ErrorBoundary from "@/components/ErrorBoundary";
import Nav from "@/components/Nav";
import { ToastProvider } from "@/components/ui/toast";
import "./globals.css";

export const metadata: Metadata = {
  title: "Career Intelligence",
  description:
    "Personal PhD position dashboard: build your profile, find matches, and save opportunities.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className="h-full antialiased">
      <body className="min-h-full flex flex-col bg-background text-foreground">
        <ToastProvider>
          <Nav />
          <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-6">
            <ErrorBoundary>{children}</ErrorBoundary>
          </main>
          <footer className="border-t py-4 text-center text-xs text-muted-foreground">
            Career Intelligence Kit · Sprint 05
          </footer>
        </ToastProvider>
      </body>
    </html>
  );
}
