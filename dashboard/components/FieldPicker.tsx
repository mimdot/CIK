"use client";

import { useCallback, useEffect, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { fetchField, fetchFields } from "@/lib/api";
import type { FieldDetail, FieldSummary } from "@/types";

export interface FieldPickerProps {
  field: string;
  onFieldChange: (field: string) => void;
  subfields: string[];
  onSubfieldsChange: (subfields: string[]) => void;
  /** Explains what the selection scopes on this page. */
  hint?: string;
  idPrefix?: string;
}

/**
 * The primary control of the app: pick a research field, then narrow to
 * subfields.
 *
 * It drives BOTH position search and supervisor search, and every source,
 * keyword and literature database downstream follows from it. Subfields are
 * collapsed by default so the page never becomes cluttered, and the current
 * selection is always visible as removable chips.
 */
export function FieldPicker({
  field,
  onFieldChange,
  subfields,
  onSubfieldsChange,
  hint,
  idPrefix = "field",
}: FieldPickerProps) {
  const [fields, setFields] = useState<FieldSummary[]>([]);
  // Kept together with the field it describes, so a stale detail is DERIVED
  // away on render rather than cleared with a synchronous setState inside the
  // effect (which would trigger a cascading render).
  const [loaded, setLoaded] = useState<{
    forField: string;
    data: FieldDetail;
  } | null>(null);
  const [expanded, setExpanded] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    fetchFields()
      .then((data) => setFields(data.fields ?? []))
      .catch(() => setLoadError("Could not load the field list."));
  }, []);

  useEffect(() => {
    if (!field) return;
    let stale = false;
    fetchField(field)
      .then((data) => {
        if (!stale) setLoaded({ forField: field, data });
      })
      .catch(() => {
        if (!stale) setLoaded(null);
      });
    return () => {
      stale = true;
    };
  }, [field]);

  const detail = loaded && loaded.forField === field ? loaded.data : null;

  // Switching field invalidates any subfield selection — subfield ids are only
  // meaningful within their own field, and carrying them across would silently
  // scope the new search by the old field's vocabulary.
  const changeField = useCallback(
    (next: string) => {
      onFieldChange(next);
      onSubfieldsChange([]);
      setExpanded(false);
    },
    [onFieldChange, onSubfieldsChange],
  );

  const toggle = useCallback(
    (id: string) => {
      onSubfieldsChange(
        subfields.includes(id)
          ? subfields.filter((s) => s !== id)
          : [...subfields, id],
      );
    },
    [subfields, onSubfieldsChange],
  );

  const available = detail?.subfields ?? [];
  const allSelected = available.length > 0 && subfields.length === available.length;

  return (
    <div className="flex flex-col gap-3 rounded-lg border bg-card p-4">
      <div className="flex flex-col gap-1.5">
        <Label htmlFor={`${idPrefix}-select`} className="text-sm font-semibold">
          Research field
        </Label>
        <Select value={field} onValueChange={(v) => changeField(v ?? "")}>
          <SelectTrigger
            id={`${idPrefix}-select`}
            className="w-full sm:w-72"
            aria-label="Research field"
          >
            <SelectValue placeholder="Choose your field…" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="">All fields</SelectItem>
            {fields.map((f) => (
              <SelectItem key={f.name} value={f.name}>
                {f.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <p className="text-xs text-muted-foreground">
          {hint ??
            "Sets which job boards are searched and which publication database finds supervisors."}
        </p>
        {loadError && <p className="text-xs text-destructive">{loadError}</p>}
      </div>

      {detail && !detail.sources.has_dedicated && (
        <p className="rounded-md bg-muted/60 p-2 text-xs text-muted-foreground">
          No board is dedicated to {detail.label} yet, so the general
          multi-discipline boards are searched using {detail.label}&apos;s own
          keywords.
        </p>
      )}

      {available.length > 0 && (
        <div className="flex flex-col gap-2">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <button
              type="button"
              className="text-sm font-medium underline-offset-4 hover:underline"
              onClick={() => setExpanded((v) => !v)}
              aria-expanded={expanded}
              aria-controls={`${idPrefix}-subfields`}
            >
              {expanded ? "Hide" : "Narrow by"} subfield
              {subfields.length > 0 && ` (${subfields.length} selected)`}
            </button>
            {available.length > 0 && (
              <Button
                type="button"
                variant="ghost"
                size="sm"
                onClick={() =>
                  onSubfieldsChange(allSelected ? [] : available.map((s) => s.id))
                }
              >
                {allSelected ? "Clear all" : "Select all"}
              </Button>
            )}
          </div>

          {subfields.length > 0 && (
            <div className="flex flex-wrap gap-1.5">
              {subfields.map((id) => {
                const sub = available.find((s) => s.id === id);
                return (
                  <Badge
                    key={id}
                    variant="secondary"
                    className="cursor-pointer gap-1"
                    onClick={() => toggle(id)}
                  >
                    {sub?.label ?? id}
                    <span aria-hidden>×</span>
                    <span className="sr-only">Remove {sub?.label ?? id}</span>
                  </Badge>
                );
              })}
            </div>
          )}

          {expanded && (
            <ul
              id={`${idPrefix}-subfields`}
              className="grid max-h-56 gap-1 overflow-y-auto rounded-md border p-2 sm:grid-cols-2"
            >
              {available.map((sub) => (
                <li key={sub.id}>
                  <label className="flex cursor-pointer items-center gap-2 rounded px-1.5 py-1 text-sm hover:bg-muted">
                    <input
                      type="checkbox"
                      checked={subfields.includes(sub.id)}
                      onChange={() => toggle(sub.id)}
                      className="size-4"
                      // Explicit name: the label also carries the keyword
                      // count, which a screen reader would otherwise read out
                      // as part of the checkbox's name ("Genetics 6").
                      aria-label={sub.label}
                    />
                    <span className="flex-1">{sub.label}</span>
                    <span
                      className="text-xs text-muted-foreground"
                      title={`${sub.keyword_count} keywords`}
                    >
                      {sub.keyword_count}
                    </span>
                  </label>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
