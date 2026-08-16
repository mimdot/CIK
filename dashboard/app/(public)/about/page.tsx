import Link from "next/link";

const FAQ = [
  {
    q: "What is Astra?",
    a: "A private tool for researchers that aggregates open PhD and postdoc positions from dozens of sources every night, then ranks them against a profile you describe. It also helps you draft cover letters and application emails.",
  },
  {
    q: "Who can use it?",
    a: "Currently a small private beta. Access is by invite code, so new accounts can only be created with an invitation. If you have a code, sign in on the home page and enter it during registration.",
  },
  {
    q: "Which fields does it cover?",
    a: "It is built and tuned for physics, astronomy, and related quantitative fields, but the profile engine is field-agnostic and can be adapted.",
  },
  {
    q: "Is my CV shared anywhere?",
    a: "No. Your profile is used to score positions and to power the assistant you trigger explicitly. It is never published or sold. See the Privacy Policy for full details.",
  },
];

export default function AboutPage() {
  return (
    <div className="mx-auto max-w-3xl space-y-8">
      <h1 className="text-3xl font-semibold">About Astra</h1>
      <p className="text-muted-foreground">
        Astra was built to solve a common frustration: hundreds of
        PhD and postdoc openings are published across university pages, job
        boards, and mailing lists every month, and most researchers only ever
        see the few that surface by chance. This service gathers them in one
        place and ranks them for you.
      </p>
      <section className="space-y-4">
        <h2 className="text-xl font-semibold">Frequently asked questions</h2>
        {FAQ.map(({ q, a }) => (
          <div key={q} className="rounded-xl border p-4">
            <h3 className="font-semibold">{q}</h3>
            <p className="mt-1 text-sm text-muted-foreground">{a}</p>
          </div>
        ))}
      </section>
      <p className="text-sm">
        <Link href="/landing" className="underline">
          Back to home
        </Link>
      </p>
    </div>
  );
}
