"use client";

import { useCallback, useState } from "react";
import { openSavedFile, revealInFolder, saveTextFile } from "@/lib/desktop";

export interface ExportedFile {
  path: string;
  revealable: boolean;
}

/**
 * Save-to-file with the outcome kept in state, so a page can show where the
 * file went instead of leaving the user guessing.
 *
 * Three outcomes, all distinct and none of them silent:
 *  - saved     -> the full path, plus reveal/open actions on desktop
 *  - cancelled -> nothing at all (the user closed the dialog; not an error)
 *  - error     -> the real message, never swallowed
 *
 * The bug this replaces reported none of them: the export button called a
 * browser download API that a webview ignores, so every click did nothing and
 * said nothing.
 */
export function useFileExport() {
  const [saved, setSaved] = useState<ExportedFile | null>(null);
  const [error, setError] = useState<string | null>(null);

  const exportFile = useCallback(
    async (opts: { suggestedName: string; contents: string; mime: string }) => {
      setSaved(null);
      setError(null);
      try {
        const result = await saveTextFile(opts);
        if (result) setSaved(result); // null => cancelled, stay quiet
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      }
    },
    [],
  );

  const dismiss = useCallback(() => {
    setSaved(null);
    setError(null);
  }, []);

  const reveal = useCallback(() => {
    if (saved?.revealable) void revealInFolder(saved.path);
  }, [saved]);

  const open = useCallback(() => {
    if (saved?.revealable) void openSavedFile(saved.path);
  }, [saved]);

  return { saved, error, exportFile, dismiss, reveal, open };
}
