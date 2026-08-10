"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import AuthGate from "@/components/AuthGate";
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { useToast } from "@/components/ui/toast";
import { ApiError, deleteBookmark, fetchBookmarks } from "@/lib/api";
import { ExternalLink } from "lucide-react";
import type { Bookmark } from "@/types";

type SortKey = "newest" | "oldest";

export default function BookmarksPage() {
  const [items, setItems] = useState<Bookmark[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [sort, setSort] = useState<SortKey>("newest");
  const [pending, setPending] = useState<Bookmark | null>(null);
  const [deleting, setDeleting] = useState(false);
  const { toast } = useToast();

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchBookmarks();
      setItems(data.items);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not load bookmarks");
      setItems([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load();
  }, [load]);

  const sorted = useMemo(() => {
    const list = [...items];
    list.sort((a, b) => {
      const ta = a.created_at ? new Date(a.created_at).getTime() : 0;
      const tb = b.created_at ? new Date(b.created_at).getTime() : 0;
      return sort === "newest" ? tb - ta : ta - tb;
    });
    return list;
  }, [items, sort]);

  async function confirmDelete() {
    if (!pending) return;
    setDeleting(true);
    setError(null);
    try {
      await deleteBookmark(pending.id);
      setItems((prev) => prev.filter((b) => b.id !== pending.id));
      toast("Bookmark removed", { variant: "success" });
      setPending(null);
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : "Could not remove bookmark";
      setError(msg);
      toast("Remove failed", { description: msg, variant: "destructive" });
    } finally {
      setDeleting(false);
    }
  }

  return (
    <AuthGate>
      <div className="flex flex-col gap-5">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h1 className="text-2xl font-semibold">Bookmarks</h1>
            <p className="text-sm text-muted-foreground">
              Positions you have saved from your matches.
            </p>
          </div>
          <div className="flex items-center gap-2">
            <Label htmlFor="sort" className="shrink-0 text-sm text-muted-foreground">
              Sort by
            </Label>
            <Select value={sort} onValueChange={(v) => setSort((v ?? "newest") as SortKey)}>
              <SelectTrigger id="sort" className="w-44">
                <SelectValue placeholder="Date added" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="newest">Newest first</SelectItem>
                <SelectItem value="oldest">Oldest first</SelectItem>
              </SelectContent>
            </Select>
          </div>
        </div>

        {error && <p className="text-sm text-destructive">{error}</p>}

        {loading && (
          <div className="flex flex-col gap-4">
            {Array.from({ length: 3 }).map((_, i) => (
              <Card key={i}>
                <CardHeader>
                  <Skeleton className="h-5 w-3/4" />
                  <Skeleton className="h-4 w-1/3" />
                </CardHeader>
              </Card>
            ))}
          </div>
        )}

        {!loading && sorted.length === 0 && (
          <div className="rounded-md border p-8 text-center text-sm text-muted-foreground">
            No bookmarks yet. Save matches you are interested in from the dashboard.
          </div>
        )}

        <div className="flex flex-col gap-4">
          {sorted.map((b) => (
            <Card key={b.id}>
              <CardHeader className="flex flex-row items-start justify-between gap-3">
                <div className="min-w-0">
                  <CardTitle className="text-base leading-snug">
                    {b.opportunity ? (
                      <a
                        href={b.opportunity.url ?? "#"}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="hover:underline"
                      >
                        {b.opportunity.title}
                      </a>
                    ) : (
                      `Opportunity #${b.opportunity_id}`
                    )}
                  </CardTitle>
                  <CardDescription>
                    {b.opportunity
                      ? [b.opportunity.institution, b.opportunity.country]
                          .filter(Boolean)
                          .join(" · ")
                      : ""}
                  </CardDescription>
                </div>
                <div className="flex shrink-0 items-center gap-2">
                  {b.opportunity?.url && (
                    <a
                      href={b.opportunity.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="inline-flex items-center rounded-md border border-input px-2.5 py-1.5 text-xs font-medium hover:bg-muted"
                    >
                      Original <ExternalLink className="ml-1 size-3.5" aria-hidden />
                    </a>
                  )}
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => setPending(b)}
                    aria-label={`Remove bookmark ${b.opportunity?.title ?? b.opportunity_id}`}
                  >
                    Remove
                  </Button>
                </div>
              </CardHeader>
              {b.opportunity && (
                <CardContent className="flex flex-wrap items-center gap-1.5 pt-0">
                  {b.opportunity.source && (
                    <Badge variant="outline">{b.opportunity.source}</Badge>
                  )}
                  {b.opportunity.position_type && (
                    <Badge variant="outline">{b.opportunity.position_type}</Badge>
                  )}
                  {b.opportunity.deadline && (
                    <Badge variant="outline">
                      Deadline {b.opportunity.deadline.slice(0, 10)}
                    </Badge>
                  )}
                  {b.created_at && (
                    <Badge variant="outline">
                      Added {new Date(b.created_at).toLocaleDateString()}
                    </Badge>
                  )}
                </CardContent>
              )}
            </Card>
          ))}
        </div>

        <Dialog open={pending !== null} onOpenChange={(open) => !open && setPending(null)}>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Remove bookmark?</DialogTitle>
              <DialogDescription>
                This will permanently remove
                {pending?.opportunity?.title
                  ? ` “${pending.opportunity.title}”`
                  : " this position"}{" "}
                from your bookmarks.
              </DialogDescription>
            </DialogHeader>
            <DialogFooter>
              <Button variant="outline" onClick={() => setPending(null)}>
                Cancel
              </Button>
              <Button
                variant="destructive"
                onClick={() => void confirmDelete()}
                disabled={deleting}
              >
                {deleting ? "Removing…" : "Remove"}
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </div>
    </AuthGate>
  );
}
