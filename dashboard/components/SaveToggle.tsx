"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Star } from "lucide-react";
import { ApiError, deleteSaved, saveItem } from "@/lib/api";
import type { SavedKind } from "@/types";

/**
 * Save/unsave a record. The same control on both kinds of card.
 *
 * The parent owns the saved state, because a card cannot answer "is this
 * saved?" on its own without one request per card. The list fetches every
 * saved key once and hands each card its answer.
 */
export default function SaveToggle({
  kind,
  recordId,
  savedId,
  onChange,
}: {
  kind: SavedKind;
  recordId: number;
  /** The saved-item id when this record is saved, else null. */
  savedId: number | null;
  onChange: (next: { savedId: number | null }) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const saved = savedId !== null;

  async function toggle() {
    setBusy(true);
    setError(null);
    try {
      if (saved) {
        await deleteSaved(savedId);
        onChange({ savedId: null });
      } else {
        const item = await saveItem(kind, recordId);
        onChange({ savedId: item.id });
      }
    } catch (e) {
      // Say what went wrong on the control itself. A star that quietly refuses
      // to fill in is the same dead-control problem in miniature.
      setError(e instanceof ApiError ? e.message : "Could not save");
    } finally {
      setBusy(false);
    }
  }

  return (
    <span className="inline-flex items-center gap-1.5">
      <Button
        variant="outline"
        size="sm"
        onClick={() => void toggle()}
        disabled={busy}
        aria-pressed={saved}
        aria-label={saved ? "Remove from saved" : "Save"}
        title={saved ? "Remove from saved" : "Save"}
      >
        <Star
          className={saved ? "size-4 fill-current" : "size-4"}
          aria-hidden
        />
      </Button>
      {error && <span className="text-xs text-destructive">{error}</span>}
    </span>
  );
}
