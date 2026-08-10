import Link from "next/link";
import { buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";

const STEPS = [
  {
    title: "Build your profile",
    body: "Paste your CV or answer a few questions. An LLM extracts your research domain, skills, methods, and target roles.",
  },
  {
    title: "Find matches",
    body: "Fresh PhD and postdoc positions are aggregated nightly and scored against your profile — relevance, location, funding, and fit.",
  },
  {
    title: "Apply with confidence",
    body: "Save positions, track applications, and use the assistant to draft cover letters and application emails.",
  },
];

export default function LandingPage() {
  return (
    <div className="space-y-14">
      <section className="mx-auto max-w-3xl text-center">
        <h1 className="text-4xl font-semibold tracking-tight sm:text-5xl">
          Your next research position, matched to you
        </h1>
        <p className="mx-auto mt-4 max-w-2xl text-lg text-muted-foreground">
          Career Intelligence aggregates open PhD and postdoc positions across
          physics, astronomy, and related fields — then scores each one against
          your own research profile, so you see the positions worth applying
          to.
        </p>
        <div className="mt-8 flex justify-center gap-3">
          <Link href="/" className={cn(buttonVariants({ size: "lg" }))}>
            Get started
          </Link>
          <Link
            href="/#how-it-works"
            className={cn(buttonVariants({ variant: "outline", size: "lg" }))}
          >
            How it works
          </Link>
        </div>
        <p className="mt-4 text-xs text-muted-foreground">
          Private beta — access is by invitation.
        </p>
      </section>

      <section id="how-it-works" className="grid gap-6 sm:grid-cols-3">
        {STEPS.map((step, i) => (
          <div key={step.title} className="rounded-xl border p-6">
            <p className="text-sm font-semibold text-primary">
              Step {i + 1} of 3
            </p>
            <h2 className="mt-2 text-lg font-semibold">{step.title}</h2>
            <p className="mt-2 text-sm text-muted-foreground">{step.body}</p>
          </div>
        ))}
      </section>

      <section className="mx-auto max-w-2xl rounded-xl border p-6 text-center">
        <h2 className="text-xl font-semibold">Your data stays yours</h2>
        <p className="mt-2 text-sm text-muted-foreground">
          Your profile is used only to score positions for you. Export or erase
          your account any time from your settings — see our{" "}
          <Link href="/privacy" className="underline">
            Privacy Policy
          </Link>
          .
        </p>
      </section>
    </div>
  );
}
