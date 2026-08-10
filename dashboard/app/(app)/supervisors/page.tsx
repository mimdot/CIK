"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import AuthGate from "@/components/AuthGate";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { buttonVariants } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError, fetchSupervisors } from "@/lib/api";
import { cn } from "@/lib/utils";
import { ChevronDown, ExternalLink, Mail, Search } from "lucide-react";
import type { Supervisor } from "@/types";

type SortKey = "fit_desc" | "fit_asc" | "name";

export default function SupervisorsPage() {
  const [items, setItems] = useState<Supervisor[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [country, setCountry] = useState("");
  const [field, setField] = useState("");
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<SortKey>("fit_desc");
  const [expanded, setExpanded] = useState<Set<number>>(new Set());

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchSupervisors(country || undefined, field || undefined);
      setItems(data.items);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not load supervisors");
      setItems([]);
    } finally {
      setLoading(false);
    }
  }, [country, field]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load();
  }, [load]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    const qs = q.split(/\s+/).filter(Boolean);
    const list = items.filter((s) => {
      if (!qs.length) return true;
      const hay = `${s.name} ${s.institution ?? ""} ${s.department ?? ""} ${s.topics.join(" ")}`.toLowerCase();
      return qs.every((part) => hay.includes(part));
    });
    return list.sort((a, b) => {
      if (sort === "name") return a.name.localeCompare(b.name);
      if (sort === "fit_asc") return (a.fit_score ?? 0) - (b.fit_score ?? 0);
      return (b.fit_score ?? 0) - (a.fit_score ?? 0);
    });
  }, [items, query, sort]);

  function toggle(id: number) {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  return (
    <AuthGate>
      <div className="flex flex-col gap-5">
        <div>
          <h1 className="text-2xl font-semibold">Supervisors</h1>
          <p className="text-sm text-muted-foreground">
            Potential PhD supervisors, ranked by fit. Expand a card for topics,
            recent papers and contact links.
          </p>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <div className="flex flex-col gap-1.5 sm:col-span-2">
          <Label htmlFor="search">Search</Label>
          <div className="relative">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden />
            <Input
              id="search"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="name, institution, topic…"
              className="pl-8"
            />
          </div>
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="country">Country</Label>
          <Input
            id="country"
            value={country}
            onChange={(e) => setCountry(e.target.value)}
            placeholder="e.g. Germany"
          />
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="field">Field / topic</Label>
          <Input
            id="field"
            value={field}
            onChange={(e) => setField(e.target.value)}
            placeholder="e.g. interstellar medium"
          />
        </div>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-3">
        <Button variant="outline" onClick={() => void load()}>
          Apply filters
        </Button>
        <div className="flex w-full items-center gap-2 sm:w-auto">
          <Label htmlFor="sort" className="shrink-0 text-sm text-muted-foreground">
            Sort
          </Label>
          <Select value={sort} onValueChange={(v) => setSort((v ?? "fit_desc") as SortKey)}>
            <SelectTrigger id="sort" className="w-full sm:w-56">
              <SelectValue placeholder="Sort by fit" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="fit_desc">Fit (high → low)</SelectItem>
              <SelectItem value="fit_asc">Fit (low → high)</SelectItem>
              <SelectItem value="name">Name A→Z</SelectItem>
            </SelectContent>
          </Select>
        </div>
      </div>

      {error && <p className="text-sm text-destructive">{error}</p>}

      {loading && (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {Array.from({ length: 6 }).map((_, i) => (
            <Card key={i}>
              <CardHeader>
                <Skeleton className="h-5 w-2/3" />
                <Skeleton className="h-4 w-1/2" />
              </CardHeader>
              <CardContent className="flex flex-col gap-2">
                <Skeleton className="h-4 w-full" />
                <Skeleton className="h-4 w-3/4" />
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      {!loading && filtered.length === 0 && (
        <div className="rounded-md border p-8 text-center text-sm text-muted-foreground">
          {items.length === 0
            ? "No supervisors found. Adjust the country / field filters."
            : "No supervisors match your search."}
        </div>
      )}

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {filtered.map((s) => {
          const isOpen = expanded.has(s.id);
          return (
            <Card key={s.id} className="flex flex-col">
              <CardHeader>
                <CardTitle className="text-base">{s.name}</CardTitle>
                <CardDescription>
                  {[s.institution, s.department, s.country].filter(Boolean).join(" · ") ||
                    "Institution n/a"}
                </CardDescription>
              </CardHeader>
              <CardContent className="mt-auto flex flex-col gap-2 pt-0">
                <div className="flex flex-wrap items-center gap-2">
                  {s.fit_score != null && (
                    <Badge data-testid="fit-score">
                      Fit {Math.round(s.fit_score * 100)}%
                    </Badge>
                  )}
                  {s.source && <Badge variant="outline">{s.source}</Badge>}
                </div>

                {s.topics.length > 0 && (
                  <div className="flex flex-wrap gap-1.5">
                    {s.topics.slice(0, isOpen ? undefined : 3).map((t) => (
                      <Badge key={t} variant="outline">
                        {t}
                      </Badge>
                    ))}
                  </div>
                )}

                {isOpen && (
                  <div className="flex flex-col gap-3 text-sm">
                    <Separator />
                    {s.methods.length > 0 && (
                      <div>
                        <p className="mb-1 text-xs font-medium uppercase tracking-wide text-muted-foreground">
                          Methods
                        </p>
                        <p>{s.methods.join(", ")}</p>
                      </div>
                    )}
                    {s.recent_papers && s.recent_papers.length > 0 && (
                      <div>
                        <p className="mb-1 text-xs font-medium uppercase tracking-wide text-muted-foreground">
                          Recent papers
                        </p>
                        <ul className="flex list-disc flex-col gap-1 pl-4 text-muted-foreground">
                          {s.recent_papers.slice(0, 5).map((p, i) => (
                            <li key={i}>{p}</li>
                          ))}
                        </ul>
                      </div>
                    )}
                    {s.email && (
                      <a
                        href={`mailto:${s.email}`}
                        className="inline-flex items-center gap-1.5 text-primary hover:underline"
                      >
                        <Mail className="size-3.5" aria-hidden />
                        {s.email}
                      </a>
                    )}
                  </div>
                )}

                <div className="mt-2 flex flex-wrap items-center gap-2">
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => toggle(s.id)}
                    aria-expanded={isOpen}
                    className="pl-0"
                  >
                    <ChevronDown
                      className={cn("size-4 transition-transform", isOpen && "rotate-180")}
                      aria-hidden
                    />
                    {isOpen ? "Show less" : "Show details"}
                  </Button>
                  {s.orcid && (
                    <a
                      href={`https://orcid.org/${s.orcid}`}
                      target="_blank"
                      rel="noopener noreferrer"
                      className={buttonVariants({ variant: "outline", size: "sm" })}
                    >
                      ORCID <ExternalLink className="size-3.5" aria-hidden />
                    </a>
                  )}
                  {s.profile_url && (
                    <a
                      href={s.profile_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className={buttonVariants({ variant: "outline", size: "sm" })}
                    >
                      Profile <ExternalLink className="size-3.5" aria-hidden />
                    </a>
                  )}
                </div>
              </CardContent>
            </Card>
          );
        })}
      </div>
      </div>
    </AuthGate>
  );
}
