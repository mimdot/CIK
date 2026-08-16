"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import AuthGate from "@/components/AuthGate";
import ExportResult from "@/components/ExportResult";
import { Badge } from "@/components/ui/badge";
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
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { useToast } from "@/components/ui/toast";
import { useFileExport } from "@/hooks/useFileExport";
import { ApiError, deleteSaved, fetchSaved, updateSaved } from "@/lib/api";
import type { SavedItem, SavedKind, SavedStatus } from "@/types";

type SortKey = "newest" | "oldest" | "title";

const STATUSES: { value: SavedStatus; label: string }[] = [
  { value: "interested", label: "Interested" },
  { value: "applied", label: "Applied" },
  { value: "rejected", label: "Rejected" },
];

const TABS: { kind: SavedKind; label: string }[] = [
  { kind: "opportunity", label: "Opportunities" },
  { kind: "supervisor", label: "Supervisors" },
];

/** The headline for a saved record, whichever kind it is. */
function titleOf(item: SavedItem): string {
  const r = item.record;
  return String(r.title ?? r.name ?? "(untitled)");
}

/** The line under the title: where it is, and who it is with. */
function subtitleOf(item: SavedItem): string {
  const r = item.record;
  return [r.institution, r.department, r.country]
    .filter(Boolean)
    .map(String)
    .join(" · ");
}

function urlOf(item: SavedItem): string | null {
  const r = item.record;
  const url = r.url ?? r.profile_url;
  return typeof url === "string" && url ? url : null;
}

