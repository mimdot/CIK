"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import AuthGate from "@/components/AuthGate";
import ExportResult from "@/components/ExportResult";
import SaveToggle from "@/components/SaveToggle";
import { useSavedIds } from "@/hooks/useSavedIds";
import { useFileExport } from "@/hooks/useFileExport";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { buttonVariants } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
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
import { CountryInput } from "@/components/CountryInput";
import { useRunJob } from "@/hooks/useRunJob";
import { ApiError, fetchSupervisors, fetchFields, triggerSupervisorSearch } from "@/lib/api";
import { cn } from "@/lib/utils";
import { ChevronDown, ExternalLink, Loader2, Mail, Search } from "lucide-react";
import type { Supervisor } from "@/types";

type SortKey = "fit_desc" | "fit_asc" | "name";

// --- client-side export (no server round-trip; exports what's on screen) -------
const EXPORT_COLUMNS = [
  "name", "institution", "department", "country", "fit_score",
  "fit_explanation", "source",
  "topics", "methods", "email", "orcid", "profile_url",
] as const;

function csvCell(value: unknown): string {
  const s = value == null ? "" : Array.isArray(value) ? value.join("; ") : String(value);
  return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

function supervisorsToCsv(rows: Supervisor[]): string {
  const header = EXPORT_COLUMNS.join(",");
  const body = rows.map((r) =>
    EXPORT_COLUMNS.map((c) => csvCell((r as unknown as Record<string, unknown>)[c])).join(","),
  );
  return [header, ...body].join("\n");
}


export default function SupervisorsPage() {
  const [items, setItems] = useState<Supervisor[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [totalCount, setTotalCount] = useState(0);
  const [country, setCountry] = useState("");
  const [field, setField] = useState("");
  const [fieldProfiles, setFieldProfiles] = useState<string[]>([]);
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<SortKey>("fit_desc");
  const [expanded, setExpanded] = useState<Set<number>>(new Set());
  const exp = useFileExport();
  const saved = useSavedIds("supervisor");

  const load = useCallback(
    async (c: string = country, f: string = field) => {
      setLoading(true);
      setError(null);
      try {
        const data = await fetchSupervisors(c || undefined, f || undefined);
        setItems(data.items);
        setTotalCount(data.total ?? data.items.length);
      } catch (e) {
        setError(e instanceof ApiError ? e.message : "Could not load supervisors");
        setItems([]);
        setTotalCount(0);
      } finally {
        setLoading(false);
      }
    },
    [country, field],
  );

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

  // Online search (supervisor sync) state — mirrors the positions Run engine.
  // The country/field the last run actually searched, so that when the job
  // finishes the list is re-filtered to match what the user asked for instead
  // of silently showing every stored supervisor (or the previous filter).
  const searched = useRef<{ country?: string; field?: string }>({});

  function onRunCompleted() {
    const { country: c, field: f } = searched.current;
    // Reflect the search in the filter controls, then reload with those exact
    // values (the state update alone would not re-fetch when they were
    // unchanged, yet new rows just landed).
    setCountry(c ?? "");
    setField(f ?? "");
    void load(c || undefined, f || undefined);
  }
  const run = useRunJob(onRunCompleted);
  const [formOpen, setFormOpen] = useState(false);
  const [runCountry, setRunCountry] = useState("");
  const [runField, setRunField] = useState("");

  function openRunDialog() {
    setRunCountry(country);
    setRunField(field);
    setFormOpen(true);
  }

  function startRun() {
    // Multi-country: accept a comma-separated list. Send a bare string for a
    // single country (back-compat) and an array for several — the API accepts
    // either (SupervisorRunRequest.country: str | list[str]).
    const raw = runCountry.trim() || country.trim();
    const countries = raw.split(",").map((c) => c.trim()).filter(Boolean);
    if (!countries.length) return;
    // Remember what this run searched so the list re-filters to it on
    // completion. A multi-country list cannot fit the single-country filter,
    // so it reloads the full list (which now contains those countries' rows).
    searched.current = {
      country: countries.length === 1 ? countries[0] : undefined,
      field: runField || undefined,
    };
    setFormOpen(false);
    void run.start(() =>
      triggerSupervisorSearch({
        country: countries.length === 1 ? countries[0] : countries,
        field: runField || undefined,
      }),
    );
  }

  // Declared BEFORE exportSupervisors, which closes over it. When a hoisted
  // function referenced `filtered` from above its own `const` declaration,
  // React Compiler could not preserve this memo and lint failed with
  // react-hooks/preserve-manual-memoization. `toSorted` (not `sort`) keeps the
  // memoized array immutable, which is the other half of what the rule wants.
  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    const qs = q.split(/\s+/).filter(Boolean);
    const list = items.filter((s) => {
      if (!qs.length) return true;
      const hay = `${s.name} ${s.institution ?? ""} ${s.department ?? ""} ${s.topics.join(" ")}`.toLowerCase();
      return qs.every((part) => hay.includes(part));
    });
    return list.toSorted((a, b) => {
      if (sort === "name") return a.name.localeCompare(b.name);
      if (sort === "fit_asc") return (a.fit_score ?? 0) - (b.fit_score ?? 0);
      return (b.fit_score ?? 0) - (a.fit_score ?? 0);
    });
  }, [items, query, sort]);

  // Exports exactly `filtered` — the same memoized, searched-and-sorted list
  // the cards below are rendered from — so what lands in the file is what the
  // user is looking at, not a second unfiltered query.
  function exportSupervisors(format: "csv" | "json") {
    if (!filtered.length) return;
    const suffix = country ? `_${country.replace(/\s+/g, "_")}` : "";
    void (format === "csv"
      ? exp.exportFile({
          suggestedName: `supervisors${suffix}.csv`,
          contents: supervisorsToCsv(filtered),
          mime: "text/csv;charset=utf-8",
        })
      : exp.exportFile({
          suggestedName: `supervisors${suffix}.json`,
          contents: JSON.stringify(filtered, null, 2),
          mime: "application/json",
        }));
  }

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
        <CountryInput id="country" value={country} onChange={setCountry} />
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="field">Field profile</Label>
          <Select value={field} onValueChange={(v) => setField(v ?? "")}>
            <SelectTrigger id="field" className="w-full">
              <SelectValue placeholder="Select field profile" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="">All fields</SelectItem>
              {fieldProfiles.map((f) => (
                <SelectItem key={f} value={f}>
                  {f}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>

      <ExportResult
        saved={exp.saved}
        error={exp.error}
        onDismiss={exp.dismiss}
        onReveal={exp.reveal}
        onOpen={exp.open}
      />

      <div className="flex flex-wrap items-center justify-between gap-3">
        <Button variant="outline" onClick={() => void load()}>
          Apply filters
        </Button>
        <div className="flex flex-wrap items-center gap-2">
          <Button onClick={openRunDialog} disabled={run.busy}>
            {run.busy ? "Searching online…" : "Run online search"}
          </Button>
          <Button
            variant="outline"
            onClick={() => exportSupervisors("csv")}
            disabled={!filtered.length}
          >
            Export CSV
          </Button>
          <Button
            variant="outline"
            onClick={() => exportSupervisors("json")}
            disabled={!filtered.length}
          >
            Export JSON
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
      </div>

      <Dialog open={formOpen} onOpenChange={(open) => setFormOpen(open)}>
        <DialogContent showCloseButton={!run.busy}>
          <DialogHeader>
            <DialogTitle>Run online supervisor search</DialogTitle>
            <DialogDescription>
              Fetches new supervisor candidates from the literature sources
              (OpenAlex / arXiv / ADS) and ranks them by fit to your profile.
            </DialogDescription>
          </DialogHeader>
          <div className="grid gap-3">
            <div className="flex flex-col gap-1.5">
              <CountryInput
                id="run-country"
                value={runCountry}
                onChange={setRunCountry}
                placeholder="e.g. Germany, Netherlands"
              />
              <p className="text-xs text-muted-foreground">
                One country, or several separated by commas.
              </p>
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="run-field">Field profile</Label>
              <Select value={runField} onValueChange={(v) => setRunField(v ?? "")}>
                <SelectTrigger id="run-field" className="w-full">
                  <SelectValue placeholder="All fields" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="">All fields</SelectItem>
                  {fieldProfiles.map((f) => (
                    <SelectItem key={f} value={f}>
                      {f}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <p className="text-xs text-muted-foreground">
              Astronomy &amp; physics rank best from NASA ADS when an{" "}
              <code>ADS_API_TOKEN</code> is configured (free at{" "}
              <a
                href="https://ui.adsabs.harvard.edu/user/settings/token"
                target="_blank"
                rel="noopener noreferrer"
                className="underline"
              >
                ADS settings
              </a>
              ). Without a token the search automatically uses OpenAlex, which
              covers every field and needs no token.
            </p>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setFormOpen(false)}>
              Cancel
            </Button>
            <Button
              onClick={startRun}
              disabled={!(runCountry.trim() || country.trim())}
            >
              Start search
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog
        open={run.open}
        onOpenChange={(open) => {
          if (!open && run.status !== "starting" && !run.busy) run.close();
        }}
      >
        <DialogContent showCloseButton={run.status !== "starting" && !run.busy}>
          <DialogHeader>
            <DialogTitle>Supervisor search</DialogTitle>
            <DialogDescription>
              {run.status === "starting" && "Starting the search…"}
              {run.status === "running" &&
                (run.cancelling
                  ? "Stopping — finishing the field in flight…"
                  : "Searching literature for candidates…")}
              {run.status === "cancelled" && "Search stopped."}
              {run.status === "completed" && "Search completed."}
              {run.status === "failed" && "Search failed."}
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
            {run.busy && run.progress?.stage && (
              <p
                className="truncate font-mono text-xs text-muted-foreground"
                data-testid="run-stage"
              >
                {run.progress.stage}
              </p>
            )}
            {run.busy && (
              <div className="flex items-center justify-between gap-3">
                <span className="text-muted-foreground">Finding candidates</span>
                <span
                  className="flex items-center gap-1.5 tabular-nums"
                  data-testid="run-elapsed"
                >
                  <Loader2 className="size-4 animate-spin" aria-hidden />
                  {run.elapsed}s elapsed
                </span>
              </div>
            )}
            {run.progress && run.progress.total > 0 && (
              <div className="flex flex-col gap-1">
                <div className="flex items-center justify-between gap-3">
                  <span className="text-muted-foreground">Supervisors found</span>
                  <span className="tabular-nums" data-testid="run-progress-count">
                    {run.progress.completed} / {run.progress.total}
                  </span>
                </div>
                {/* One row per field x country pair as it lands. This is the
                    difference between "the engine is working" and "the engine
                    is wedged", which an elapsed counter alone cannot tell you.
                    States are drawn with weight and words, not a second hue —
                    the palette has one accent and no status colours. */}
                <ul
                  className="max-h-40 overflow-y-auto border p-2 text-xs"
                  data-testid="run-progress-list"
                >
                  {run.progress.sources.map((sp) => (
                    <li
                      key={sp.source}
                      className="flex items-center justify-between gap-2 py-0.5"
                    >
                      <span className="truncate">{sp.source}</span>
                      <span
                        className={
                          sp.status === "error"
                            ? "text-destructive"
                            : sp.records > 0
                              ? "font-bold tabular-nums"
                              : "text-muted-foreground tabular-nums"
                        }
                      >
                        {sp.status === "error" ? "failed" : sp.records}
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {run.reconnecting && (
              <p
                className="text-xs text-muted-foreground"
                data-testid="run-reconnecting"
              >
                Lost contact with the backend — retrying. The search is still
                running; it does not happen in this window.
              </p>
            )}
            {run.status === "cancelled" && (
              <p className="border p-2 text-muted-foreground">
                Search stopped. The supervisors found before you stopped it have
                been kept and are listed below.
              </p>
            )}
            {run.records != null && (
              <div className="flex items-center justify-between gap-3">
                <span className="text-muted-foreground">Candidates found</span>
                <span className="tabular-nums" data-testid="run-records">
                  {run.records}
                </span>
              </div>
            )}
            {run.error && (
              <p className="rounded-md border border-destructive/30 bg-destructive/10 p-2 text-destructive">
                {run.error}
              </p>
            )}
            <p className="text-muted-foreground">
              This can take a few minutes while sources are polled.
            </p>
          </div>
          <DialogFooter showCloseButton={run.status !== "starting" && !run.busy}>
            {/* Stop is cooperative: the field in flight finishes, nothing new
                starts, and every supervisor already saved is kept. Without
                this a long search could only be escaped by killing the app. */}
            {run.busy && (
              <Button
                variant="outline"
                onClick={() => void run.cancel()}
                disabled={run.cancelling}
              >
                {run.cancelling ? "Stopping…" : "Stop search"}
              </Button>
            )}
            {(run.status === "completed" || run.status === "cancelled") && (
              <Button onClick={() => run.close()}>Done</Button>
            )}
          </DialogFooter>
        </DialogContent>
      </Dialog>

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

      {!loading && (
        <p className="text-sm text-muted-foreground">
          Showing {filtered.length} of {totalCount} supervisors
          {country && ` in ${country}`}
          {field && ` (field: ${field})`}
        </p>
      )}

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {filtered.map((s) => {
          const isOpen = expanded.has(s.id);
          return (
            <Card key={s.id} className="flex flex-col">
              <CardHeader>
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <CardTitle className="text-base">{s.name}</CardTitle>
                    <CardDescription>
                      {[s.institution, s.department, s.country].filter(Boolean).join(" · ") ||
                        "Institution n/a"}
                    </CardDescription>
                  </div>
                  <SaveToggle
                    kind="supervisor"
                    recordId={s.id}
                    savedId={saved.savedIdFor(s.id)}
                    onChange={({ savedId }) => saved.set(s.id, savedId)}
                  />
                </div>
              </CardHeader>
              <CardContent className="mt-auto flex flex-col gap-2 pt-0">
                <div className="flex flex-wrap items-center gap-2">
                  {s.fit_score != null && (
                    // fit_score is ALREADY 0-100. It used to be multiplied by
                    // 100 and shown as a percentage, so an unbounded raw score
                    // of 43 rendered as "Fit 4300%" — a large part of why the
                    // value looked nonsensical.
                    <Badge
                      data-testid="fit-score"
                      title={s.fit_explanation ?? undefined}
                    >
                      Fit {Math.round(s.fit_score)} / 100
                    </Badge>
                  )}
                  {s.source && <Badge variant="outline">{s.source}</Badge>}
                </div>

                {/* Never a bare number: expanding a card shows how the score
                    was arrived at, component by component. */}
                {isOpen && s.fit_explanation && (
                  <p
                    className="rounded-md border bg-muted/40 p-2 text-xs text-muted-foreground"
                    data-testid="fit-explanation"
                  >
                    {s.fit_explanation}
                  </p>
                )}

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
