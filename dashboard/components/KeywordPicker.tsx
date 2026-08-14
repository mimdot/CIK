"use client";

import { useEffect, useMemo, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { fetchField } from "@/lib/api";
import type { FieldDetail } from "@/types";

export interface KeywordPickerProps {
  field: string;
  selected: string[];
  onChange: (keywords: string[]) => void;
}

/**
 * Pick your research keywords from a curated list — the PRIMARY way to tell
 * the app what you work on.
 *
 * It replaces the dependency on CV parsing (fragile) and on an AI service
 * (needs a paid key, and produced a bare "Could not extract profile from text"
 * when absent). The vocabulary comes from fields/*.yaml — the very terms the
 * relevance engine scores against — so a keyword picked here can never fail
 * to match the way a typed guess can.
 *
 * Layout rules that keep it from becoming cluttered: subfields are collapsed
 * by default, each group has select-all, the current selection is always
 * visible as removable chips, and a search box filters across every group.
 */
export function KeywordPicker({ field, selected, onChange }: KeywordPickerProps) {
  const [detail, setDetail] = useState<{ forField: string; data: FieldDetail } | null>(
    null,
  );
  const [open, setOpen] = useState<Set<string>>(new Set());
  const [query, setQuery] = useState("");
  const [custom, setCustom] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!field) return;
    let stale = false;
    fetchField(field)
      .then((data) => {
        if (!stale) setDetail({ forField: field, data });
      })
      .catch(() => {
        if (!stale) setError("Could not load the keyword list for this field.");
      });
    return () => {
      stale = true;
    };
  }, [field]);

  const data = detail && detail.forField === field ? detail.data : null;
  const needle = query.trim().toLowerCase();

  // When searching, show only matching keywords and auto-expand their groups
  // so a hit is never hidden behind a collapsed header.
  const groups = useMemo(() => {
    const subs = data?.subfields ?? [];
    return subs
      .map((s) => ({
        ...s,
        matches: (s.keywords ?? []).filter(
          (k) => !needle || k.toLowerCase().includes(needle),
        ),
      }))
      .filter((s) => !needle || s.matches.length > 0);
  }, [data, needle]);

  function toggle(keyword: string) {
    onChange(
      selected.includes(keyword)
        ? selected.filter((k) => k !== keyword)
        : [...selected, keyword],
    );
  }

  function toggleGroup(keywords: string[]) {
    const allOn = keywords.every((k) => selected.includes(k));
    onChange(
      allOn
        ? selected.filter((k) => !keywords.includes(k))
        : [...new Set([...selected, ...keywords])],
    );
  }

  function addCustom() {
    const term = custom.trim();
    if (!term || selected.includes(term)) {
      setCustom("");
      return;
    }
    onChange([...selected, term]);
    setCustom("");
  }

  if (!field) {
    return (
      <p className="rounded-md border bg-muted/40 p-4 text-sm text-muted-foreground">
        Choose a research field first — the keyword list comes from it.
      </p>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      {error && <p className="text-sm text-destructive">{error}</p>}

      {/* Current selection, always visible, always removable. */}
      <div className="flex flex-col gap-1.5">
        <Label>Your keywords ({selected.length})</Label>
        {selected.length === 0 ? (
          <p className="text-xs text-muted-foreground">
            Nothing selected yet. Pick from the groups below, or type your own.
          </p>
        ) : (
          <div className="flex flex-wrap gap-1.5" data-testid="keyword-chips">
            {selected.map((k) => (
              <Badge
                key={k}
                variant="secondary"
                className="cursor-pointer gap-1"
                onClick={() => toggle(k)}
              >
                {k}
                <span aria-hidden>×</span>
                <span className="sr-only">Remove {k}</span>
              </Badge>
            ))}
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="h-6 px-2 text-xs"
              onClick={() => onChange([])}
            >
              Clear all
            </Button>
          </div>
        )}
      </div>

      <div className="flex flex-col gap-1.5">
        <Label htmlFor="kw-search">Search keywords</Label>
        <Input
          id="kw-search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Type to filter, e.g. catalysis…"
        />
      </div>

      <ul className="flex flex-col gap-1.5">
        {groups.map((group) => {
          const expanded = open.has(group.id) || needle.length > 0;
          const chosen = group.matches.filter((k) => selected.includes(k)).length;
          return (
            <li key={group.id} className="rounded-md border">
              <div className="flex items-center justify-between gap-2 px-3 py-2">
                <button
                  type="button"
                  className="flex-1 text-left text-sm font-medium"
                  onClick={() =>
                    setOpen((prev) => {
                      const next = new Set(prev);
                      if (next.has(group.id)) next.delete(group.id);
                      else next.add(group.id);
                      return next;
                    })
                  }
                  aria-expanded={expanded}
                >
                  {group.label}
                  <span className="ml-2 text-xs font-normal text-muted-foreground">
                    {chosen > 0
                      ? `${chosen} of ${group.matches.length} selected`
                      : `${group.matches.length} keywords`}
                  </span>
                </button>
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  className="text-xs"
                  onClick={() => toggleGroup(group.matches)}
                >
                  {group.matches.every((k) => selected.includes(k))
                    ? "None"
                    : "All"}
                </Button>
              </div>
              {expanded && (
                <ul className="grid gap-0.5 border-t p-2 sm:grid-cols-2">
                  {group.matches.map((k) => (
                    <li key={k}>
                      <label className="flex cursor-pointer items-center gap-2 rounded px-1.5 py-1 text-sm hover:bg-muted">
                        <input
                          type="checkbox"
                          className="size-4"
                          checked={selected.includes(k)}
                          onChange={() => toggle(k)}
                          aria-label={k}
                        />
                        <span>{k}</span>
                      </label>
                    </li>
                  ))}
                </ul>
              )}
            </li>
          );
        })}
        {data && groups.length === 0 && (
          <li className="rounded-md border p-4 text-center text-sm text-muted-foreground">
            No keyword matches “{query}”. You can add it as your own below.
          </li>
        )}
      </ul>

      <div className="flex flex-col gap-1.5">
        <Label htmlFor="kw-custom">Add your own</Label>
        <div className="flex gap-2">
          <Input
            id="kw-custom"
            value={custom}
            onChange={(e) => setCustom(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                addCustom();
              }
            }}
            placeholder="A term that is not in the list…"
          />
          <Button type="button" variant="outline" onClick={addCustom}>
            Add
          </Button>
        </div>
      </div>
    </div>
  );
}