function toCsv(items: SavedItem[]): string {
  const cols = ["title", "institution", "country", "url", "status", "note",
                "still_listed", "saved_at"];
  const cell = (v: unknown) => {
    const s = v == null ? "" : String(v);
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  const rows = items.map((i) =>
    [
      titleOf(i),
      i.record.institution ?? "",
      i.record.country ?? "",
      urlOf(i) ?? "",
      i.status,
      i.note ?? "",
      i.still_listed ? "yes" : "no longer listed",
      i.created_at ?? "",
    ].map(cell).join(","),
  );
  return [cols.join(","), ...rows].join("\n");
}

export default function SavedPage() {
  const [kind, setKind] = useState<SavedKind>("opportunity");
  const [items, setItems] = useState<Record<SavedKind, SavedItem[]>>({
    opportunity: [],
    supervisor: [],
  });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<SortKey>("newest");
  const [editing, setEditing] = useState<number | null>(null);
  const [draftNote, setDraftNote] = useState("");
  const { toast } = useToast();
  const exp = useFileExport();

  // Both tabs are loaded up front so the counts on the tabs are real from the
  // first paint — a count that appears only after you click the tab is not a
  // count, it is a surprise.
  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [opps, sups] = await Promise.all([
        fetchSaved("opportunity"),
        fetchSaved("supervisor"),
      ]);
      setItems({ opportunity: opps.items, supervisor: sups.items });
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not load saved items");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load();
  }, [load]);

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase();
    const list = items[kind].filter((i) => {
      if (!q) return true;
      return `${titleOf(i)} ${subtitleOf(i)} ${i.note ?? ""}`
        .toLowerCase()
        .includes(q);
    });
    return list.toSorted((a, b) => {
      if (sort === "title") return titleOf(a).localeCompare(titleOf(b));
      const at = a.created_at ?? "";
      const bt = b.created_at ?? "";
      return sort === "oldest" ? at.localeCompare(bt) : bt.localeCompare(at);
    });
  }, [items, kind, query, sort]);

  function replace(next: SavedItem) {
    setItems((prev) => ({
      ...prev,
      [next.kind]: prev[next.kind].map((i) => (i.id === next.id ? next : i)),
    }));
  }

  async function remove(item: SavedItem) {
    try {
      await deleteSaved(item.id);
      setItems((prev) => ({
        ...prev,
        [item.kind]: prev[item.kind].filter((i) => i.id !== item.id),
      }));
      toast("Removed from saved", { variant: "success" });
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : "Could not remove";
      toast("Could not remove", { description: msg, variant: "destructive" });
    }
  }

  async function setStatus(item: SavedItem, status: SavedStatus) {
    try {
      replace(await updateSaved(item.id, { status }));
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : "Could not update";
      toast("Could not update", { description: msg, variant: "destructive" });
    }
  }

  async function saveNote(item: SavedItem) {
    try {
      replace(await updateSaved(item.id, { note: draftNote }));
      setEditing(null);
      toast("Note saved", { variant: "success" });
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : "Could not save the note";
      toast("Could not save the note", { description: msg, variant: "destructive" });
    }
  }

  function exportSaved(format: "csv" | "json") {
    if (!visible.length) return;
    void (format === "csv"
      ? exp.exportFile({
          suggestedName: `saved-${kind}s.csv`,
          contents: toCsv(visible),
          mime: "text/csv;charset=utf-8",
        })
      : exp.exportFile({
          suggestedName: `saved-${kind}s.json`,
          contents: JSON.stringify(visible, null, 2),
          mime: "application/json",
        }));
  }

  return (
    <AuthGate>
      <div className="flex flex-col gap-5">
        <div>
          <h1 className="text-2xl font-semibold">Saved</h1>
          <p className="text-sm text-muted-foreground">
            Positions and supervisors you kept. Each one stores a copy of what
            it looked like when you saved it, so it still reads correctly even
            after the original posting comes down.
          </p>
        </div>

        {/* Two clearly separated sections, each with its real count. */}
        <div role="tablist" aria-label="Saved items" className="flex gap-2">
          {TABS.map((tab) => (
            <button
              key={tab.kind}
              role="tab"
              aria-selected={kind === tab.kind}
              onClick={() => setKind(tab.kind)}
              className={
                kind === tab.kind
                  ? "rounded-md bg-primary/10 px-3 py-1.5 text-sm font-medium text-primary"
                  : "rounded-md px-3 py-1.5 text-sm font-medium text-muted-foreground hover:bg-muted"
              }
            >
              {tab.label}{" "}
              <span className="tabular-nums">({items[tab.kind].length})</span>
            </button>
          ))}
        </div>

        <ExportResult
          saved={exp.saved}
          error={exp.error}
          onDismiss={exp.dismiss}
          onReveal={exp.reveal}
          onOpen={exp.open}
        />

        <div className="flex flex-wrap items-end gap-3">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="saved-search">Search</Label>
            <Input
              id="saved-search"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="title, institution, note…"
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="saved-sort">Sort</Label>
            <Select
              value={sort}
              onValueChange={(v) => setSort((v ?? "newest") as SortKey)}
            >
              <SelectTrigger id="saved-sort" className="w-48">
                <SelectValue placeholder="Newest first" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="newest">Newest first</SelectItem>
                <SelectItem value="oldest">Oldest first</SelectItem>
                <SelectItem value="title">Title A–Z</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div className="flex gap-2">
            <Button
              variant="outline"
              onClick={() => exportSaved("csv")}
              disabled={!visible.length}
            >
              Export CSV
            </Button>
            <Button
              variant="outline"
              onClick={() => exportSaved("json")}
              disabled={!visible.length}
            >
              Export JSON
            </Button>
          </div>
        </div>

        {error && (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        )}

        {loading && <Skeleton className="h-24 w-full" />}

        {!loading && !visible.length && (
          <div className="rounded-md border p-8 text-center text-sm text-muted-foreground">
            {items[kind].length
              ? "Nothing matches that search."
              : `No saved ${kind === "opportunity" ? "positions" : "supervisors"} yet — press the star on any card.`}
          </div>
        )}

        <div className="flex flex-col gap-3">
          {visible.map((item) => (
            <Card key={item.id} data-testid="saved-card">
              <CardContent className="flex flex-col gap-3 p-4">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <h2 className="text-base font-medium">{titleOf(item)}</h2>
                      {!item.still_listed && (
                        <Badge
                          variant="outline"
                          className="text-destructive"
                          data-testid="delisted"
                        >
                          No longer listed
                        </Badge>
                      )}
                    </div>
                    <p className="text-sm text-muted-foreground">
                      {subtitleOf(item)}
                    </p>
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    <Select
                      value={item.status}
                      onValueChange={(v) =>
                        void setStatus(item, (v ?? "interested") as SavedStatus)
                      }
                    >
                      <SelectTrigger
                        className="w-36"
                        aria-label={`Status for ${titleOf(item)}`}
                      >
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {STATUSES.map((s) => (
                          <SelectItem key={s.value} value={s.value}>
                            {s.label}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                    {urlOf(item) && (
                      <a
                        href={urlOf(item)!}
                        className="text-sm underline underline-offset-4"
                      >
                        Open
                      </a>
                    )}
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => void remove(item)}
                      aria-label={`Remove ${titleOf(item)} from saved`}
                    >
                      Remove
                    </Button>
                  </div>
                </div>

                {editing === item.id ? (
                  <div className="flex flex-col gap-2">
                    <Label htmlFor={`note-${item.id}`}>Note</Label>
                    <Textarea
                      id={`note-${item.id}`}
                      rows={3}
                      value={draftNote}
                      onChange={(e) => setDraftNote(e.target.value)}
                    />
                    <div className="flex gap-2">
                      <Button size="sm" onClick={() => void saveNote(item)}>
                        Save note
                      </Button>
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => setEditing(null)}
                      >
                        Cancel
                      </Button>
                    </div>
                  </div>
                ) : (
                  <button
                    type="button"
                    className="text-left text-sm text-muted-foreground underline-offset-4 hover:underline"
                    onClick={() => {
                      setEditing(item.id);
                      setDraftNote(item.note ?? "");
                    }}
                  >
                    {item.note ? item.note : "Add a note"}
                  </button>
                )}
              </CardContent>
            </Card>
          ))}
        </div>
      </div>
    </AuthGate>
  );
}
