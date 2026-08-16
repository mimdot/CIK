"use client";

import { Button } from "@/components/ui/button";
import type { ExportedFile } from "@/hooks/useFileExport";

/**
 * The result of an export, stated plainly: the full path it was written to,
 * with the actions that make that path useful. Renders nothing when there is
 * nothing to report, so a cancelled dialog leaves no trace.
 */
export default function ExportResult({
  saved,
  error,
  onDismiss,
  onReveal,
  onOpen,
}: {
  saved: ExportedFile | null;
  error: string | null;
  onDismiss: () => void;
  onReveal: () => void;
  onOpen: () => void;
}) {
  if (error) {
    return (
      <div
        className="flex flex-wrap items-center gap-3 rounded-md border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive"
        data-testid="export-error"
      >
        <span className="min-w-0 break-all">Export failed: {error}</span>
        <Button variant="outline" size="sm" onClick={onDismiss}>
          Dismiss
        </Button>
      </div>
    );
  }

  if (!saved) return null;

  return (
    <div
      className="flex flex-wrap items-center gap-3 rounded-md border p-3 text-sm"
      data-testid="export-saved"
    >
      <span className="min-w-0 break-all">
        Saved to <code className="font-mono">{saved.path}</code>
      </span>
      {saved.revealable && (
        <>
          <Button variant="outline" size="sm" onClick={onReveal}>
            Show in folder
          </Button>
          <Button variant="outline" size="sm" onClick={onOpen}>
            Open file
          </Button>
        </>
      )}
      <Button variant="ghost" size="sm" onClick={onDismiss}>
        Dismiss
      </Button>
    </div>
  );
}
