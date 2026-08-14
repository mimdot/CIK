"use client";

import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { normalizeName } from "@/lib/api";
import type { NameSuggestion } from "@/types";

export interface CountryInputProps {
  id: string;
  label?: string;
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
}

/**
 * A country box that auto-corrects what you type (Phase 2D).
 *
 * It SUGGESTS rather than rewrites: typing "Germny" or "UK" offers the
 * canonical form for one click. Silently replacing what someone typed is
 * worse than a wrong search — they would never know why the results changed.
 *
 * Resolution happens server-side against the full ISO-3166 list, so every
 * country works, not the ~50 someone once thought to list.
 */
export function CountryInput({
  id,
  label = "Country",
  value,
  onChange,
  placeholder = "e.g. Germany",
}: CountryInputProps) {
  const [suggestion, setSuggestion] = useState<NameSuggestion | null>(null);
  const [unknown, setUnknown] = useState(false);

  useEffect(() => {
    const term = value.trim();
    if (term.length < 2) {
      return;
    }
    let stale = false;
    // Debounced: this fires per keystroke otherwise.
    const timer = setTimeout(() => {
      normalizeName({ country: term })
        .then((res) => {
          if (stale) return;
          const hit = res.country ?? null;
          setSuggestion(hit && hit.corrected ? hit : null);
          setUnknown(hit === null);
        })
        .catch(() => {
          if (!stale) {
            setSuggestion(null);
            setUnknown(false);
          }
        });
    }, 350);
    return () => {
      stale = true;
      clearTimeout(timer);
    };
  }, [value]);

  return (
    <div className="flex flex-col gap-1.5">
      <Label htmlFor={id}>{label}</Label>
      <Input
        id={id}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
      />
      {suggestion && (
        <p className="text-xs text-muted-foreground" data-testid="country-suggestion">
          Did you mean{" "}
          <Button
            type="button"
            variant="link"
            className="h-auto p-0 text-xs"
            onClick={() => {
              onChange(suggestion.value);
              setSuggestion(null);
            }}
          >
            {suggestion.value}
          </Button>
          ?
        </p>
      )}
      {unknown && value.trim().length > 2 && (
        <p className="text-xs text-amber-600" data-testid="country-unknown">
          “{value.trim()}” is not a country we recognise — results may be empty.
        </p>
      )}
    </div>
  );
}
