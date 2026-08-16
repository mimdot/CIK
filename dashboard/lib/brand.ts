/**
 * Astra — the fixed strings from the identity spec (section 04).
 *
 * These are quoted verbatim in the handoff and must not be paraphrased per
 * surface. Kept in one module so a wording change is one edit, and so the CLI,
 * dashboard and desktop cannot drift into three slightly different products.
 *
 * Naming rules the spec is explicit about:
 *  - "Astra" is always capitalised — never ASTRA, never Astra.app
 *  - `astra` is lowercase in every code context (binary, command, package)
 *  - surfaces are "Astra CLI", "Astra Dashboard", "Astra Desktop"
 *  - domain terms are position, supervisor, programme, call, deadline,
 *    shortlist — never "job", never "lead"
 */

export const BRAND = {
  /** Product name. Capitalised, always. */
  name: "Astra",

  /** Top line — use verbatim. */
  topLine: "Astra: your academic constellation",

  /** The tagline on its own, for chrome and titles. */
  tagline: "Your academic constellation",

  /** Four-word descriptor that sits under the wordmark. */
  descriptor: "Positions and supervisors in academia",

  /** Uppercase label form of the descriptor, for chrome at label size. */
  descriptorLabel: "Positions & supervisors",

  /** One-line memo — README, package description, --help. */
  memo:
    "Astra finds academic positions and supervisors — PhD openings, postdocs, " +
    "funded programmes and the people running them — and keeps the search on " +
    "your own machine.",

  /** Short memo — landing page, store listing. */
  summary:
    "Academic openings are scattered across faculty pages, mailing lists and " +
    "PDF calls. Astra collects them, matches them to your field and stage, and " +
    "shows you who supervises what — so the search becomes a shortlist you can " +
    "act on. Runs as a command, a local dashboard or a desktop app; your data " +
    "never leaves your machine.",

  /** Origin note. Colophons and about screens only — never a tagline. */
  motto: "Per aspera ad astra",
} as const;

/** Colour roles, for the few places that need a literal rather than a token. */
export const BRAND_COLORS = {
  ground: "#f3f2f2",
  surface: "#eae9e9",
  ink: "#201e1d",
  accent: "#ec3013",
  accentOnInk: "#ff563c",
  accentText: "#ae1800",
  secondaryText: "#605d5d",
} as const;
