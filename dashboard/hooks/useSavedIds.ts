"use client";

import { useCallback, useEffect, useState } from "react";
import { fetchSavedIds } from "@/lib/api";
import type { SavedKind } from "@/types";

/**
 * Which records in a list are already saved.
 *
 * One request for the whole list, not one per card: the mapping from live row
 * id to saved-item id is resolved server-side, because the stable key a saved
 * item is stored under is derived there and a second copy of those rules in
 * the browser would be free to drift.
 *
 * Failure is silent on purpose. Not knowing whether something is saved must
 * not stop the list from rendering; the toggle simply starts unfilled, and
 * pressing it still works (saving twice is not an error).
 */
export function useSavedIds(kind: SavedKind) {
  const [ids, setIds] = useState<Record<string, number>>({});

  const reload = useCallback(() => {
    fetchSavedIds(kind)
      .then((r) => setIds(r.ids ?? {}))
      .catch(() => setIds({}));
  }, [kind]);

  useEffect(reload, [reload]);

  /** Apply a toggle's outcome locally, so the star fills without a refetch. */
  const set = useCallback((recordId: number, savedId: number | null) => {
    setIds((prev) => {
      const next = { ...prev };
      if (savedId === null) delete next[String(recordId)];
      else next[String(recordId)] = savedId;
      return next;
    });
  }, []);

  const savedIdFor = useCallback(
    (recordId: number): number | null => ids[String(recordId)] ?? null,
    [ids],
  );

  return { savedIdFor, set, reload };
}
