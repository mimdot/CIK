import Link from "next/link";

export default function PrivacyPage() {
  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <h1 className="text-3xl font-semibold">Privacy Policy</h1>
      <p className="text-sm text-muted-foreground">
        Last updated: 2026-08-10 · This is the private-beta version.
      </p>

      <section className="space-y-2">
        <h2 className="text-xl font-semibold">What we collect</h2>
        <p className="text-sm">
          To operate the service we store the account details you provide
          (email address and a password hashed with bcrypt), your research
          profile (the CV text or answers you supply, plus the structured
          profile we derive from it), and your activity within the app
          (matches, saved positions, feedback, and API usage).
        </p>
      </section>

      <section className="space-y-2">
        <h2 className="text-xl font-semibold">How your profile is used</h2>
        <p className="text-sm">
          Your profile is used only to score and filter position listings for
          you and to power the optional writing assistant. Profile text may be
          sent to a third-party LLM provider for extraction and drafting; it is
          not used to train those models on your behalf.
        </p>
      </section>

      <section className="space-y-2">
        <h2 className="text-xl font-semibold">Cookies</h2>
        <p className="text-sm">
          This site sets only functional cookies — the session cookie that keeps
          you signed in. We do not use tracking or advertising cookies. Your
          consent choice is stored in your browser.
        </p>
      </section>

      <section className="space-y-2">
        <h2 className="text-xl font-semibold">Your rights</h2>
        <p className="text-sm">
          You may request a copy of everything we hold about you
          ({" "}
          <span className="font-mono text-xs">GET /api/account/data-export</span>
          ), update your marketing-email consent, or erase your account. When
          you erase your account we delete your personal records and anonymize
          aggregated analytics so no row identifies you. To exercise these
          rights, use the account menu in the dashboard or contact the operator
          who invited you.
        </p>
      </section>

      <section className="space-y-2">
        <h2 className="text-xl font-semibold">Contact</h2>
        <p className="text-sm">
          Questions about this policy? Contact the person or team that invited
          you to the private beta.{" "}
          <Link href="/landing" className="underline">
            Back to home
          </Link>
          .
        </p>
      </section>
    </div>
  );
}
