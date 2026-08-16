"use client";

import { useEffect } from "react";
import { isDesktop, isExternalHref, openExternal } from "@/lib/desktop";

/**
 * Route every external link through the system browser, app-wide.
 *
 * Mounted once in the root layout and done as a single delegated listener
 * rather than a special <ExternalLink> component, deliberately: the failure
 * being fixed here is *links that were missed*, and a per-component approach
 * only works for the components someone remembered to convert. A capture-phase
 * listener on the document catches every anchor that exists now or later,
 * including ones rendered from crawled data (opportunity postings, supervisor
 * profiles) where the href is not visible in the source at all.
 *
 * Inert on the web build, where a plain anchor already does the right thing.
 */
export default function ExternalLinks() {
  useEffect(() => {
    function onClick(event: MouseEvent) {
      // Checked per click, not once at mount: the shell injects the desktop
      // flag on page load, which can land after React has already mounted.
      if (!isDesktop()) return;
      // Let modified clicks alone — they mean "open how I asked".
      if (event.defaultPrevented || event.button !== 0) return;
      if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;

      const target = event.target as Element | null;
      const anchor = target?.closest?.("a[href]") as HTMLAnchorElement | null;
      if (!anchor) return;

      const href = anchor.getAttribute("href") ?? "";
      if (!isExternalHref(href)) return; // in-app route: Next handles it

      event.preventDefault();
      void openExternal(href).catch(() => {
        // Nothing useful to do in a click handler; the link simply does not
        // open. Better than the previous behaviour either way, which was the
        // same outcome with no attempt made.
      });
    }

    document.addEventListener("click", onClick, true);
    return () => document.removeEventListener("click", onClick, true);
  }, []);

  return null;
}
