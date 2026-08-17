"use client";

import { useCallback, useEffect, useState } from "react";
import AuthGate from "@/components/AuthGate";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  ApiError,
  createInvite,
  fetchAdminMetrics,
  fetchAnomalies,
  fetchDeadLetters,
  fetchFeedbackIntel,
  fetchInvites,
  fetchSourceHealth,
  fetchWorkerHeartbeat,
  retryDeadLetter,
  runAnomalyDetect,
  runDriftCheck,
} from "@/lib/api";
import type {
  AdminMetrics,
  AnomalySnapshot,
  DeadLetterJob,
  FeedbackIntel,
  SourceHealthRow,
  WorkerHeartbeat,
} from "@/types";

const REFRESH_MS = 30_000;

function Stat({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="flex flex-col gap-0.5 rounded-md border p-3">
      <span className="text-xs text-muted-foreground">{label}</span>
      <span className="text-lg font-semibold tabular-nums">{value}</span>
    </div>
  );
}

export default function AdminPage() {
  const [metrics, setMetrics] = useState<AdminMetrics | null>(null);
  const [invites, setInvites] = useState<{ items: { code: string; used: boolean }[]; created: number; redeemed: number; pending: number } | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [newCode, setNewCode] = useState<string | null>(null);

  // Sprint 09 ops intelligence
  const [sourceHealth, setSourceHealth] = useState<SourceHealthRow[]>([]);
  const [feedback, setFeedback] = useState<FeedbackIntel | null>(null);
  const [deadLetters, setDeadLetters] = useState<DeadLetterJob[]>([]);
  const [heartbeat, setHeartbeat] = useState<WorkerHeartbeat | null>(null);
  const [anomalies, setAnomalies] = useState<AnomalySnapshot | null>(null);
  const [opsMsg, setOpsMsg] = useState<string | null>(null);
  const [retrying, setRetrying] = useState<string | null>(null);

  const loadOps = useCallback(async () => {
    try {
      const [sh, fb, dl, hb, an] = await Promise.all([
        fetchSourceHealth(),
        fetchFeedbackIntel(),
        fetchDeadLetters(),
        fetchWorkerHeartbeat(),
        fetchAnomalies(),
      ]);
      setSourceHealth(sh.sources ?? []);
      setFeedback(fb);
      setDeadLetters(dl.jobs ?? []);
      setHeartbeat(hb);
      setAnomalies(an);
    } catch (e) {
      setOpsMsg(
        e instanceof ApiError ? `Ops intel: ${e.message}` : "Ops intel unavailable",
      );
    }
  }, []);

  const load = useCallback(async () => {
    setError(null);
    try {
      const [m, inv] = await Promise.all([fetchAdminMetrics(), fetchInvites()]);
      setMetrics(m);
      setInvites(inv);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not load admin data");
      if (e instanceof ApiError && e.status === 403) {
        setError("Admin privileges required to view this page.");
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load();
    void loadOps();
    const timer = setInterval(() => {
      void load();
      void loadOps();
    }, REFRESH_MS);
    return () => clearInterval(timer);
  }, [load, loadOps]);

  async function handleCreateInvite() {
    setCreating(true);
    setNewCode(null);
    setError(null);
    try {
      const created = await createInvite();
      setNewCode(created.code);
      await load();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not create invite");
    } finally {
      setCreating(false);
    }
  }

  async function handleDriftCheck() {
    setOpsMsg(null);
    try {
      const result = await runDriftCheck();
      setOpsMsg(
        result.count === 0
          ? "No source drift detected."
          : `${result.count} source(s) drifted — alerts sent to ops.`,
      );
    } catch (e) {
      setOpsMsg(e instanceof ApiError ? e.message : "Drift check failed");
    }
  }

  async function handleAnomalyDetect() {
    setOpsMsg(null);
    try {
      const an = await runAnomalyDetect();
      setAnomalies(an);
      setOpsMsg(
        an.anomalies.length === 0
          ? "No API anomalies detected."
          : `${an.anomalies.length} API anomaly(ies) — alerts sent to ops.`,
      );
    } catch (e) {
      setOpsMsg(e instanceof ApiError ? e.message : "Anomaly detection failed");
    }
  }

  async function handleRetry(jobId: string) {
    setRetrying(jobId);
    setOpsMsg(null);
    try {
      const result = await retryDeadLetter(jobId);
      setOpsMsg(`Requeued job ${jobId} (new id ${result.new_job_id}).`);
      await loadOps();
    } catch (e) {
      setOpsMsg(e instanceof ApiError ? e.message : "Retry failed");
    } finally {
      setRetrying(null);
    }
  }

  return (
    <AuthGate>
      <div className="flex flex-col gap-6">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h1 className="text-2xl font-semibold">Admin</h1>
            <p className="text-sm text-muted-foreground">
              Source health, API, users, jobs and invites. Auto-refreshes every
              30 seconds.
            </p>
          </div>
          <div className="flex items-center gap-2">
            {newCode && (
              <Badge variant="secondary" data-testid="new-invite-code">
                {newCode}
              </Badge>
            )}
            <Button onClick={() => void handleCreateInvite()} disabled={creating}>
              {creating ? "Creating…" : "Create invite"}
            </Button>
          </div>
        </div>

        {error && (
          <div className="rounded-md border border-destructive/30 bg-destructive/10 p-4 text-sm text-destructive">
            {error}
            <Button variant="outline" size="sm" className="ml-3" onClick={() => void load()}>
              Retry
            </Button>
          </div>
        )}

        {loading ? (
          <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
            {Array.from({ length: 8 }).map((_, i) => (
              <Skeleton key={i} className="h-20" />
            ))}
          </div>
        ) : metrics ? (
          <>
            <section className="grid gap-4 md:grid-cols-2 lg:grid-cols-4" aria-label="User metrics">
              <Stat label="Total users" value={metrics.users.total} />
              <Stat label="Active profiles" value={metrics.users.active} />
              <Stat label="Profiles built" value={metrics.users.profiles_built} />
              <Stat label="Matches computed" value={metrics.content.matches} />
            </section>

            <Card>
              <CardHeader>
                <CardTitle className="text-base">API</CardTitle>
                <CardDescription>
                  Requests recorded since the API started (process-local).
                </CardDescription>
              </CardHeader>
              <CardContent className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
                <Stat label="Requests" value={metrics.api.requests} />
                <Stat label="Error rate" value={`${(metrics.api.error_rate * 100).toFixed(2)}%`} />
                <Stat label="Avg latency" value={`${metrics.api.avg_latency_ms} ms`} />
                <Stat label="p95 latency" value={`${metrics.api.p95_latency_ms} ms`} />
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle className="text-base">Job queue</CardTitle>
                <CardDescription>
                  Pipeline runs via the {metrics.jobs.backend} backend.
                </CardDescription>
              </CardHeader>
              <CardContent className="grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
                <Stat label="Pending" value={metrics.jobs.pending} />
                <Stat label="Running" value={metrics.jobs.running} />
                <Stat label="Completed" value={metrics.jobs.completed} />
                <Stat label="Failed" value={metrics.jobs.failed} />
                <Stat label="Total" value={metrics.jobs.total} />
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle className="text-base">Source health</CardTitle>
                <CardDescription>
                  Record count and latest posting per source.
                </CardDescription>
              </CardHeader>
              <CardContent>
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Source</TableHead>
                      <TableHead className="text-right">Records</TableHead>
                      <TableHead>Last posted</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {metrics.content.sources.map((s) => (
                      <TableRow key={s.source}>
                        <TableCell className="font-medium">{s.source}</TableCell>
                        <TableCell className="text-right tabular-nums">{s.records}</TableCell>
                        <TableCell>{s.last_posted?.slice(0, 10) ?? "—"}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </CardContent>
            </Card>
          </>
        ) : null}

        {opsMsg && (
          <div
            className="border p-3 text-sm font-bold"
            data-testid="ops-msg"
          >
            {opsMsg}
          </div>
        )}

        <section className="grid gap-4 md:grid-cols-2 lg:grid-cols-4" aria-label="LLM usage and source health">
          <Stat label="LLM calls" value={metrics?.llm?.calls ?? 0} />
          <Stat
            label="Est. LLM spend (USD)"
            value={`$${(metrics?.llm?.estimated_spend_usd ?? 0).toFixed(2)}`}
          />
          <Stat label="Drifting sources" value={metrics?.source_health?.drifted ?? 0} />
          <Stat label="Erroring sources" value={metrics?.source_health?.erroring ?? 0} />
        </section>

        <Card>
          <CardHeader className="flex flex-row items-start justify-between gap-2">
            <div>
              <CardTitle className="text-base">Source availability</CardTitle>
              <CardDescription>
                Rolling baseline of raw records per run. A z-score above 2.5
                flags drift.
              </CardDescription>
            </div>
            <Button
              variant="outline"
              size="sm"
              onClick={() => void handleDriftCheck()}
            >
              Check drift
            </Button>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Source</TableHead>
                  <TableHead className="text-right">Runs</TableHead>
                  <TableHead className="text-right">Last result</TableHead>
                  <TableHead className="text-right">Baseline mean</TableHead>
                  <TableHead className="text-right">z</TableHead>
                  <TableHead>Status</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {sourceHealth.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={6} className="text-muted-foreground">
                      No source runs recorded yet.
                    </TableCell>
                  </TableRow>
                ) : (
                  sourceHealth.map((s) => (
                    <TableRow key={s.source} data-testid={`source-row-${s.source}`}>
                      <TableCell className="font-medium">{s.source}</TableCell>
                      <TableCell className="text-right tabular-nums">{s.runs}</TableCell>
                      <TableCell className="text-right tabular-nums">
                        {s.last_result ?? "—"}
                      </TableCell>
                      <TableCell className="text-right tabular-nums">
                        {s.mean ?? "—"}
                      </TableCell>
                      <TableCell className="text-right tabular-nums">
                        {s.zscore ?? "—"}
                      </TableCell>
                      <TableCell>
                        {s.drift ? (
                          <Badge variant="destructive">drift</Badge>
                        ) : (
                          <Badge variant="outline">ok</Badge>
                        )}
                      </TableCell>
                    </TableRow>
                  ))
                )}
              </TableBody>
            </Table>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">Match-feedback intel</CardTitle>
            <CardDescription>
              Helpful-rate by score band and by source, plus the most common
              complaint keywords from negative comments.
            </CardDescription>
          </CardHeader>
          <CardContent className="grid gap-6 lg:grid-cols-2">
            <div className="flex flex-col gap-3">
              <div className="grid grid-cols-3 gap-2">
                <Stat label="Total" value={feedback?.summary.total ?? 0} />
                <Stat label="Helpful" value={feedback?.summary.helpful ?? 0} />
                <Stat
                  label="Helpful rate"
                  value={
                    feedback?.summary.rate != null
                      ? `${Math.round(feedback.summary.rate * 100)}%`
                      : "—"
                  }
                />
              </div>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Score band</TableHead>
                    <TableHead className="text-right">Total</TableHead>
                    <TableHead className="text-right">Helpful</TableHead>
                    <TableHead className="text-right">Rate</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {(feedback?.brackets ?? []).map((b) => (
                    <TableRow key={b.key}>
                      <TableCell>{b.key}</TableCell>
                      <TableCell className="text-right tabular-nums">{b.total}</TableCell>
                      <TableCell className="text-right tabular-nums">{b.helpful}</TableCell>
                      <TableCell className="text-right tabular-nums">
                        {b.rate != null ? `${Math.round(b.rate * 100)}%` : "—"}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
            <div className="flex flex-col gap-3">
              <p className="text-xs font-medium text-muted-foreground">
                Top complaint keywords
              </p>
              <div className="flex flex-wrap gap-1.5">
                {(feedback?.comments.keywords ?? []).map((k) => (
                  <Badge key={k.keyword} variant="secondary">
                    {k.keyword} · {k.count}
                  </Badge>
                ))}
              </div>
              {(feedback?.comments.samples ?? []).slice(0, 3).map((s, i) => (
                <p
                  key={i}
                  className="rounded-md border p-2 text-xs text-muted-foreground"
                >
                  “{s.comment}”
                </p>
              ))}
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-start justify-between gap-2">
            <div>
              <CardTitle className="text-base">Failed jobs & workers</CardTitle>
              <CardDescription>
                Dead-letter jobs available for requeue and the latest worker
                heartbeat.
              </CardDescription>
            </div>
            <Badge variant="outline">
              {heartbeat?.backend ?? "—"} ·{" "}
              {heartbeat?.workers
                ? Object.keys(heartbeat.workers).length
                : 0}{" "}
              worker(s)
            </Badge>
          </CardHeader>
          <CardContent className="flex flex-col gap-2">
            {deadLetters.length === 0 ? (
              <p className="text-sm text-muted-foreground">No failed jobs.</p>
            ) : (
              deadLetters.map((job) => (
                <div
                  key={job.job_id}
                  className="flex items-center justify-between gap-3 rounded-md border p-2"
                  data-testid={`dead-letter-${job.job_id}`}
                >
                  <div className="min-w-0">
                    <p className="font-mono text-xs">{job.job_id}</p>
                    <p className="truncate text-xs text-muted-foreground">
                      {job.error}
                    </p>
                  </div>
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={retrying === job.job_id}
                    onClick={() => void handleRetry(job.job_id)}
                  >
                    {retrying === job.job_id ? "Requeueing…" : "Retry"}
                  </Button>
                </div>
              ))
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-start justify-between gap-2">
            <div>
              <CardTitle className="text-base">API anomalies</CardTitle>
              <CardDescription>
                Rolling per-minute API metrics with z-score anomaly detection.
              </CardDescription>
            </div>
            <Button
              variant="outline"
              size="sm"
              onClick={() => void handleAnomalyDetect()}
            >
              Re-run detection
            </Button>
          </CardHeader>
          <CardContent className="flex flex-col gap-3">
            <div className="grid gap-2 sm:grid-cols-3">
              <Stat
                label="Requests (window)"
                value={anomalies?.summaries.requests ?? 0}
              />
              <Stat
                label="Error rate"
                value={`${((anomalies?.summaries.error_rate ?? 0) * 100).toFixed(2)}%`}
              />
              <Stat
                label="Avg latency"
                value={`${anomalies?.summaries.avg_latency_ms ?? 0} ms`}
              />
            </div>
            {anomalies?.anomalies.length ? (
              <ul className="flex flex-col gap-1.5">
                {anomalies.anomalies.map((a) => (
                  <li
                    key={a.id}
                    className="rounded-md border border-destructive/30 bg-destructive/10 p-2 text-sm"
                    data-testid="anomaly-row"
                  >
                    {a.message}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-sm text-muted-foreground">No anomalies detected.</p>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">Invites</CardTitle>
            <CardDescription>
              Private-beta access codes and their usage.
            </CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-4">
            {invites ? (
              <div className="grid gap-4 sm:grid-cols-3">
                <Stat label="Created" value={invites.created} />
                <Stat label="Redeemed" value={invites.redeemed} />
                <Stat label="Pending" value={invites.pending} />
              </div>
            ) : (
              !loading && <Skeleton className="h-20" />
            )}
            {invites && invites.items.length > 0 && (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Code</TableHead>
                    <TableHead>Status</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {invites.items.map((i) => (
                    <TableRow key={i.code}>
                      <TableCell className="font-mono text-xs">{i.code}</TableCell>
                      <TableCell>
                        <Badge variant={i.used ? "secondary" : "outline"}>
                          {i.used ? "used" : "pending"}
                        </Badge>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </CardContent>
        </Card>
      </div>
    </AuthGate>
  );
}
