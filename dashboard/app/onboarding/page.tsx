"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import AuthGate from "@/components/AuthGate";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { ApiError, buildProfile, fetchFields, fetchProfile, updateProfile, validateInvite } from "@/lib/api";
import type { UserProfile } from "@/types";

const STEPS = [
  "Welcome",
  "Paste CV",
  "Review",
  "Field",
  "Countries",
  "Done",
];

const STORAGE_KEY = "cik_onboarding";

export default function OnboardingPage() {
  const router = useRouter();
  const [step, setStep] = useState(0);
  const [rawText, setRawText] = useState("");
  const [profile, setProfile] = useState<UserProfile | null>(null);
  const [fields, setFields] = useState<string[]>([]);
  const [field, setField] = useState("");
  const [countries, setCountries] = useState("");
  const [checking, setChecking] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [inviteCode, setInviteCode] = useState("");
  const [inviting, setInviting] = useState(false);

  // Restore saved progress from localStorage (client-only).
  useEffect(() => {
    try {
      const saved = localStorage.getItem(STORAGE_KEY);
      if (saved) {
        const parsed = JSON.parse(saved) as { step?: number; rawText?: string };
        // eslint-disable-next-line react-hooks/set-state-in-effect
        if (typeof parsed.step === "number") setStep(parsed.step);
        if (typeof parsed.rawText === "string") setRawText(parsed.rawText);
      }
    } catch {
      // Ignore corrupt storage.
    }
  }, []);

  function saveProgress(nextStep: number, text = rawText) {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify({ step: nextStep, rawText: text }));
    } catch {
      // Storage unavailable (private mode) — the wizard still works in-memory.
    }
  }

  function goTo(next: number) {
    setStep(next);
    saveProgress(next);
  }

  const load = useCallback(async () => {
    setChecking(true);
    try {
      const [existing, fieldsData] = await Promise.all([
        fetchProfile().catch((e) => {
          if (e instanceof ApiError && e.status === 404) return null;
          throw e;
        }),
        fetchFields().catch(() => null),
      ]);
      if (existing) {
        // Skip onboarding: a profile already exists.
        router.replace("/");
        return;
      }
      setFields(fieldsData?.profiles ?? []);
      setField(fieldsData?.default ?? "");
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not load onboarding");
    } finally {
      setChecking(false);
    }
  }, [router]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load();
  }, [load]);

  async function handleStart() {
    const code = inviteCode.trim();
    if (!code) {
      setError("Enter your invite code to get started.");
      return;
    }
    setError(null);
    setInviting(true);
    try {
      await validateInvite(code);
      goTo(1);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Invite code is invalid");
    } finally {
      setInviting(false);
    }
  }

  async function handleExtract() {
    if (!rawText.trim()) {
      setError("Paste some CV or biography text first.");
      return;
    }
    setError(null);
    setBusy(true);
    try {
      const built = await buildProfile(rawText);
      setProfile(built);
      setField(built.domain || field);
      goTo(2);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not extract profile");
    } finally {
      setBusy(false);
    }
  }

  async function handleField() {
    if (!profile) return;
    setError(null);
    setBusy(true);
    try {
      const updated = await updateProfile({ domain: field });
      setProfile(updated);
      goTo(4);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not save field");
    } finally {
      setBusy(false);
    }
  }

  async function handleCountries() {
    if (!profile) return;
    const list = countries
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean);
    setError(null);
    setBusy(true);
    try {
      const updated = await updateProfile({ countries_preferred: list });
      setProfile(updated);
      goTo(5);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not save countries");
    } finally {
      setBusy(false);
    }
  }

  function finish() {
    try {
      localStorage.removeItem(STORAGE_KEY);
    } catch {
      // Ignore.
    }
    router.push("/");
  }

  const progress = useMemo(
    () => Math.round(((step + 1) / STEPS.length) * 100),
    [step],
  );

  if (checking) {
    return (
      <AuthGate>
        <div className="mx-auto max-w-2xl py-16 text-center text-sm text-muted-foreground">
          Checking your profile…
        </div>
      </AuthGate>
    );
  }

  return (
    <AuthGate>
      <div className="mx-auto flex max-w-2xl flex-col gap-6">
        <div className="flex flex-col gap-2">
          <h1 className="text-2xl font-semibold">Welcome to Career Intelligence</h1>
          <p className="text-sm text-muted-foreground">
            A few quick steps to personalize your matches.
          </p>
          <div className="flex items-center gap-2">
            <div className="h-2 flex-1 overflow-hidden rounded-full bg-muted">
              <div
                className="h-full bg-primary transition-all"
                style={{ width: `${progress}%` }}
                data-testid="onboarding-progress"
              />
            </div>
            <span className="text-xs tabular-nums text-muted-foreground">
              {step + 1}/{STEPS.length}
            </span>
          </div>
          <div className="flex flex-wrap gap-1.5" aria-label="Wizard steps">
            {STEPS.map((label, i) => (
              <Badge
                key={label}
                variant={i === step ? "default" : i < step ? "secondary" : "outline"}
              >
                {i + 1}. {label}
              </Badge>
            ))}
          </div>
        </div>

        {error && (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        )}

        {step === 0 && (
          <Card>
            <CardHeader>
              <CardTitle>Get started</CardTitle>
              <CardDescription>
                Enter your invite code, then we will build a research profile
                from your CV, pick your field, and set the countries you prefer
                — then score PhD opportunities against it.
              </CardDescription>
            </CardHeader>
            <CardContent className="flex flex-col gap-4">
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="onboarding-invite">Invite code</Label>
                <Input
                  id="onboarding-invite"
                  value={inviteCode}
                  onChange={(e) => {
                    setInviteCode(e.target.value);
                    setError(null);
                  }}
                  placeholder="Enter your invite code"
                />
              </div>
              <div className="flex justify-end">
                <Button onClick={handleStart} disabled={inviting}>
                  {inviting ? "Checking…" : "Start"}
                </Button>
              </div>
            </CardContent>
          </Card>
        )}

        {step === 1 && (
          <Card>
            <CardHeader>
              <CardTitle>Paste your CV or bio</CardTitle>
              <CardDescription>
                We extract a structured profile with an LLM — no file upload needed.
              </CardDescription>
            </CardHeader>
            <CardContent className="flex flex-col gap-3">
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="onboarding-cv">CV / bio text</Label>
                <Textarea
                  id="onboarding-cv"
                  rows={7}
                  value={rawText}
                  onChange={(e) => {
                    setRawText(e.target.value);
                    setError(null);
                  }}
                  placeholder={
                    "e.g. I am a PhD student in astronomy, working on the interstellar\nmedium with radio interferometry (LOFAR). I use Python and am\ninterested in dust polarization."
                  }
                />
              </div>
              <div className="flex justify-end gap-2">
                <Button variant="outline" onClick={() => goTo(0)}>
                  Back
                </Button>
                <Button onClick={handleExtract} disabled={busy}>
                  {busy ? "Extracting…" : "Extract profile"}
                </Button>
              </div>
            </CardContent>
          </Card>
        )}

        {step === 2 && profile && (
          <Card>
            <CardHeader>
              <CardTitle>Review your profile</CardTitle>
              <CardDescription>
                Confidence {Math.round(profile.confidence * 100)}%. You can refine
                these later on the Profile page.
              </CardDescription>
            </CardHeader>
            <CardContent className="flex flex-col gap-4">
              <dl className="grid gap-3 sm:grid-cols-2">
                <OnboardItem label="Domain" value={profile.domain} />
                <OnboardItem label="Subfield" value={profile.subfield ?? "—"} />
                <OnboardItem label="Experience" value={profile.experience_level} />
                <OnboardItem
                  label="Skills"
                  value={profile.skills.join(", ") || "—"}
                />
                <OnboardItem
                  label="Methods"
                  value={profile.methods.join(", ") || "—"}
                />
                <OnboardItem
                  label="Tools"
                  value={profile.tools.join(", ") || "—"}
                />
              </dl>
              <div className="flex justify-end gap-2">
                <Button variant="outline" onClick={() => goTo(1)}>
                  Back
                </Button>
                <Button onClick={() => goTo(3)}>Looks good</Button>
              </div>
            </CardContent>
          </Card>
        )}

        {step === 3 && (
          <Card>
            <CardHeader>
              <CardTitle>Select your field</CardTitle>
              <CardDescription>
                This drives the taxonomy used for matching.
              </CardDescription>
            </CardHeader>
            <CardContent className="flex flex-col gap-4">
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="onboarding-field">Field profile</Label>
                <Select value={field} onValueChange={(v) => setField(v ?? "")}>
                  <SelectTrigger id="onboarding-field" className="w-full">
                    <SelectValue placeholder="Select a field" />
                  </SelectTrigger>
                  <SelectContent>
                    {fields.map((f) => (
                      <SelectItem key={f} value={f}>
                        {f}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="flex justify-end gap-2">
                <Button variant="outline" onClick={() => goTo(2)}>
                  Back
                </Button>
                <Button onClick={handleField} disabled={busy || !field}>
                  {busy ? "Saving…" : "Continue"}
                </Button>
              </div>
            </CardContent>
          </Card>
        )}

        {step === 4 && (
          <Card>
            <CardHeader>
              <CardTitle>Preferred countries</CardTitle>
              <CardDescription>
                Comma-separated. Leave empty for worldwide results.
              </CardDescription>
            </CardHeader>
            <CardContent className="flex flex-col gap-4">
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="onboarding-countries">Countries</Label>
                <Input
                  id="onboarding-countries"
                  value={countries}
                  onChange={(e) => setCountries(e.target.value)}
                  placeholder="Germany, Netherlands, United States"
                />
              </div>
              <div className="flex justify-end gap-2">
                <Button variant="outline" onClick={() => goTo(3)}>
                  Back
                </Button>
                <Button onClick={handleCountries} disabled={busy}>
                  {busy ? "Saving…" : "Continue"}
                </Button>
              </div>
            </CardContent>
          </Card>
        )}

        {step === 5 && (
          <Card>
            <CardHeader>
              <CardTitle>You are all set</CardTitle>
              <CardDescription>
                Your profile is built and your preferences are saved.
              </CardDescription>
            </CardHeader>
            <CardContent className="flex justify-end">
              <Button onClick={finish}>Go to dashboard</Button>
            </CardContent>
          </Card>
        )}
      </div>
    </AuthGate>
  );
}

function OnboardItem({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col gap-0.5">
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="text-sm font-medium">{value}</dd>
    </div>
  );
}
