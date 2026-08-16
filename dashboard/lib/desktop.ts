// The two things a Tauri webview cannot do that a browser can, in one place.
//
// A webview is not a browser. `<a href="https://…">` does not open the user's
// browser — it tries to navigate the app window itself, which the shell
// refuses, so the click looks dead. `URL.createObjectURL` + `a.download` does
// not write a file — there is no download manager behind it, so "Export CSV"
// silently does nothing. Both need a Tauri plugin and a permission.
//
// Everything here is a no-op difference on the web build: the same functions
// fall back to the browser behaviour, so callers never branch on platform.
// The plugin modules are loaded with dynamic `import()` so they stay out of
// the web bundle entirely.

/**
 * Are we running inside the desktop shell?
 *
 * `__CIK_DESKTOP__` is injected by the Rust shell on every page load, which is
 * the signal we control and can rely on. `isTauri` is Tauri v2's own marker,
 * kept as a fallback. Note that `window.__TAURI__` is NOT a valid check here:
 * v2 only defines it under `app.withGlobalTauri`, which this app does not set.
 */
export function isDesktop(): boolean {
  if (typeof window === "undefined") return false;
  const w = window as unknown as { __CIK_DESKTOP__?: boolean; isTauri?: boolean };
  return w.__CIK_DESKTOP__ === true || w.isTauri === true;
}

/** Links that must leave the app: real sites, mail clients, diallers. */
export function isExternalHref(href: string): boolean {
  return /^(https?:|mailto:|tel:)/i.test(href.trim());
}

/** Open a URL in the user's real browser (or a new tab on the web). */
export async function openExternal(url: string): Promise<void> {
  if (isDesktop()) {
    const { openUrl } = await import("@tauri-apps/plugin-opener");
    await openUrl(url);
    return;
  }
  window.open(url, "_blank", "noopener,noreferrer");
}

export interface SavedFile {
  /** Absolute path on desktop; the file name on the web. */
  path: string;
  /** Whether "Show in folder" / "Open file" can act on this path. */
  revealable: boolean;
}

/**
 * Save text to a file the user chooses.
 *
 * Returns null when the user cancels the dialog — that is not an error and
 * must not be reported as one. Anything that actually fails throws, so the
 * caller can show the real reason instead of a silent no-op.
 */
export async function saveTextFile(opts: {
  suggestedName: string;
  contents: string;
  mime: string;
}): Promise<SavedFile | null> {
  const { suggestedName, contents, mime } = opts;

  if (isDesktop()) {
    const { save } = await import("@tauri-apps/plugin-dialog");
    const ext = suggestedName.split(".").pop() ?? "";
    const path = await save({
      defaultPath: suggestedName,
      filters: ext ? [{ name: ext.toUpperCase(), extensions: [ext] }] : undefined,
    });
    if (!path) return null; // cancelled
    const { invoke } = await import("@tauri-apps/api/core");
    const written = await invoke<string>("write_text_file", { path, contents });
    return { path: written, revealable: true };
  }

  const blob = new Blob([contents], { type: mime });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = suggestedName;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
  return { path: suggestedName, revealable: false };
}

/** Select the file in the OS file manager. Desktop only. */
export async function revealInFolder(path: string): Promise<void> {
  if (!isDesktop()) return;
  const { revealItemInDir } = await import("@tauri-apps/plugin-opener");
  await revealItemInDir(path);
}

/** Open the file with the OS default application. Desktop only. */
export async function openSavedFile(path: string): Promise<void> {
  if (!isDesktop()) return;
  const { openPath } = await import("@tauri-apps/plugin-opener");
  await openPath(path);
}
