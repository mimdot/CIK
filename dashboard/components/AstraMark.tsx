/**
 * The Astra mark — three square nodes joined by two strokes.
 *
 * Geometry is fixed by the identity spec (Mark 5E, 100 × 100 grid) and must not
 * be re-spaced, rotated or mirrored. The two ink nodes and both strokes use
 * `currentColor`, so the mark inverts for free on dark chrome; the keystone —
 * the position you are heading for — is the one accent element.
 *
 * `oneColor` drops the accent entirely. Required below 16px, in single-colour
 * print and in terminal contexts, where the accent cannot be relied on to read.
 */
export default function AstraMark({
  size = 28,
  oneColor = false,
  accent,
  className,
}: {
  /** Rendered edge length in px. Use whole pixels so the 7-unit strokes stay crisp. */
  size?: number;
  /** Drop the accent node to currentColor. Mandatory under 16px. */
  oneColor?: boolean;
  /** Override the keystone colour — `#ff563c` on ink, per the spec. */
  accent?: string;
  className?: string;
}) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 100 100"
      fill="none"
      role="img"
      aria-label="Astra"
      className={className}
      style={{ flex: "none" }}
    >
      <line x1="14" y1="80" x2="48" y2="34" stroke="currentColor" strokeWidth="7" />
      <line x1="48" y1="34" x2="87" y2="53" stroke="currentColor" strokeWidth="7" />
      <rect x="0" y="66" width="28" height="28" fill="currentColor" />
      <rect x="74" y="40" width="26" height="26" fill="currentColor" />
      <rect
        x="32"
        y="18"
        width="32"
        height="32"
        fill={oneColor ? "currentColor" : (accent ?? "var(--astra-accent, #ec3013)")}
      />
    </svg>
  );
}
