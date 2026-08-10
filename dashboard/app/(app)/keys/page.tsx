"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import AuthGate from "@/components/AuthGate";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
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
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import { useToast } from "@/components/ui/toast";
import {
  ApiError,
  createKey,
  fetchKeyUsage,
  fetchKeys,
  revokeKey,
  rotateKey,
} from "@/lib/api";
import { Copy, KeyRound, RefreshCw, ShieldX } from "lucide-react";
import type { ApiKey, ApiKeyCreateResult, ApiKeyUsage } from "@/types";

const ALL_SCOPES = [
  "read:profile",
  "read:matches",
  "read:opportunities",
  "read:supervisors",
  "write:bookmarks",
  "write:feedback",
];

function relativeTime(iso: string | null): string {
  if (!iso) return "never";
  const then = new Date(iso).getTime();
  const ms = Date.now() - then;
  const mins = Math.max(1, Math.round(ms / 60_000));
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.round(hours / 24);
  return `${days}d ago`;
}

function UsageChart({ usage }: { usage: ApiKeyUsage }) {
  const days = useMemo(() => usage.items.slice(-14).reverse(), [usage]);
  const max = Math.max(1, ...days.map((d) => d.requests));
  if (days.length === 0) {
    return <p className="text-xs text-muted-foreground">No usage yet.</p>;
  }
  return (
    <div className="flex h-24 items-end gap-1" role="img" aria-label="Requests per day, last 14 days">
      {days.map((d) => (
        <div key={d.date} className="flex flex-1 flex-col items-center gap-1">
          <div
            className="w-full rounded-sm bg-primary/80"
            style={{ height: `${Math.max(4, (d.requests / max) * 96)}px` }}
            aria-label={`${d.date}: ${d.requests} requests`}
            title={`${d.date}: ${d.requests} requests`}
          />
        </div>
      ))}
    </div>
  );
}

