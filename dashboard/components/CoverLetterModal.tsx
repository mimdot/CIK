"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { ApiError, fetchAssistantUsage, generateCoverLetter } from "@/lib/api";
import type { AssistantDraft, Match } from "@/types";

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  match: Match;
}

export default function CoverLetterModal({ open, onOpenChange, match }: Props) {
  const [tone, setTone] = useState("professional");
  const [length, setLength] = useState("medium");
  const [text, setText] = useState("");
  const [model, setModel] = useState<string | null>(null);
  const [usage, setUsage] = useState<string | null>(null);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  function handleOpenChange(next: boolean) {
    if (!next) {
      setText("");
      setModel(null);
      setUsage(null);
      setError(null);
      setCopied(false);
    }
    onOpenChange(next);
  }

  async function handleGenerate() {
    setGenerating(true);
    setError(null);
    try {
      const draft: AssistantDraft = await generateCoverLetter(match.id, {
        tone,
        length,
      });
      setText(draft.text);
      setModel(draft.model);
      try {
        const u = await fetchAssistantUsage();
        setUsage(`${u.used} of ${u.limit} daily drafts used`);
      } catch {
        setUsage(null);
      }
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not generate draft");
    } finally {
      setGenerating(false);
    }
  }

  async function handleCopy() {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      setCopied(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>Draft cover letter</DialogTitle>
          <DialogDescription>
            {match.title} · {match.institution} · {match.country}
          </DialogDescription>
        </DialogHeader>

        <div className="flex flex-col gap-3">
          <div className="grid grid-cols-2 gap-3">
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="cl-tone">Tone</Label>
              <Select value={tone} onValueChange={(v) => setTone(v ?? "professional")}>
                <SelectTrigger id="cl-tone">
                  <SelectValue placeholder="Tone" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="professional">Professional</SelectItem>
                  <SelectItem value="warm">Warm</SelectItem>
                  <SelectItem value="enthusiastic">Enthusiastic</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="cl-length">Length</Label>
              <Select value={length} onValueChange={(v) => setLength(v ?? "medium")}>
                <SelectTrigger id="cl-length">
                  <SelectValue placeholder="Length" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="short">Short (~150 words)</SelectItem>
                  <SelectItem value="medium">Medium (~250 words)</SelectItem>
                  <SelectItem value="long">Long (~400 words)</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>

          {error && (
            <p className="rounded-md border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive">
              {error}
            </p>
          )}

          {text ? (
            <>
              <Textarea
                value={text}
                onChange={(e) => setText(e.target.value)}
                rows={14}
                aria-label="Cover letter draft (editable)"
                data-testid="cover-letter-draft"
              />
              <div className="flex items-center justify-between text-xs text-muted-foreground">
                <span data-testid="cover-letter-quota">
                  {usage ?? "Editable draft — nothing is submitted."}
                </span>
                {model && <span>{model}</span>}
              </div>
            </>
          ) : (
            <p className="text-sm text-muted-foreground">
              Generate a grounded draft from your profile facts and this
              posting. You can edit it before applying.
            </p>
          )}
        </div>

        <DialogFooter>
          <Button
            variant="outline"
            onClick={() => void handleCopy()}
            disabled={!text || copied}
          >
            {copied ? "Copied" : "Copy"}
          </Button>
          <Button
            variant="outline"
            onClick={onOpenChange.bind(null, false)}
            disabled={generating}
          >
            Close
          </Button>
          <Button
            onClick={() => void handleGenerate()}
            disabled={generating}
            data-testid="generate-cover-letter"
          >
            {generating ? "Drafting…" : text ? "Regenerate" : "Generate"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}