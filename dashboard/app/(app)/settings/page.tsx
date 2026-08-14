"use client";

import { useCallback, useEffect, useState } from "react";
import AuthGate from "@/components/AuthGate";
import { Badge } from "@/components/ui/badge";
import { DonationPlaceholder } from "@/components/ComingSoon";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { useToast } from "@/components/ui/toast";
import {
  ApiError,
  fetchFields,
  fetchMe,
  fetchPreferences,
  fetchProfile,
  updateDigestPreference,
  updateProfile,
} from "@/lib/api";
import type { User } from "@/types";

export default function SettingsPage() {
  const [fields, setFields] = useState<{ default: string; profiles: string[] } | null>(null);
  const [profile, setProfile] = useState("");
  const [me, setMe] = useState<User | null>(null);
  const [digest, setDigest] = useState(false);
  const [saving, setSaving] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const { toast } = useToast();

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [fieldsData, meData, prefs, userProfile] = await Promise.all([
        fetchFields(),
        fetchMe().catch(() => null),
        fetchPreferences(),
        // The field shown here IS the profile's field — not a second,
        // competing setting that silently does nothing.
        fetchProfile().catch(() => null),
      ]);
      setFields(fieldsData);
      setProfile(userProfile?.domain || fieldsData.default);
      setMe(meData);
      setDigest(prefs.digest_enabled);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not load settings");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load();
  }, [load]);

  /** Save the field to the user's profile — the single place it lives. */
  async function changeField(next: string) {
    const previous = profile;
    setProfile(next);
    setSaving(true);
    setError(null);
    try {
      await updateProfile({ domain: next });
      toast(`Your field is now ${next}`, { variant: "success" });
    } catch (e) {
      setProfile(previous);
      const msg = e instanceof ApiError ? e.message : "Could not save your field";
      setError(msg);
      toast("Could not save", { description: msg, variant: "destructive" });
    } finally {
      setSaving(false);
    }
  }

  async function toggleDigest() {
    if (saving) return;
    const next = !digest;
    setDigest(next);
    setSaving(true);
    setError(null);
    try {
      const saved = await updateDigestPreference(next);
      setDigest(saved.digest_enabled);
      toast(
        saved.digest_enabled ? "Email digest enabled" : "Email digest disabled",
        { variant: "success" },
      );
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : "Could not save preference";
      setDigest(!next);
      setError(msg);
      toast("Save failed", { description: msg, variant: "destructive" });
    } finally {
      setSaving(false);
    }
  }

  return (
    <AuthGate>
      <div className="flex flex-col gap-5">
        <div>
          <h1 className="text-2xl font-semibold">Settings</h1>
          <p className="text-sm text-muted-foreground">
            Your research field and notification preferences.
          </p>
        </div>

        {error && <p className="text-sm text-destructive">{error}</p>}

        <Card>
          <CardHeader>
            <CardTitle className="text-base">Account</CardTitle>
            <CardDescription>
              The account used by this dashboard instance.
            </CardDescription>
          </CardHeader>
          <CardContent>
            {loading ? (
              <Skeleton className="h-4 w-48" />
            ) : me ? (
              <p className="text-sm">
                Signed in as{" "}
                <span className="font-medium text-foreground">{me.email}</span>
              </p>
            ) : (
              <p className="text-sm text-muted-foreground">
                Account details unavailable.
              </p>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">Your research field</CardTitle>
            <CardDescription>
              Decides which job boards are searched, which keywords are offered,
              and which publication database finds your supervisors. Changing it
              here changes it everywhere.
            </CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-3">
            {loading ? (
              <Skeleton className="h-9 w-full sm:w-72" />
            ) : fields && fields.profiles.length > 0 ? (
              <>
                <Select
                  value={profile}
                  onValueChange={(v) => void changeField(v ?? fields.default)}
                >
                  <SelectTrigger className="w-full sm:w-72" aria-label="Field profile">
                    <SelectValue placeholder="Select a field" />
                  </SelectTrigger>
                  <SelectContent>
                    {fields.profiles.map((f) => (
                      <SelectItem key={f} value={f}>
                        {f}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <p className="text-xs text-muted-foreground">
                  {saving
                    ? "Saving…"
                    : "This is the same field shown on your Profile page."}
                </p>
              </>
            ) : (
              <p className="text-sm text-muted-foreground">
                No field profiles available.
              </p>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <div className="flex items-center gap-2">
              <CardTitle className="text-base">Notifications</CardTitle>
              <Badge variant="outline">Coming soon</Badge>
            </div>
            <CardDescription>
              A weekly email summarising new positions that match you. Not
              switched on yet — your preference is remembered for when it is.
            </CardDescription>
          </CardHeader>
          <CardContent className="flex flex-wrap items-center gap-3">
            <p className="text-sm text-muted-foreground">
              Email me a weekly digest once this is available.
            </p>
            <Button
              variant={digest ? "default" : "outline"}
              onClick={() => void toggleDigest()}
              disabled={saving || loading}
              aria-pressed={digest}
            >
              {saving ? "Saving…" : digest ? "Yes, when ready" : "No thanks"}
            </Button>
          </CardContent>
        </Card>

        <DonationPlaceholder />
      </div>
    </AuthGate>
  );
}
