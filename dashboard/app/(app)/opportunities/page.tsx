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
import { DepartmentBrowser } from "@/components/DepartmentBrowser";
import { FieldPicker } from "@/components/FieldPicker";
import { RunFunnelSummary } from "@/components/RunFunnelSummary";
import { useRunJob } from "@/hooks/useRunJob";
import { ApiError, fetchOpportunities, triggerPipeline } from "@/lib/api";
import type { Opportunity } from "@/types";

const PAGE_SIZE = 12;

function formatElapsed(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return m > 0 ? `${m}m ${String(s).padStart(2, "0")}s` : `${s}s`;
}

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

  // The field (and optionally subfields) this page is scoped to. Drives BOTH
  // what a run crawls and which stored rows are listed, so the results shown
  // always belong to the discipline that is selected.
  const [field, setField] = useState("");
  const [subfields, setSubfields] = useState<string[]>([]);
  // The exhaustive department sweep is opt-in (2B) — it adds minutes.
  const [includeSlow, setIncludeSlow] = useState(false);
  const [browseOpen, setBrowseOpen] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchOpportunities({
        country: country || undefined,
        source: source || undefined,
        type: type || undefined,
        // Scope the list to the selected field, so switching to chemistry
        // cannot keep showing astronomy rows stored by an earlier run.
        field: field || undefined,
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
  }, [country, source, type, field, page]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load();
  }, [load]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setPage(1);
  }, [country, source, type, field]);

  // Run-engine state (Phase 1: easy to run the engine from the UI).
  // The notice deliberately does NOT quote a second, differently-derived
  // count. The engine's per-stage breakdown is rendered by RunFunnelSummary,
  // and the headline "N open positions" below comes from the same filtered
  // dataset the list does — the two can no longer disagree.
  function onRunCompleted() {
    setNotice(
      `Search finished${field ? ` for ${field}` : ""}. Showing the results below.`,
    );
    void load();
  }
  // Cancelling reloads through the same path, so partial results appear in the
  // list exactly like a full run's.
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
        subfields: subfields.length ? subfields : undefined,
        include_slow: includeSlow || undefined,
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
            {loading
              ? "Loading…"
              : `${total} open position${total === 1 ? "" : "s"}${
                  field ? ` in ${field}` : ""
                }.`}
          </p>
        </div>
        <Button onClick={() => void handleRunEngine()} disabled={run.busy}>
          {run.busy ? "Searching…" : "Search for positions"}
        </Button>
      </div>

      <FieldPicker
        field={field}
        onFieldChange={setField}
        subfields={subfields}
        onSubfieldsChange={setSubfields}
        idPrefix="run-field"
        hint="Sets which job boards are searched, with your field's own keywords. Subfields push matching positions to the top."
      />

      {/* 2B — the exhaustive department sweep is OFF unless asked for, and
          says what it costs. The instant manual alternative sits beside it. */}
      <div className="rounded-lg border bg-card p-4 text-sm">
        <label className="flex cursor-pointer items-start gap-2.5">
          <input
            type="checkbox"
            checked={includeSlow}
            onChange={(e) => setIncludeSlow(e.target.checked)}
            className="mt-0.5 size-4"
            aria-label="Also sweep university department pages"
          />
          <span>
            <span className="font-medium">
              Also sweep university department pages
            </span>
            <span className="block text-xs text-muted-foreground">
              Off by default. Visits every department in your field&apos;s list
              one at a time at a polite 2-second delay — about 150 pages for
              astronomy and 20 for most fields, so it adds{" "}
              <strong>several minutes</strong> to a search. It finds openings
              the job boards miss.
            </span>
          </span>
        </label>
        <button
          type="button"
          className="mt-2 text-xs font-medium underline-offset-4 hover:underline"
          onClick={() => setBrowseOpen((v) => !v)}
          aria-expanded={browseOpen}
        >
          {browseOpen ? "Hide" : "Or browse"} the department list yourself
          (instant)
        </button>
        {browseOpen && (
          <div className="mt-3">
            <DepartmentBrowser field={field} />
          </div>
        )}
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
              {run.status === "running" &&
                (run.cancelling
                  ? "Stopping — finishing the source in flight…"
                  : "Aggregating opportunities from sources…")}
              {run.status === "completed" && "Run completed."}
              {run.status === "cancelled" && "Search cancelled."}
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
                            : s.status === "skipped"
                              ? "text-muted-foreground"
                              : "text-emerald-600"
                        }
                      >
                        {s.status === "error"
                          ? "error"
                          : s.status === "skipped"
                            ? "skipped"
                            : `${s.records}`}
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {run.progress?.funnel && (
              <RunFunnelSummary funnel={run.progress.funnel} />
            )}
            {run.error && (
              <p className="rounded-md border border-destructive/30 bg-destructive/10 p-2 text-destructive">
                {run.error}
              </p>
            )}
            {run.busy && (
              <div className="flex items-center justify-between gap-3">
                <span className="text-muted-foreground">Elapsed</span>
                <span className="tabular-nums" data-testid="run-elapsed">
                  {formatElapsed(run.elapsed)}
                </span>
              </div>
            )}
            {run.status === "cancelled" && (
              <p className="rounded-md border bg-muted/50 p-2 text-muted-foreground">
                Search stopped. The positions found before you cancelled have
                been kept and are listed below.
              </p>
            )}
            <p className="text-muted-foreground">
              This can take a minute or two while sources are polled. You can
              cancel at any time and keep what has been found so far.
            </p>
          </div>
          <DialogFooter showCloseButton={run.status !== "starting" && !run.busy}>
            {run.busy && (
              <Button
                variant="outline"
                onClick={() => void run.cancel()}
                disabled={run.cancelling || run.status === "starting"}
              >
                {run.cancelling ? "Stopping…" : "Cancel search"}
              </Button>
            )}
            {(run.status === "completed" || run.status === "cancelled") && (
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
