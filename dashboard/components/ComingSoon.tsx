import { Badge } from "@/components/ui/badge";

/**
 * Placeholders for features planned for a future update (Phase 6B/6C).
 *
 * Deliberately EMPTY of content: they reserve the layout and set expectations,
 * but invent nothing. A fake testimonial or a live-looking donate button that
 * does not work would be worse than no section at all.
 */

/** Shown while a search runs — a future home for real user experiences. */
export function TestimonialsPlaceholder() {
  return (
    <section
      aria-labelledby="testimonials-heading"
      className="rounded-lg border border-dashed p-4"
      data-testid="testimonials-placeholder"
    >
      <div className="flex items-center gap-2">
        <h2 id="testimonials-heading" className="text-sm font-medium">
          While you wait
        </h2>
        <Badge variant="outline">Coming soon</Badge>
      </div>
      <p className="mt-1.5 text-sm text-muted-foreground">
        This space will show how other researchers used the app to find their
        position — real experiences, once people have shared them.
      </p>
    </section>
  );
}

/** Reserved for a future donation option. Intentionally not a live button. */
export function DonationPlaceholder() {
  return (
    <section
      aria-labelledby="support-heading"
      className="rounded-lg border border-dashed p-4"
      data-testid="donation-placeholder"
    >
      <div className="flex items-center gap-2">
        <h2 id="support-heading" className="text-sm font-medium">
          Support this project
        </h2>
        <Badge variant="outline">Coming soon</Badge>
      </div>
      <p className="mt-1.5 text-sm text-muted-foreground">
        The Career Intelligence Kit is free and open. A way to support its
        development is planned for a future update.
      </p>
    </section>
  );
}
