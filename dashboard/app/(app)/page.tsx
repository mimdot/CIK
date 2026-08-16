"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import AuthGate from "@/components/AuthGate";
import MatchCard from "@/components/MatchCard";
import { useSavedIds } from "@/hooks/useSavedIds";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { ApiError, fetchMatches, fetchFields } from "@/lib/api";
import type { Match } from "@/types";

export default function DashboardPage() {
  const [matches, setMatches] = useState<Match[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [query, setQuery] = useState("");
  const [country, setCountry] = useState("all");
  const [source, setSource] = useState("all");
  const [type, setType] = useState("all");
  const [field, setField] = useState("");
  const [fieldProfiles, setFieldProfiles] = useState<string[]>([]);
  const saved = useSavedIds("opportunity");

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchMatches(0, 100, field || undefined);
      const items = (data.items as Match[]).sort(
        (a, b) => b.match_score - a.match_score,
      );
      setMatches(items);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not load matches");
      setMatches([]);
    } finally {
      setLoading(false);
    }
  }, [field]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load();
  }, [load]);

  // Load field profiles for the dropdown
  useEffect(() => {
    fetchFields()
      .then((data) => setFieldProfiles(data.profiles))
      .catch(() => setFieldProfiles([]));
  }, []);

  const facets = useMemo(() => {
    const countries = new Set<string>();
    const sources = new Set<string>();
    const types = new Set<string>();
    for (const m of matches) {
      if (m.country) countries.add(m.country);
      if (m.source) sources.add(m.source);
      if (m.position_type) types.add(m.position_type);
    }
    return {
      countries: [...countries].sort(),
      sources: [...sources].sort(),
      types: [...types].sort(),
    };
  }, [matches]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return matches.filter((m) => {
      if (country !== "all" && m.country !== country) return false;
      if (source !== "all" && m.source !== source) return false;
      if (type !== "all" && m.position_type !== type) return false;
      if (q && !`${m.title} ${m.institution ?? ""} ${m.country ?? ""}`
        .toLowerCase().includes(q)) {
        return false;
      }
      return true;
    });
  }, [matches, query, country, source, type]);

  return (
    <AuthGate>
      <div className="flex flex-col gap-5">
        <div className="flex flex-col gap-1">
          <h1 className="text-2xl font-semibold">Your matches</h1>
          <p className="text-sm text-muted-foreground">
            {loading
              ? "Loading…"
              : `${matches.length} opportunities scored against your profile.`}
          </p>
        </div>

        <Card>
          <CardContent className="grid gap-3 p-4 sm:grid-cols-2 lg:grid-cols-5">
            <div className="flex flex-col gap-1.5 lg:col-span-2">
              <Label htmlFor="search">Search</Label>
              <Input
                id="search"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="title, institution, country…"
              />
            </div>
            <FilterSelect
              id="country-filter"
              label="Country"
              value={country}
              onChange={setCountry}
              options={facets.countries}
              placeholder="All countries"
            />
            <FilterSelect
              id="source-filter"
              label="Source"
              value={source}
              onChange={setSource}
              options={facets.sources}
              placeholder="All sources"
            />
            <FilterSelect
              id="type-filter"
              label="Type"
              value={type}
              onChange={setType}
              options={facets.types}
              placeholder="All types"
            />
            <FilterSelect
              id="field-filter"
              label="Field"
              value={field}
              onChange={setField}
              options={fieldProfiles}
              placeholder="All fields"
            />
          </CardContent>
        </Card>

        {error && (
          <div className="rounded-md border border-destructive/30 bg-destructive/10 p-4 text-sm text-destructive">
            {error}
            <Button variant="outline" size="sm" className="ml-3" onClick={() => void load()}>
              Retry
            </Button>
          </div>
        )}

        {!loading && !error && filtered.length === 0 && (
          <div className="rounded-md border p-8 text-center text-sm text-muted-foreground">
            {matches.length === 0
              ? "No matches yet. Build a profile first — the scores will appear here."
              : "No opportunities match the current filters."}
          </div>
        )}

        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {filtered.map((m) => (
            <MatchCard
              key={m.id}
              match={m}
              savedId={saved.savedIdFor(m.id)}
              onSavedChange={saved.set}
            />
          ))}
        </div>
      </div>
    </AuthGate>
  );
}

interface FilterSelectProps {
  id: string;
  label: string;
  value: string;
  onChange: (value: string) => void;
  options: string[];
  placeholder: string;
}

function FilterSelect({ id, label, value, onChange, options, placeholder }: FilterSelectProps) {
  return (
    <div className="flex flex-col gap-1.5">
      <Label htmlFor={id}>{label}</Label>
      <Select value={value} onValueChange={(v) => onChange(v ?? "all")}>
        <SelectTrigger id={id} className="w-full">
          <SelectValue placeholder={placeholder} />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="all">{placeholder}</SelectItem>
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
