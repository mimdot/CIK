import ErrorBoundary from "@/components/ErrorBoundary";
import Nav from "@/components/Nav";
import { SiteFooter } from "@/components/SiteFooter";
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
      <SiteFooter />
    </ToastProvider>
  );
}
