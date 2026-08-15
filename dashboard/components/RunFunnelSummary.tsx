"use client";

import type { RunFunnel } from "@/types";

/**
 * Explains the headline number.
 *
 * The bug this exists for: the page said "18 open positions" while the run
 * dialog said "63 records" — two numbers, from two layers, neither accounting
 * for the other. Now the engine reports every stage and every drop reason, and
 * this renders the chain so the shrink is always visible and attributable.
 */
export function RunFunnelSummary({ funnel }: { funnel: RunFunnel }) {
  const d = funnel.dropped;
  const stages: { label: string; value: number }[] = [
    { label: "found", value: funnel.found },
    { label: "after field filter", value: funnel.after_field_filter },
    { label: "after freshness", value: funnel.after_freshness },
    { label: "after dedupe", value: funnel.after_dedupe },
  ];
  if (typeof funnel.stored === "number") {
    stages.push({ label: "stored", value: funnel.stored });
  }

  const reasons: { label: string; value: number }[] = [
    { label: "wrong position type", value: d.position_type },
    { label: "off-field", value: d.off_field },
    { label: "deadline passed", value: d.expired },
    { label: "other country", value: d.country },
    { label: "too old", value: d.stale },
    { label: "duplicate", value: d.duplicate },
  ].filter((r) => r.value > 0);

  return (
    <div
      className="rounded-md border bg-muted/40 p-3 text-xs"
      data-testid="run-funnel"
    >
      <div className="flex flex-wrap items-center gap-x-1.5 gap-y-1 font-medium">
        {stages.map((s, i) => (
          <span key={s.label} className="flex items-center gap-1.5">
            {i > 0 && <span aria-hidden className="text-muted-foreground">→</span>}
            <span>
              {s.value}{" "}
              <span className="font-normal text-muted-foreground">{s.label}</span>
            </span>
          </span>
        ))}
      </div>

      {/* Which profile terms this run actually used. Without this the only way
          to tell whether the research profile did anything was to change it,
          re-run, and compare by eye. */}
      <p className="mt-2 text-muted-foreground" data-testid="run-profile-terms">
        {funnel.profile_active && (funnel.profile_terms?.length ?? 0) > 0 ? (
          <>
            Ranked with your research profile:{" "}
            <span className="font-medium text-foreground">
              {funnel.profile_terms!.join(", ")}
            </span>
          </>
        ) : (
          <>
            No research profile was used — results are ranked by field relevance
            only. Add keywords on the Profile page to change what ranks highest.
          </>
        )}
      </p>

      {/* The table total belongs OUTSIDE the funnel chain. Printed as the last
          stage it contradicted the stage before it — "0 after dedupe → 40
          stored" — because it counts every earlier run's rows too. */}
      {typeof funnel.stored_total === "number" && (
        <p className="mt-2 text-muted-foreground" data-testid="run-stored-total">
          {funnel.stored_total} saved in total, including earlier runs.
        </p>
      )}

      {reasons.length > 0 && (
        <p className="mt-2 text-muted-foreground">
          Dropped:{" "}
          {reasons.map((r, i) => (
            <span key={r.label}>
              {i > 0 && ", "}
              {r.value} {r.label}
            </span>
          ))}
          .
        </p>
      )}

      {funnel.storage_error && (
        <div className="mt-2 text-destructive">
          <p>
            Results were found but could not be saved ({funnel.storage_error}),
            so the list below may be out of date.
          </p>
          {funnel.storage_rescue_path && (
            <p className="mt-1">
              Nothing was lost — this run was saved to{" "}
              <code
                className="break-all rounded bg-destructive/10 px-1 py-0.5 font-mono"
                data-testid="run-rescue-path"
              >
                {funnel.storage_rescue_path}
              </code>
            </p>
          )}
        </div>
      )}
    </div>
  );
}
