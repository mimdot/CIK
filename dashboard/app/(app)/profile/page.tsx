"use client";

import { useCallback, useEffect, useState } from "react";
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
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { useToast } from "@/components/ui/toast";
import { ApiError, buildProfile, fetchProfile, updateProfile } from "@/lib/api";
import type { UserProfile } from "@/types";

const EXPERIENCE_LEVELS = [
  "phd_student",
  "postdoc",
  "faculty",
  "industry",
  "other",
];

type FieldErrors = Partial<Record<"domain" | "confidence" | "experience_level", string>>;

function validateProfile(profile: UserProfile): FieldErrors {
  const errors: FieldErrors = {};
  if (!profile.domain || !profile.domain.trim()) {
    errors.domain = "Domain is required.";
  }
  const conf = Number(profile.confidence);
  if (!Number.isFinite(conf) || conf < 0 || conf > 1) {
    errors.confidence = "Confidence must be between 0 and 1.";
  }
  if (!EXPERIENCE_LEVELS.includes(profile.experience_level)) {
    errors.experience_level = `Experience level must be one of: ${EXPERIENCE_LEVELS.join(", ")}.`;
  }
  return errors;
}

export default function ProfilePage() {
  const [rawText, setRawText] = useState("");
  const [profile, setProfile] = useState<UserProfile | null>(null);
  const [fieldErrors, setFieldErrors] = useState<FieldErrors>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<"build" | "save" | "load" | null>(null);
  const { toast } = useToast();

  const load = useCallback(async () => {
    setError(null);
    try {
      setProfile(await fetchProfile());
    } catch (e) {
      setProfile(null);
      if (!(e instanceof ApiError) || e.status !== 404) {
        setError(e instanceof ApiError ? e.message : "Could not load profile");
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load();
  }, [load]);

  function revalidate(p: UserProfile) {
    setFieldErrors(validateProfile(p));
  }

  async function handleBuild() {
    if (!rawText.trim()) {
      setError("Paste some CV or biography text first.");
      return;
    }
    setError(null);
    setBusy("build");
    try {
      const built = await buildProfile(rawText);
      setProfile(built);
      revalidate(built);
      toast("Profile rebuilt from CV", { variant: "success" });
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : "Build failed";
      setError(msg);
      toast("Build failed", { description: msg, variant: "destructive" });
    } finally {
      setBusy(null);
    }
  }

  async function handleSave() {
    if (!profile) return;
    const errors = validateProfile(profile);
    setFieldErrors(errors);
    if (Object.keys(errors).length > 0) {
      setError("Please fix the highlighted fields before saving.");
      return;
    }
    setError(null);
    setBusy("save");
    try {
      const updated = await updateProfile({ ...profile });
      setProfile(updated);
      revalidate(updated);
      toast("Profile saved", { variant: "success" });
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : "Save failed";
      setError(msg);
      toast("Save failed", { description: msg, variant: "destructive" });
    } finally {
      setBusy(null);
    }
  }

  function update<K extends keyof UserProfile>(key: K, value: UserProfile[K]) {
    setProfile((p) => {
      if (!p) return p;
      const next = { ...p, [key]: value };
      setFieldErrors(validateProfile(next));
      return next;
    });
  }

  function updateList(
    key: "methods" | "tools" | "skills" | "target_roles" | "countries_preferred" | "constraints",
    value: string,
  ) {
    const items = value
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean);
    update(key, items as UserProfile[typeof key]);
  }

  return (
    <AuthGate>
      <div className="flex flex-col gap-6">
        <div>
          <h1 className="text-2xl font-semibold">Profile builder</h1>
          <p className="text-sm text-muted-foreground">
            Paste your CV or a short bio. We extract a structured profile with an
            LLM, then you can adjust it before saving.
          </p>
        </div>

        <div className="flex flex-col gap-2">
          <Label htmlFor="cv">CV / bio text</Label>
          <Textarea
            id="cv"
            rows={7}
            value={rawText}
            onChange={(e) => setRawText(e.target.value)}
            placeholder={"Paste your CV here…\n\ne.g. I am a PhD student in astronomy, working on interstellar medium with radio interferometry (LOFAR). I use Python and am interested in dust polarization."}
          />
          <div className="flex flex-wrap gap-2">
            <Button onClick={handleBuild} disabled={busy !== null}>
              {busy === "build" ? "Building…" : "Re-build from CV"}
            </Button>
            <Button variant="outline" onClick={() => void load()} disabled={busy !== null}>
              Reload profile
            </Button>
          </div>
        </div>

        {error && (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        )}

        {loading && (
          <Card>
            <CardHeader>
              <Skeleton className="h-5 w-40" />
              <Skeleton className="h-4 w-64" />
            </CardHeader>
            <CardContent className="grid gap-4 sm:grid-cols-2">
              {Array.from({ length: 8 }).map((_, i) => (
                <div key={i} className="flex flex-col gap-1.5">
                  <Skeleton className="h-3 w-24" />
                  <Skeleton className="h-9 w-full" />
                </div>
              ))}
            </CardContent>
          </Card>
        )}

        {!loading && !profile && (
          <div className="rounded-md border p-8 text-center text-sm text-muted-foreground">
            No profile yet. Paste your CV above and press “Re-build from CV” to
            create one.
          </div>
        )}

        {profile && (
          <Card>
            <CardHeader className="flex flex-row items-center justify-between gap-4">
              <div>
                <CardTitle>Your profile</CardTitle>
                <CardDescription>
                  Confidence:{" "}
                  <span className="font-semibold">
                    {Math.round(profile.confidence * 100)}%
                  </span>
                </CardDescription>
              </div>
              <Badge variant="secondary">{profile.experience_level}</Badge>
            </CardHeader>
            <CardContent className="grid gap-4 sm:grid-cols-2">
              <Field label="Domain" error={fieldErrors.domain}>
                <Input
                  value={profile.domain}
                  aria-invalid={Boolean(fieldErrors.domain)}
                  onChange={(e) => update("domain", e.target.value)}
                />
              </Field>
              <Field label="Subfield">
                <Input value={profile.subfield ?? ""} onChange={(e) => update("subfield", e.target.value || null)} />
              </Field>
              <Field label="Experience level" error={fieldErrors.experience_level}>
                <Select
                  value={profile.experience_level}
                  onValueChange={(v) => update("experience_level", v ?? "other")}
                >
                  <SelectTrigger
                    className="w-full"
                    aria-label="Experience level"
                    aria-invalid={Boolean(fieldErrors.experience_level)}
                  >
                    <SelectValue placeholder="Select a level" />
                  </SelectTrigger>
                  <SelectContent>
                    {EXPERIENCE_LEVELS.map((level) => (
                      <SelectItem key={level} value={level}>
                        {level}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </Field>
              <Field label="Confidence (0–1)" error={fieldErrors.confidence}>
                <Input
                  type="number"
                  min={0}
                  max={1}
                  step={0.01}
                  value={profile.confidence}
                  aria-invalid={Boolean(fieldErrors.confidence)}
                  onChange={(e) =>
                    update("confidence", Number.parseFloat(e.target.value) || 0)
                  }
                />
              </Field>
              <Field label="Methods (comma separated)">
                <Input value={profile.methods.join(", ")} onChange={(e) => updateList("methods", e.target.value)} />
              </Field>
              <Field label="Tools (comma separated)">
                <Input value={profile.tools.join(", ")} onChange={(e) => updateList("tools", e.target.value)} />
              </Field>
              <Field label="Skills (comma separated)">
                <Input value={profile.skills.join(", ")} onChange={(e) => updateList("skills", e.target.value)} />
              </Field>
              <Field label="Target roles (comma separated)">
                <Input value={profile.target_roles.join(", ")} onChange={(e) => updateList("target_roles", e.target.value)} />
              </Field>
              <Field label="Preferred countries (comma separated)">
                <Input value={profile.countries_preferred.join(", ")} onChange={(e) => updateList("countries_preferred", e.target.value)} />
              </Field>
              <Field label="Constraints (comma separated)">
                <Input value={profile.constraints.join(", ")} onChange={(e) => updateList("constraints", e.target.value)} />
              </Field>
              <Field label="Funding requirement">
                <Input value={profile.funding_requirement ?? ""} onChange={(e) => update("funding_requirement", e.target.value || null)} />
              </Field>
              <div className="flex items-end">
                <Button
                  onClick={handleSave}
                  disabled={busy !== null || Object.keys(fieldErrors).length > 0}
                >
                  {busy === "save" ? "Saving…" : "Save profile"}
                </Button>
              </div>
            </CardContent>
          </Card>
        )}
      </div>
    </AuthGate>
  );
}

function Field({
  label,
  error,
  children,
}: {
  label: string;
  error?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <Label>{label}</Label>
      {children}
      {error && <p className="text-xs text-destructive">{error}</p>}
    </div>
  );
}
