"use client";

// Minimal toast system (Sprint 05, A5). A context provider renders a fixed
// viewport of auto-dismissing toasts; `useToast()` pushes them from any page.

import * as React from "react";
import { useCallback, useContext, useState } from "react";
import { CheckCircle2, Info, TriangleAlert } from "lucide-react";
import { cn } from "@/lib/utils";

type ToastVariant = "default" | "success" | "destructive";

interface ToastItem {
  id: number;
  title: string;
  description?: string;
  variant: ToastVariant;
}

interface ToastOptions {
  description?: string;
  variant?: ToastVariant;
}

interface ToastContextValue {
  toast: (title: string, opts?: ToastOptions) => void;
}

const ToastContext = React.createContext<ToastContextValue | null>(null);

export function useToast(): ToastContextValue {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error("useToast must be used within <ToastProvider>");
  return ctx;
}

const ICONS: Record<ToastVariant, React.ReactNode> = {
  default: <Info className="size-4" aria-hidden />,
  success: <CheckCircle2 className="size-4" aria-hidden />,
  destructive: <TriangleAlert className="size-4" aria-hidden />,
};

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<ToastItem[]>([]);

  const toast = useCallback((title: string, opts: ToastOptions = {}) => {
    const id = Date.now() + Math.random();
    setToasts((prev) => [
      ...prev,
      { id, title, description: opts.description, variant: opts.variant ?? "default" },
    ]);
    window.setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.id !== id));
    }, 4000);
  }, []);

  return (
    <ToastContext.Provider value={{ toast }}>
      {children}
      <div
        aria-live="polite"
        aria-atomic="false"
        className="pointer-events-none fixed bottom-4 left-1/2 z-[60] flex w-[calc(100%-2rem)] max-w-sm -translate-x-1/2 flex-col gap-2 sm:left-auto sm:right-4 sm:translate-x-0"
      >
        {toasts.map((t) => (
          <div
            key={t.id}
            data-variant={t.variant}
            className={cn(
              "pointer-events-auto flex items-start gap-2.5 rounded-lg border bg-background p-3 text-sm shadow-lg ring-1 ring-foreground/10",
              t.variant === "destructive" && "border-destructive/40 text-destructive",
              t.variant === "success" && "border-foreground/40",
            )}
          >
            <span className="mt-0.5 shrink-0">{ICONS[t.variant]}</span>
            <div className="min-w-0">
              <p className="font-medium">{t.title}</p>
              {t.description && (
                <p className="text-muted-foreground">{t.description}</p>
              )}
            </div>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}
