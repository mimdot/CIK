"use client";

import {
  cloneElement,
  isValidElement,
  useCallback,
  useEffect,
  useId,
  useState,
  type ChangeEvent,
  type ReactElement,
} from "react";
import AuthGate from "@/components/AuthGate";
import { Badge } from "@/components/ui/badge";
import { Button, buttonVariants } from "@/components/ui/button";
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
import {
  analyseCv,
  ApiError,
  buildProfile,
  extractCv,
  fetchParserSupport,
  fetchProfile,
  updateProfile,
} from "@/lib/api";
import { FieldPicker } from "@/components/FieldPicker";
import { KeywordPicker } from "@/components/KeywordPicker";
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
  const [busy, setBusy] = useState<"build" | "save" | "load" | "upload" | null>(null);
  // The keyword picker is the PRIMARY path (3C): a CV only pre-fills it.
  const [field, setField] = useState("");
  const [keywords, setKeywords] = useState<string[]>([]);
  const [cvOpen, setCvOpen] = useState(false);
  const [analysisNote, setAnalysisNote] = useState<string | null>(null);
  const [parserSupport, setParserSupport] = useState<{
    txt: boolean;
    pdf: boolean;
    docx: boolean;
    enabled: boolean;
  } | null>(null);
  // Until the API has answered, assume OFF. Rendering the upload control first
  // and retracting it would offer a feature and then take it away.
  const cvEnabled = parserSupport?.enabled === true;
  const { toast } = useToast();

  const load = useCallback(async () => {
    setError(null);
    try {
      const loaded = await fetchProfile();
      setProfile(loaded);
      // Seed the picker from whatever is already saved, so the page opens
      // showing the user's real selection rather than an empty form.
      setField(loaded.domain || "");
      setKeywords(loaded.skills ?? []);
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

  // Know what this installation can read BEFORE the user picks a file.
  useEffect(() => {
    fetchParserSupport()
      .then(setParserSupport)
      .catch(() => setParserSupport(null));
  }, []);

  function revalidate(p: UserProfile) {
    setFieldErrors(validateProfile(p));
  }

  async function handleUpload(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    e.target.value = ""; // allow re-selecting the same file
    if (!file) return;
    setError(null);
    setBusy("upload");
    try {
      const res = await extractCv(file);
      setRawText(res.raw_text);
      toast(`Extracted ${res.chars} characters from ${res.filename}`, {
        variant: "success",
      });
    } catch (err) {
      const msg = err instanceof ApiError ? err.message : "Could not read the file";
      setError(msg);
      toast("Could not read the file", { description: msg, variant: "destructive" });
    } finally {
      setBusy(null);
    }
  }

  /**
   * Read the CV and TICK the matching keywords — no AI service involved.
   * Never a dead end: when nothing is recognised it says which case applies
   * and leaves the picker exactly as it was.
   */
  async function handleAnalyse() {
    if (!rawText.trim()) {
      setError("Paste some CV text first, or upload a file.");
      return;
    }
    setError(null);
    setAnalysisNote(null);
    setBusy("build");
    try {
      const result = await analyseCv(rawText, field || undefined);
      if (result.field && !field) setField(result.field);
      if (result.keywords.length) {
        setKeywords((prev) => [...new Set([...prev, ...result.keywords])]);
      }
      setAnalysisNote(
        result.found_anything
          ? `Found ${result.keywords.length} keyword${
              result.keywords.length === 1 ? "" : "s"
            }${result.field ? ` and suggested the field “${result.field}”` : ""}. ` +
            "They are ticked above — edit them, then Save."
          : result.notes[0] ?? "Nothing recognisable was found in this text.",
      );
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : "Could not read the text";
      setError(msg);
    } finally {
      setBusy(null);
    }
  }

  /** Save just the field + keywords — the whole profile the app needs. */
  async function handleSaveKeywords() {
    setError(null);
    setBusy("save");
    try {
      const saved = await updateProfile({
        domain: field || undefined,
        skills: keywords,
      });
      setProfile(saved);
      revalidate(saved);
      toast("Keywords saved", { variant: "success" });
    } catch (e) {
      // No profile row yet (404) — build one from the selection itself, so a
      // brand-new user never has to go through the CV path at all.
      if (e instanceof ApiError && e.status === 404) {
        try {
          const seed = [field, ...keywords].filter(Boolean).join(", ");
          const built = await buildProfile(
            `Research field: ${field}. Keywords: ${seed}.`,
          );
          setProfile(built);
          revalidate(built);
          toast("Profile created from your keywords", { variant: "success" });
          return;
        } catch {
          /* fall through to the error below */
        }
      }
      const msg = e instanceof ApiError ? e.message : "Could not save";
      setError(msg);
      toast("Could not save", { description: msg, variant: "destructive" });
    } finally {
      setBusy(null);
    }
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
          <h1 className="text-2xl font-semibold">Your research profile</h1>
          <p className="text-sm text-muted-foreground">
            Pick your field and the keywords you work on. That is all the app
            needs
            {cvEnabled
              ? " — a CV is optional and only pre-fills these choices."
              : " to find and rank matches for you."}
          </p>
        </div>

        {/* PRIMARY PATH (3C). Picking from the curated list is more reliable
            than parsing a CV, needs no AI service, and every term here is one
            the matching engine actually understands. */}
        <div className="flex flex-col gap-4 rounded-lg border bg-card p-4">
          <FieldPicker
            field={field}
            onFieldChange={setField}
            subfields={[]}
            onSubfieldsChange={() => {}}
            idPrefix="profile-field"
            hint="Your field decides which keywords are offered below, and which job boards and publication databases are searched for you."
          />
          <KeywordPicker
            field={field}
            selected={keywords}
            onChange={setKeywords}
          />
          <div className="flex flex-wrap items-center gap-2">
            <Button onClick={() => void handleSaveKeywords()} disabled={busy !== null}>
              {busy === "save" ? "Saving…" : "Save my keywords"}
            </Button>
            <span className="text-xs text-muted-foreground">
              {keywords.length} keyword{keywords.length === 1 ? "" : "s"} selected
            </span>
          </div>
        </div>

        {/* Switched off for now (CV_PARSING_ENABLED). Stated as a plan rather
            than shown as a control that refuses to work — a disabled button
            with no explanation reads as a broken app. */}
        {!cvEnabled ? (
          <div
            className="flex flex-col gap-1 rounded-lg border border-dashed p-4"
            data-testid="cv-coming-soon"
          >
            <p className="text-sm font-medium text-muted-foreground">
              Reading your CV — coming in a future update
            </p>
            <p className="text-xs text-muted-foreground">
              For now, pick your field and keywords above. That is all the app
              needs to find and rank matches for you.
            </p>
          </div>
        ) : (
          <div className="flex flex-col gap-2 rounded-lg border p-4">
            <button
              type="button"
              className="text-left text-sm font-medium underline-offset-4 hover:underline"
              onClick={() => setCvOpen((v) => !v)}
              aria-expanded={cvOpen}
            >
              {cvOpen ? "Hide" : "Optional:"} pre-fill from a CV
            </button>
            <p className="text-xs text-muted-foreground">
              Reads your CV locally and ticks the matching keywords above. You
              stay in control — nothing is saved until you press Save.
            </p>
          </div>
        )}

        {/* Not rendered at all when the feature is off — not merely hidden.
            A `display:none` block still holds a focusable file input and live
            buttons, which is the difference between "absent" and "disabled". */}
        {cvEnabled && (
        <div className={cvOpen ? "flex flex-col gap-2" : "hidden"}>
          <Label htmlFor="cv">CV / bio text</Label>
          <Textarea
            id="cv"
            rows={7}
            value={rawText}
            onChange={(e) => setRawText(e.target.value)}
            placeholder={"Paste your CV here…\n\ne.g. I am a PhD student in astronomy, working on interstellar medium with radio interferometry (LOFAR). I use Python and am interested in dust polarization."}
          />
          <div className="flex flex-wrap items-center gap-2">
            <label
              htmlFor="cv-file"
              className={buttonVariants({ variant: "outline" })}
              data-disabled={busy !== null ? "" : undefined}
            >
              {busy === "upload" ? "Reading file…" : "Upload CV (PDF, DOCX, TXT)"}
            </label>
            <input
              id="cv-file"
              type="file"
              accept=".pdf,.docx,.txt,.md,text/plain,application/pdf"
              className="sr-only"
              aria-label="Upload CV file"
              disabled={busy !== null}
              onChange={handleUpload}
            />
            <Button onClick={() => void handleAnalyse()} disabled={busy !== null}>
              {busy === "build" ? "Reading…" : "Pre-fill my keywords"}
            </Button>
            <Button variant="outline" onClick={handleBuild} disabled={busy !== null}>
              {busy === "build" ? "Building…" : "Build full profile"}
            </Button>
            <Button variant="outline" onClick={() => void load()} disabled={busy !== null}>
              Reload profile
            </Button>
          </div>
          {analysisNote && (
            <p className="rounded-md border bg-muted/40 p-2 text-xs text-muted-foreground">
              {analysisNote}
            </p>
          )}
          <p className="text-xs text-muted-foreground">
            Files are parsed locally on the server — never sent to a third party
            or stored.
            {parserSupport && !parserSupport.pdf && (
              <span className="text-destructive">
                {" "}
                This installation cannot read PDF files — paste the text above
                instead.
              </span>
            )}
          </p>
        </div>
        )}

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
  // Associate the label with its control. Without this the inputs had no
  // accessible name at all — a screen reader announced "edit text" with no
  // indication of which profile field it was.
  const id = useId();
  const control = isValidElement(children)
    ? cloneElement(children as ReactElement<{ id?: string }>, { id })
    : children;
  return (
    <div className="flex flex-col gap-1.5">
      <Label htmlFor={id}>{label}</Label>
      {control}
      {error && <p className="text-xs text-destructive">{error}</p>}
    </div>
  );
}
