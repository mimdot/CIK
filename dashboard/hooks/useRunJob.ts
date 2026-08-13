"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, jobStatus } from "@/lib/api";
import type { RunProgress } from "@/types";

export interface RunJobState {
  open: boolean;
  busy: boolean;
  status: string | null;
  records: number | null;
  error: string | null;
  progress: RunProgress | null;
}

const POLL_MS = 2000;

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
  const [state, setState] = useState<RunJobState>({
    open: false,
    busy: false,
    status: null,
    records: null,
    error: null,
    progress: null,
  });
  const [runId, setRunId] = useState<string | null>(null);
  const onCompletedRef = useRef(onCompleted);
  onCompletedRef.current = onCompleted;

  const start = useCallback(
    async (trigger: () => Promise<{ run_id: string }>) => {
      setRunId(null);
      setState({ open: true, busy: true, status: "starting", records: null, error: null, progress: null });
      try {
        const res = await trigger();
        setRunId(res.run_id);
      } catch (e) {
        setState({
          open: true,
          busy: false,
          status: "failed",
          records: null,
          error: e instanceof ApiError ? e.message : "Could not start the run",
          progress: null,
        });
      }
    },
    [],
  );

  useEffect(() => {
    if (!state.open || !runId) return;
    let cancelled = false;
    const tick = async () => {
      try {
        const status = await jobStatus(runId);
        if (cancelled) return;
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
        }));
        if (status.status === "completed") {
          setState((s) => ({ ...s, status: "completed", busy: false }));
          void onCompletedRef.current?.(status.records ?? null);
        } else if (status.status === "failed") {
          setState((s) => ({ ...s, status: "failed", busy: false }));
        } else {
          setTimeout(() => {
            if (!cancelled) void tick();
          }, POLL_MS);
        }
      } catch (e) {
        if (cancelled) return;
        setState((s) => ({
          ...s,
          error:
            e instanceof ApiError ? e.message : "Could not check run status",
          busy: false,
          status: s.status === "starting" ? "failed" : s.status,
        }));
      }
    };
    void tick();
    return () => {
      cancelled = true;
    };
  }, [state.open, runId]);

  const close = useCallback(() => {
    setState((s) => ({ ...s, open: false }));
  }, []);

  return { ...state, start, close };
}
