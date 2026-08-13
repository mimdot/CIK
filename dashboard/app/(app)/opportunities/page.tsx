"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useRunJob } from "@/hooks/useRunJob";
import { ApiError, fetchFields, fetchOpportunities, triggerPipeline } from "@/lib/api";
import type { Opportunity } from "@/types";

const PAGE_SIZE = 12;

export default function OpportunitiesPage() {
  const [items, setItems] = useState<Opportunity[]>([]);
  const [total, setTotal] = useState(0);
  const [pages, setPages] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const [country, setCountry] = useState("");
  const [source, setSource] = useState("");
  const [type, setType] = useState("");

  // Field profile to crawl/score under when running the engine (empty = server
  // default). Populated from GET /api/fields so the list is data, not code.
  const [field, setField] = useState("");
  const [fieldProfiles, setFieldProfiles] = useState<string[]>([]);

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

  // Field profiles for the run-scope dropdown.
  useEffect(() => {
    fetchFields()
      .then((data) => setFieldProfiles(data.profiles))
      .catch(() => setFieldProfiles([]));
  }, []);

  // Run-engine state (Phase 1: easy to run the engine from the UI).
  function onRunCompleted(records: number | null) {
    setNotice(
      `Engine run finished — ${records ?? 0} records${field ? ` (${field})` : ""}. Data refreshed.`,
    );
    void load();
  }
  const run = useRunJob(onRunCompleted);

  function handleRunEngine() {
    setNotice(null);
    // Scope the crawl to the active country filter (worldwide when unset) and
    // the chosen field profile (server default when unset).
    const scope = country.trim();
    void run.start(() =>
      triggerPipeline({
        country: scope || undefined,
        field: field || undefined,
      }),
    );
  }

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
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold">Opportunities</h1>
          <p className="text-sm text-muted-foreground">
            {loading ? "Loading…" : `${total} open positions.`}
          </p>
        </div>
        <div className="flex items-end gap-2">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="run-field">Field to crawl</Label>
            <Select value={field} onValueChange={(v) => setField(v ?? "")}>
              <SelectTrigger id="run-field" className="w-48">
                <SelectValue placeholder="Server default" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="">Server default</SelectItem>
                {fieldProfiles.map((f) => (
                  <SelectItem key={f} value={f}>
                    {f}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <Button onClick={() => void handleRunEngine()} disabled={run.busy}>
            {run.busy ? "Running engine…" : "Run engine"}
          </Button>
        </div>
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
      {notice && <p className="text-sm text-emerald-600">{notice}</p>}

      {!loading && items.length === 0 && (
        <div className="rounded-md border p-8 text-center text-sm text-muted-foreground">
          <p className="mb-3">No opportunities yet.</p>
          <Button onClick={() => void handleRunEngine()} disabled={run.busy}>
            {run.busy ? "Running engine…" : "Run the engine to discover positions"}
          </Button>
        </div>
      )}

      <Dialog
        open={run.open}
        onOpenChange={(open) => {
          if (!open && run.status !== "starting" && !run.busy) run.close();
        }}
      >
        <DialogContent showCloseButton={run.status !== "starting" && !run.busy}>
          <DialogHeader>
            <DialogTitle>Engine run</DialogTitle>
            <DialogDescription>
              {run.status === "starting" && "Starting the data engine…"}
              {run.status === "running" && "Aggregating opportunities from sources…"}
              {run.status === "completed" && "Run completed."}
              {run.status === "failed" && "Run failed."}
            </DialogDescription>
          </DialogHeader>
          <div className="flex flex-col gap-2 text-sm">
            <div className="flex items-center justify-between gap-3">
              <span className="text-muted-foreground">Status</span>
              <Badge
                variant={
                  run.status === "completed"
                    ? "secondary"
                    : run.status === "failed"
                      ? "destructive"
                      : "outline"
                }
                data-testid="run-status"
              >
                {run.status ?? "idle"}
              </Badge>
            </div>
            {run.records != null && (
              <div className="flex items-center justify-between gap-3">
                <span className="text-muted-foreground">Records found</span>
                <span className="tabular-nums" data-testid="run-records">
                  {run.records}
                </span>
              </div>
            )}
            {run.progress && run.progress.total > 0 && (
              <div className="flex flex-col gap-1">
                <div className="flex items-center justify-between gap-3">
                  <span className="text-muted-foreground">Sources</span>
                  <span className="tabular-nums" data-testid="run-progress-count">
                    {run.progress.completed} / {run.progress.total}
                  </span>
                </div>
                <ul className="max-h-40 overflow-y-auto rounded-md border p-2 text-xs">
                  {run.progress.sources.map((s) => (
                    <li
                      key={s.source}
                      className="flex items-center justify-between gap-2 py-0.5"
                    >
                      <span className="truncate">{s.source}</span>
                      <span
                        className={
                          s.status === "error"
                            ? "text-destructive"
                            : "text-emerald-600"
                        }
                      >
                        {s.status === "error" ? "error" : `${s.records}`}
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {run.error && (
              <p className="rounded-md border border-destructive/30 bg-destructive/10 p-2 text-destructive">
                {run.error}
              </p>
            )}
            <p className="text-muted-foreground">
              This can take a minute or two while sources are polled.
            </p>
          </div>
          <DialogFooter showCloseButton={run.status !== "starting" && !run.busy}>
            {run.status === "completed" && (
              <Button onClick={() => run.close()}>Done</Button>
            )}
          </DialogFooter>
        </DialogContent>
      </Dialog>

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
  const id = `filter-${label.toLowerCase()}`;
  return (
    <div className="flex flex-col gap-1.5">
      <Label htmlFor={id}>{label}</Label>
      <Select value={value} onValueChange={(v) => onChange(v ?? "")}>
        <SelectTrigger id={id} className="w-full">
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