export default function ApiKeysPage() {
  const { toast } = useToast();
  const [keys, setKeys] = useState<ApiKey[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // create flow
  const [createOpen, setCreateOpen] = useState(false);
  const [name, setName] = useState("");
  const [scopes, setScopes] = useState<string[]>(ALL_SCOPES);
  const [saving, setSaving] = useState(false);
  const [fresh, setFresh] = useState<ApiKeyCreateResult | null>(null);

  const [usageFor, setUsageFor] = useState<{ key: ApiKey; usage: ApiKeyUsage } | null>(null);
  const [revokeTarget, setRevokeTarget] = useState<ApiKey | null>(null);
  const [rotateTarget, setRotateTarget] = useState<ApiKey | null>(null);
  const [confirming, setConfirming] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setKeys(await fetchKeys());
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not load API keys");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load();
  }, [load]);

  function toggleScope(scope: string) {
    setScopes((prev) =>
      prev.includes(scope) ? prev.filter((s) => s !== scope) : [...prev, scope],
    );
  }

  async function handleCreate() {
    if (!name.trim() || saving) return;
    setSaving(true);
    setError(null);
    try {
      const created = await createKey({ name: name.trim(), scopes });
      setFresh(created);
      setCreateOpen(false);
      setName("");
      await load();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not create key");
      toast("Create failed", {
        description: e instanceof ApiError ? e.message : undefined,
        variant: "destructive",
      });
    } finally {
      setSaving(false);
    }
  }

  async function copyKey(raw: string) {
    try {
      await navigator.clipboard.writeText(raw);
    } catch {
      /* clipboard unavailable — user can select the text manually */
    }
    toast("Key copied", {
      description: "Store it somewhere safe — it won't be shown again.",
      variant: "success",
    });
  }

  async function openUsage(key: ApiKey) {
    try {
      const usage = await fetchKeyUsage(key.id, 14);
      setUsageFor({ key, usage });
    } catch (e) {
      toast("Could not load usage", {
        description: e instanceof ApiError ? e.message : undefined,
        variant: "destructive",
      });
    }
  }

  async function handleRevoke() {
    if (!revokeTarget || confirming) return;
    setConfirming(true);
    try {
      await revokeKey(revokeTarget.id);
      toast("Key revoked", { variant: "success" });
      setRevokeTarget(null);
      await load();
    } catch (e) {
      toast("Revoke failed", {
        description: e instanceof ApiError ? e.message : undefined,
        variant: "destructive",
      });
    } finally {
      setConfirming(false);
    }
  }

  async function handleRotate() {
    if (!rotateTarget || confirming) return;
    setConfirming(true);
    try {
      const rotated = await rotateKey(rotateTarget.id);
      setFresh(rotated);
      setRotateTarget(null);
      await load();
    } catch (e) {
      toast("Rotate failed", {
        description: e instanceof ApiError ? e.message : undefined,
        variant: "destructive",
      });
    } finally {
      setConfirming(false);
    }
  }

  const active = keys.filter((k) => !k.revoked_at);
  const revoked = keys.filter((k) => k.revoked_at);

  return (
    <AuthGate>
      <div className="flex flex-col gap-5">
        <div className="flex items-start justify-between gap-3">
          <div>
            <h1 className="flex items-center gap-2 text-2xl font-semibold">
              <KeyRound className="h-5 w-5" />
              API Keys
            </h1>
            <p className="text-sm text-muted-foreground">
              Scoped, rate-limited keys for integrating with the public
              <code className="mx-1 rounded bg-muted px-1">/api/v1</code>
              API. Keys are shown exactly once at creation.
            </p>
          </div>
          <Button onClick={() => setCreateOpen(true)} disabled={loading}>
            Create API key
          </Button>
        </div>

        {error && <p className="text-sm text-destructive">{error}</p>}

        <Card>
          <CardHeader>
            <CardTitle className="text-base">Developer keys</CardTitle>
            <CardDescription>
              {active.length} active — daily quota unlimited unless an admin
              sets a cap.
            </CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-3">
            {loading ? (
              <div className="flex flex-col gap-3">
                <Skeleton className="h-16 w-full" />
                <Skeleton className="h-16 w-full" />
              </div>
            ) : keys.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                No API keys yet — create one to start integrating.
              </p>
            ) : (
              active.map((key) => (
                <div
                  key={key.id}
                  className="rounded-lg border p-3"
                  data-testid="key-row"
                >
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-medium text-foreground">{key.name}</span>
                    <Badge variant="outline" className="font-mono text-xs">
                      {key.key_prefix}…
                    </Badge>
                    <Badge variant="secondary">{key.scopes.length} scopes</Badge>
                    <span className="text-xs text-muted-foreground">
                      Last used {relativeTime(key.last_used_at)}
                    </span>
                    <div className="ml-auto flex items-center gap-1">
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => void openUsage(key)}
                      >
                        Usage
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        aria-label={`Rotate ${key.name}`}
                        onClick={() => setRotateTarget(key)}
                      >
                        <RefreshCw className="h-4 w-4" />
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        className="text-destructive"
                        aria-label={`Revoke ${key.name}`}
                        onClick={() => setRevokeTarget(key)}
                      >
                        <ShieldX className="h-4 w-4" />
                      </Button>
                    </div>
                  </div>
                  <div className="mt-2 flex flex-wrap gap-1">
                    {key.scopes.map((s) => (
                      <Badge key={s} variant="default" className="text-xs">
                        {s}
                      </Badge>
                    ))}
                  </div>
                  {usageFor?.key.id === key.id && (
                    <div className="mt-3">
                      <Separator className="mb-3" />
                      <UsageChart usage={usageFor.usage} />
                      <p className="mt-1 text-xs text-muted-foreground">
                        Daily quota: {usageFor.usage.quota_limit ?? "unlimited"} ·
                        Rate limit: {usageFor.usage.rate_limit ?? "60"}/min
                      </p>
                    </div>
                  )}
                </div>
              ))
            )}

            {revoked.length > 0 && (
              <div className="mt-2">
                <Separator className="mb-3" />
                <p className="mb-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">
                  Revoked
                </p>
                {revoked.map((key) => (
                  <div
                    key={key.id}
                    className="flex flex-wrap items-center gap-2 rounded-lg border border-dashed p-2 text-sm text-muted-foreground"
                  >
                    <span className="line-through">{key.name}</span>
                    <Badge variant="outline" className="font-mono text-xs">
                      {key.key_prefix}…
                    </Badge>
                    <span>revoked {relativeTime(key.revoked_at)}</span>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      {/* create dialog */}
      <Dialog open={createOpen} onOpenChange={setCreateOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Create an API key</DialogTitle>
            <DialogDescription>
              You&apos;ll see the full key exactly once; keep it secret.
            </DialogDescription>
          </DialogHeader>
          <div className="flex flex-col gap-4">
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="key-name">Name</Label>
              <Input
                id="key-name"
                placeholder="e.g. Production ML app"
                value={name}
                onChange={(e) => setName(e.target.value)}
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label>Scopes</Label>
              <div className="grid grid-cols-2 gap-1">
                {ALL_SCOPES.map((scope) => (
                  <label
                    key={scope}
                    className="flex items-center gap-2 text-sm"
                  >
                    <input
                      type="checkbox"
                      checked={scopes.includes(scope)}
                      onChange={() => toggleScope(scope)}
                      aria-label={`Scope ${scope}`}
                    />
                    <code className="text-xs">{scope}</code>
                  </label>
                ))}
              </div>
            </div>
          </div>
          <DialogFooter>
            <Button onClick={() => setCreateOpen(false)} variant="outline">
              Cancel
            </Button>
            <Button onClick={() => void handleCreate()} disabled={saving || !name.trim()}>
              {saving ? "Creating…" : "Create"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* one-time key reveal */}
      <Dialog open={fresh !== null} onOpenChange={(open) => !open && setFresh(null)}>
        <DialogContent>
          {fresh && (
            <>
              <DialogHeader>
                <DialogTitle>Key created</DialogTitle>
                <DialogDescription>
                  Copy it now — for security it won&apos;t be shown again.
                </DialogDescription>
              </DialogHeader>
              <div className="flex items-center gap-2" data-testid="fresh-key">
                <Input readOnly value={fresh.raw_key} className="font-mono text-xs" />
                <Button
                  variant="outline"
                  size="icon"
                  aria-label="Copy key"
                  onClick={() => void copyKey(fresh.raw_key)}
                >
                  <Copy className="h-4 w-4" />
                </Button>
              </div>
              <DialogFooter>
                <Button onClick={() => setFresh(null)}>Done</Button>
              </DialogFooter>
            </>
          )}
        </DialogContent>
      </Dialog>

      {/* revoke confirm */}
      <Dialog open={revokeTarget !== null} onOpenChange={(open) => !open && setRevokeTarget(null)}>
        <DialogContent>
          {revokeTarget && (
            <>
              <DialogHeader>
                <DialogTitle>Revoke &quot;{revokeTarget.name}&quot;?</DialogTitle>
                <DialogDescription>
                  Calls made with this key will immediately fail with 401. This
                  cannot be undone.
                </DialogDescription>
              </DialogHeader>
              <DialogFooter>
                <Button variant="outline" onClick={() => setRevokeTarget(null)}>
                  Cancel
                </Button>
                <Button
                  variant="destructive"
                  onClick={() => void handleRevoke()}
                  disabled={confirming}
                >
                  {confirming ? "Revoking…" : "Revoke"}
                </Button>
              </DialogFooter>
            </>
          )}
        </DialogContent>
      </Dialog>

      {/* rotate confirm */}
      <Dialog open={rotateTarget !== null} onOpenChange={(open) => !open && setRotateTarget(null)}>
        <DialogContent>
          {rotateTarget && (
            <>
              <DialogHeader>
                <DialogTitle>Rotate &quot;{rotateTarget.name}&quot;?</DialogTitle>
                <DialogDescription>
                  The existing key is revoked and a new one with the same
                  scopes is issued. Copy it right away.
                </DialogDescription>
              </DialogHeader>
              <DialogFooter>
                <Button variant="outline" onClick={() => setRotateTarget(null)}>
                  Cancel
                </Button>
                <Button onClick={() => void handleRotate()} disabled={confirming}>
                  {confirming ? "Rotating…" : "Rotate"}
                </Button>
              </DialogFooter>
            </>
          )}
        </DialogContent>
      </Dialog>
    </AuthGate>
  );
}