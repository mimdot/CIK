import ErrorBoundary from "@/components/ErrorBoundary";
import Nav from "@/components/Nav";
import { ToastProvider } from "@/components/ui/toast";

export default function AppLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <ToastProvider>
      <Nav />
      <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-6">
        <ErrorBoundary>{children}</ErrorBoundary>
      </main>
      <footer className="border-t py-4 text-center text-xs text-muted-foreground">
        Career Intelligence Kit · private beta
      </footer>
    </ToastProvider>
  );
}
