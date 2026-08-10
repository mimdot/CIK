import Link from "next/link";

export default function TermsPage() {
  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <h1 className="text-3xl font-semibold">Terms of Service</h1>
      <p className="text-sm text-muted-foreground">
        Last updated: 2026-08-10 · Applies to the private-beta service.
      </p>

      <section className="space-y-2">
        <h2 className="text-xl font-semibold">Access</h2>
        <p className="text-sm">
          Career Intelligence is provided as a private beta by invitation. You
          may use the service only under the terms here and only for your own
          job search. Access may be revoked by the operator at any time and
          without notice.
        </p>
      </section>

      <section className="space-y-2">
        <h2 className="text-xl font-semibold">The service is a tool, not advice</h2>
        <p className="text-sm">
          Matching scores and AI drafts are generated automatically and may
          contain errors or omissions. You are responsible for verifying any
          position listing, application, or draft before relying on it. The
          service does not guarantee employment outcomes.
        </p>
      </section>

      <section className="space-y-2">
        <h2 className="text-xl font-semibold">Your account</h2>
        <p className="text-sm">
          You must keep your login credentials confidential and not share them.
          You may not use the service to scrape or republish its data, to
          harass others, or for any unlawful purpose. We may suspend accounts
          that violate these terms.
        </p>
      </section>

      <section className="space-y-2">
        <h2 className="text-xl font-semibold">No warranty / limitation</h2>
        <p className="text-sm">
          The service is provided “as is” without warranties of any kind.
          During the beta it may be unavailable, change without notice, or be
          discontinued. To the maximum extent permitted by law, the operator is
          not liable for any damages arising from your use of the service.
        </p>
      </section>

      <p className="text-sm">
        Questions? Contact the operator who invited you, or{" "}
        <Link href="/landing" className="underline">
          back to home
        </Link>
        .
      </p>
    </div>
  );
}
