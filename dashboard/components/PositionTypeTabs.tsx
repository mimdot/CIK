"use client";

import { useEffect, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { fetchPositionTypes } from "@/lib/api";
import type { PositionType } from "@/types";
import { cn } from "@/lib/utils";

export interface PositionTypeTabsProps {
  value: string;
  onChange: (positionType: string) => void;
}

/**
 * PhD and Postdoc as separate, first-class searches (Phase 2C).
 *
 * They used to be blended: one run with `wanted_position_types: [phd, postdoc]`
 * and one mixed list, so you could not ask for postdocs specifically or see
 * PhD results on their own. Each tab is now its own search with its own
 * results.
 *
 * The tabs are DATA — whatever `/api/fields/position-types` returns is
 * rendered, and anything not `enabled` shows as a disabled "coming soon" chip.
 * Master's and Scholarships become real options by flipping one flag in
 * position_types.yaml; nothing here changes.
 */
export function PositionTypeTabs({ value, onChange }: PositionTypeTabsProps) {
  const [types, setTypes] = useState<PositionType[]>([]);

  useEffect(() => {
    fetchPositionTypes()
      .then((data) => setTypes(data.types ?? []))
      .catch(() => setTypes([]));
  }, []);

  if (types.length === 0) return null;

  return (
    <div className="flex flex-col gap-1.5">
      <span className="text-sm font-semibold">What are you looking for?</span>
      <div
        role="tablist"
        aria-label="Position type"
        className="flex flex-wrap gap-2"
      >
        {types.map((t) => {
          const active = t.enabled && value === t.name;
          return (
            <button
              key={t.name}
              type="button"
              role="tab"
              aria-selected={active}
              // A disabled tab is announced as such rather than simply looking
              // inert, so it reads as "planned", not "broken".
              aria-disabled={!t.enabled}
              disabled={!t.enabled}
              title={t.description}
              onClick={() => t.enabled && onChange(t.name)}
              className={cn(
                // Selected reads as INK, not accent: the accent belongs to
                // the primary action ("Search for positions"), and the spec
                // allows one accent element per view. Selection is carried by
                // a filled ink field and weight, which is unambiguous without
                // spending the accent.
                "inline-flex items-center gap-2 border px-4 py-2 text-sm transition-colors",
                active
                  ? "border-foreground bg-foreground font-bold text-background"
                  : t.enabled
                    ? "font-medium hover:bg-muted"
                    : "cursor-not-allowed font-medium opacity-60",
              )}
            >
              {t.label}
              {!t.enabled && (
                <Badge variant="outline" className="text-[10px]">
                  Coming soon
                </Badge>
              )}
            </button>
          );
        })}
      </div>
      <p className="text-xs text-muted-foreground">
        {types.find((t) => t.name === value)?.description ??
          "Each is its own search, with its own results."}
      </p>
    </div>
  );
}
