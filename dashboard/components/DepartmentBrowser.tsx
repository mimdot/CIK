"use client";

import { useEffect, useState } from "react";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { fetchFieldDepartments } from "@/lib/api";
import type { DepartmentList } from "@/types";

/**
 * Browse a field's departments yourself — the manual alternative to the slow
 * exhaustive sweep.
 *
 * Crawling these pages is by far the most expensive thing the engine does
 * (~150 pages for astronomy at a 2s crawl delay). Rather than making everyone
 * pay that, this hands over the same curated list instantly: filter by
 * country, search by name, open the department's own page.
 */
export function DepartmentBrowser({ field }: { field: string }) {
  const [data, setData] = useState<DepartmentList | null>(null);
  const [country, setCountry] = useState("");
  const [query, setQuery] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!field) return;
    let stale = false;
    fetchFieldDepartments(field, {
      country: country || undefined,
      q: query || undefined,
    })
      .then((d) => {
        if (!stale) setData(d);
      })
      .catch(() => {
        if (!stale) setError("Could not load the department list.");
      });
    return () => {
      stale = true;
    };
  }, [field, country, query]);

  if (!field) {
    return (
      <p className="text-sm text-muted-foreground">
        Choose a research field to browse its departments.
      </p>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-end gap-3">
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="dept-country">Country</Label>
          <Select value={country} onValueChange={(v) => setCountry(v ?? "")}>
            <SelectTrigger
              id="dept-country"
              className="w-52"
              aria-label="Department country"
            >
              <SelectValue placeholder="All countries" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="">All countries</SelectItem>
              {(data?.countries ?? []).map((c) => (
                <SelectItem key={c} value={c}>
                  {c}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="flex flex-1 flex-col gap-1.5">
          <Label htmlFor="dept-search">Search</Label>
          <Input
            id="dept-search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Institution or country…"
          />
        </div>
      </div>

      {error && <p className="text-sm text-destructive">{error}</p>}

      <p className="text-xs text-muted-foreground">
        {data ? `${data.total} department${data.total === 1 ? "" : "s"}` : "…"}{" "}
        — opens the department&apos;s own vacancies page. No crawling, nothing
        to wait for.
      </p>

      <ul className="max-h-96 divide-y overflow-y-auto rounded-md border">
        {(data?.departments ?? []).map((d) => (
          <li key={d.url} className="px-3 py-2 text-sm hover:bg-muted/50">
            <a
              href={d.url}
              target="_blank"
              rel="noopener noreferrer"
              className="font-medium hover:underline"
            >
              {d.institution}
            </a>
            <span className="ml-2 text-xs text-muted-foreground">
              {d.country}
            </span>
          </li>
        ))}
        {data && data.departments.length === 0 && (
          <li className="px-3 py-6 text-center text-sm text-muted-foreground">
            No departments match those filters.
          </li>
        )}
      </ul>
    </div>
  );
}
