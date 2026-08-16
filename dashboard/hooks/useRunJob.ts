"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, cancelJob, jobStatus } from "@/lib/api";
import type { RunProgress } from "@/types";

export interface RunJobState {
  open: boolean;
  busy: boolean;
  status: string | null;
  records: number | null;
  error: string | null;
  progress: RunProgress | null;
  /** True from the moment Cancel is pressed until the run reports back. */
  cancelling: boolean;
  /** Lost contact with the API mid-run and still retrying. NOT a failure:
   *  the job runs in the backend, not in this window. */
  reconnecting: boolean;
  /** Seconds since the run started — proof the search is not frozen. */
  elapsed: number;
}

const POLL_MS = 2000;

/**
 * How many consecutive unreachable polls to tolerate before giving up.
 *
 * A search runs for minutes, and a single momentary blip used to end it: the
 * catch below set busy:false and scheduled nothing, so one failed poll killed
 * the run display permanently and reported "Cannot reach the API server" —
 * while the job carried on in the backend and finished normally. The run is
 * not happening in this window, so losing sight of it briefly is not the run
 * failing. Five tries at a widened interval is ~20s of genuine silence before
 * we say anything is wrong.
 */
const MAX_POLL_FAILURES = 5;

/**
 * Shared state machine for "run a background job and poll until it finishes".
 *
 * Powers both the opportunities "Run engine" flow (pipeline run) and the
 * supervisors "Run online search" flow (supervisor sync): start(trigger)
 * launches the job, the returned run id is polled via GET /api/jobs/{id}, and
 * onCompleted() reloads the page's data.
 */
export function useRunJob(
  onCompleted?: (records: number | null) => void | Promise<void>,
) {
  const IDLE: RunJobState = {
    open: false,
    busy: false,
    status: null,
    records: null,
    error: null,
    progress: null,
    cancelling: false,
    reconnecting: false,
    elapsed: 0,
  };
  const [state, setState] = useState<RunJobState>(IDLE);
  const [runId, setRunId] = useState<string | null>(null);
  const startedAt = useRef<number | null>(null);
  const onCompletedRef = useRef(onCompleted);
  onCompletedRef.current = onCompleted;

  const start = useCallback(
    async (trigger: () => Promise<{ run_id: string }>) => {
      setRunId(null);
      startedAt.current = Date.now();
      setState({ ...IDLE, open: true, busy: true, status: "starting" });
      try {
        const res = await trigger();
        setRunId(res.run_id);
      } catch (e) {
        setState((s) => ({
          ...s,
          busy: false,
          status: "failed",
          error: e instanceof ApiError ? e.message : "Could not start the run",
        }));
      }
    },
    // IDLE is a stable literal; excluding it keeps start() referentially stable.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
  );

  /**
   * Stop an in-progress run. The backend cancels cooperatively, so partial
   * results are still filtered, deduped and saved; the dialog stays open and
   * usable and the page reloads with whatever was found.
   */
  const cancel = useCallback(async () => {
    if (!runId) return;
    setState((s) => ({ ...s, cancelling: true }));
    try {
      await cancelJob(runId);
    } catch (e) {
      // 409 = it finished on its own in the meantime; that is not an error
      // worth showing, the next poll will report the real outcome.
      if (!(e instanceof ApiError && e.status === 409)) {
        setState((s) => ({
          ...s,
          cancelling: false,
          error: e instanceof ApiError ? e.message : "Could not cancel the run",
        }));
      }
    }
  }, [runId]);

  useEffect(() => {
    if (!state.open || !runId) return;
    let stopped = false;
    let fails = 0;
    const tick = async () => {
      try {
        const status = await jobStatus(runId);
        if (stopped) return;
        fails = 0; // contact restored (or never lost)
        // The job backend may report queued/deferred while en route to
        // running; treat every non-terminal task state as "running".
        const phase =
          status.status === "running" || status.status === "queued"
            ? ("running" as const)
            : status.status;
        setState((s) => ({
          ...s,
          status: phase,
          records: status.records ?? s.records,
          error: status.error ?? s.error,
          progress: status.progress ?? s.progress,
          reconnecting: false,
        }));
        if (status.status === "completed" || status.status === "cancelled") {
          // A cancelled run is a SUCCESSFUL one that stopped early: its
          // partial results are already saved, so reload the page data just
          // as for a full run. The UI returns to a usable idle state.
          setState((s) => ({
            ...s,
            status: status.status,
            busy: false,
            cancelling: false,
          }));
          void onCompletedRef.current?.(status.records ?? null);
        } else if (status.status === "failed") {
          setState((s) => ({
            ...s, status: "failed", busy: false, cancelling: false,
          }));
        } else {
          setTimeout(() => {
            if (!stopped) void tick();
          }, POLL_MS);
        }
      } catch (e) {
        if (stopped) return;
        fails += 1;
        // status 0 is "the request never got an answer" — the desktop shell
        // restarting the sidecar looks exactly like this, and it comes back.
        const unreachable = e instanceof ApiError && e.status === 0;
        if (unreachable && fails < MAX_POLL_FAILURES) {
          setState((s) => ({ ...s, reconnecting: true }));
          setTimeout(() => {
            if (!stopped) void tick();
          }, POLL_MS * 2);
          return;
        }
        setState((s) => ({
          ...s,
          error:
            e instanceof ApiError ? e.message : "Could not check run status",
          busy: false,
          cancelling: false,
          reconnecting: false,
          status: s.status === "starting" ? "failed" : s.status,
        }));
      }
    };
    void tick();
    return () => {
      stopped = true;
    };
  }, [state.open, runId]);

  // Elapsed-time ticker: visible proof the search is working, not frozen.
  useEffect(() => {
    if (!state.busy || startedAt.current === null) return;
    const id = setInterval(() => {
      if (startedAt.current === null) return;
      setState((s) => ({
        ...s,
        elapsed: Math.floor((Date.now() - startedAt.current!) / 1000),
      }));
    }, 1000);
    return () => clearInterval(id);
  }, [state.busy]);

  const close = useCallback(() => {
    setState((s) => ({ ...s, open: false }));
  }, []);

  return { ...state, start, cancel, close };
}
