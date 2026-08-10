"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { ApiError, fetchOpportunities } from "@/lib/api";
import type { Opportunity } from "@/types";

const PAGE_SIZE = 12;

export default function OpportunitiesPage() {
  const [items, setItems] = useState<Opportunity[]>([]);
  const [total, setTotal] = useState(0);
  const [pages, setPages] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [country, setCountry] = useState("");
  const [source, setSource] = useState("");
  const [type, setType] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchOpportunities({
        country: country || undefined,
        source: source || undefined,
        type: type || undefined,
        page,
        limit: PAGE_SIZE,
      });
      setItems(data.items);
      setTotal(data.total);
      setPages(data.pages ?? 0);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not load opportunities");
    } finally {
      setLoading(false);
    }
  }, [country, source, type, page]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load();
  }, [load]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setPage(1);
  }, [country, source, type]);

  const countries = useMemo(
    () => [...new Set(items.map((o) => o.country).filter(Boolean) as string[])].sort(),
    [items],
  );
  const sources = useMemo(
    () => [...new Set(items.map((o) => o.source).filter(Boolean))].sort(),
    [items],
  );
  const types = useMemo(
    () => [...new Set(items.map((o) => o.position_type).filter(Boolean) as string[])].sort(),
    [items],
  );

  return (
    <div className="flex flex-col gap-5">
      <div>
        <h1 className="text-2xl font-semibold">Opportunities</h1>
        <p className="text-sm text-muted-foreground">
          {loading ? "Loading…" : `${total} open positions.`}
        </p>
      </div>

      <div className="grid gap-3 sm:grid-cols-3 lg:grid-cols-5">
        <FilterInput label="Country" value={country} onChange={setCountry} options={countries} />
        <FilterInput label="Source" value={source} onChange={setSource} options={sources} />
        <FilterInput label="Type" value={type} onChange={setType} options={types} />
        <Button
          variant="outline"
          className="sm:col-span-3 lg:col-span-2 lg:self-end"
          onClick={() => void load()}
        >
          Refresh
        </Button>
      </div>

      {error && <p className="text-sm text-destructive">{error}</p>}

      {!loading && items.length === 0 && (
        <div className="rounded-md border p-8 text-center text-sm text-muted-foreground">
          No opportunities found.
        </div>
      )}

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {items.map((o) => (
          <Card key={o.id} className="flex flex-col">
            <CardHeader>
              <CardTitle className="text-base leading-snug">
                <a
                  href={o.url ?? "#"}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="hover:underline"
                >
                  {o.title}
                </a>
              </CardTitle>
              <CardDescription>
                {[o.institution, o.country].filter(Boolean).join(" · ") || "Institution n/a"}
              </CardDescription>
            </CardHeader>
            <CardContent className="mt-auto flex flex-wrap gap-1.5 pt-0">
              {o.source && <Badge variant="outline">{o.source}</Badge>}
              {o.position_type && <Badge variant="outline">{o.position_type}</Badge>}
              {o.deadline && (
                <Badge variant="outline">Deadline {o.deadline.slice(0, 10)}</Badge>
              )}
            </CardContent>
          </Card>
        ))}
      </div>

      {pages > 1 && (
        <div className="flex items-center justify-center gap-3">
          <Button variant="outline" size="sm" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>
            Previous
          </Button>
          <span className="text-sm text-muted-foreground">
            Page {page} of {pages}
          </span>
          <Button variant="outline" size="sm" disabled={page >= pages} onClick={() => setPage((p) => p + 1)}>
            Next
          </Button>
        </div>
      )}
    </div>
  );
}

function FilterInput({
  label,
  value,
  onChange,
  options,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  options: string[];
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <Label>{label}</Label>
      <Select value={value} onValueChange={(v) => onChange(v ?? "")}>
        <SelectTrigger className="w-full">
          <SelectValue placeholder={`All ${label.toLowerCase()}s`} />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="">All {label.toLowerCase()}s</SelectItem>
          {options.map((o) => (
            <SelectItem key={o} value={o}>
              {o}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
}
