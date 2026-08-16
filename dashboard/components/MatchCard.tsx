"use client";

import { useEffect, useState } from "react";
import CoverLetterModal from "@/components/CoverLetterModal";
import SaveToggle from "@/components/SaveToggle";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import { Bookmark, ExternalLink, FileText, ThumbsDown, ThumbsUp } from "lucide-react";
import { buttonVariants } from "@/components/ui/button";
import { ApiError, fetchAssistantConfig, submitMatchFeedback } from "@/lib/api";
import type { Match } from "@/types";

interface Props {
  match: Match;
  onBookmark?: (match: Match) => void;
  /** Saved-item id when this match is saved, else null. Owned by the list, so
   *  a page of cards resolves every toggle in one request instead of N. */
  savedId?: number | null;
  onSavedChange?: (matchId: number, savedId: number | null) => void;
}

export default function MatchCard({ match, onBookmark, savedId = null, onSavedChange }: Props) {
  const [expanded, setExpanded] = useState(false);
  // AI drafting is behind ASSISTANT_ENABLED and off in the desktop build.
  // Assume off until the API says otherwise, so the button is never offered
  // and then withdrawn — and never offered only to fail when pressed.
  const [aiEnabled, setAiEnabled] = useState(false);

  useEffect(() => {
    fetchAssistantConfig()
      .then((c) => setAiEnabled(c.enabled))
      .catch(() => setAiEnabled(false));
  }, []);
  const [feedback, setFeedback] = useState<boolean | null>(null);
  const [feedbackMsg, setFeedbackMsg] = useState<string | null>(null);
  const [sending, setSending] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);
  const percent = Math.round(match.match_score * 100);

  async function sendFeedback(helpful: boolean) {
    if (sending || feedback !== null) return;
    setSending(true);
    setFeedbackMsg(null);
    try {
      await submitMatchFeedback(match.id, helpful);
      setFeedback(helpful);
      setFeedbackMsg(helpful ? "Marked as relevant" : "Marked as not relevant");
    } catch (e) {
      setFeedbackMsg(e instanceof ApiError ? e.message : "Feedback failed");
    } finally {
      setSending(false);
    }
  }

  return (
    <Card className="flex flex-col" data-testid="match-card">
      <CardHeader className="flex flex-row items-start justify-between gap-3">
        <div className="flex flex-col gap-1">
          <CardTitle className="text-base leading-snug">
            <a
              href={match.url ?? "#"}
              target="_blank"
              rel="noopener noreferrer"
              className="hover:underline"
            >
              {match.title}
            </a>
          </CardTitle>
          <CardDescription>
            {[match.institution, match.country, match.position_type]
              .filter(Boolean)
              .join(" · ") || "Institution n/a"}
          </CardDescription>
        </div>
        <div className="flex shrink-0 flex-col items-end gap-1">
          <Badge
            variant={percent >= 70 ? "default" : percent >= 40 ? "secondary" : "outline"}
            className="text-sm"
            data-testid="match-score"
          >
            {percent}%
          </Badge>
          <span className="text-xs text-muted-foreground">
            match score {match.match_score.toFixed(3)}
          </span>
        </div>
      </CardHeader>

      <CardContent className="flex flex-col gap-2">
        <div className="flex flex-wrap gap-1.5">
          {match.source && <Badge variant="outline">{match.source}</Badge>}
          {match.country && <Badge variant="outline">{match.country}</Badge>}
          {match.deadline && (
            <Badge variant="outline">Deadline {match.deadline.slice(0, 10)}</Badge>
          )}
        </div>

        <p className="text-sm text-muted-foreground" data-testid="match-explanation">
          {expanded
            ? match.match_explanation
            : `${match.match_explanation.slice(0, 160)}${match.match_explanation.length > 160 ? "…" : ""}`}
        </p>

        {expanded && (
          <div className="flex flex-col gap-1 text-sm">
            <Separator />
            <p className="font-medium">Why this matches</p>
            <div className="grid grid-cols-3 gap-2 text-center text-xs">
              <ScoreDim label="Topic" value={match.topic_score} />
              <ScoreDim label="Method" value={match.method_score} />
              <ScoreDim label="Location" value={match.location_score} />
            </div>
            {match.short_description && (
              <p className="mt-2 text-muted-foreground">{match.short_description}</p>
            )}
            {match.next_actions && match.next_actions.length > 0 && (
              <div className="mt-2 flex flex-col gap-1" data-testid="next-actions">
                <p className="font-medium">Suggested next steps</p>
                <ol className="list-decimal space-y-1 pl-4 text-muted-foreground">
                  {match.next_actions.slice(0, 5).map((step) => (
                    <li key={step}>{step}</li>
                  ))}
                </ol>
              </div>
            )}
            {match.suggestions && match.suggestions.length > 0 && (
              <p className="mt-1 text-xs text-muted-foreground" data-testid="suggestions">
                Consider learning: {match.suggestions.join(", ")}
              </p>
            )}
          </div>
        )}
      </CardContent>

      <CardFooter className="mt-auto flex items-center justify-between gap-2 pt-0">
        <Button
          variant="ghost"
          size="sm"
          onClick={() => setExpanded((e) => !e)}
          aria-expanded={expanded}
        >
          {expanded ? "Show less" : "Show details"}
        </Button>
        <div className="flex items-center gap-2">
          {feedbackMsg && (
            <span
              className="text-xs text-muted-foreground"
              data-testid="feedback-msg"
            >
              {feedbackMsg}
            </span>
          )}
          {aiEnabled && (
            <Button
              variant="outline"
              size="sm"
              onClick={() => setModalOpen(true)}
              aria-label="Draft a cover letter for this match"
            >
              <FileText className="size-4" aria-hidden />
            </Button>
          )}
          <div
            className="flex items-center gap-1"
            role="group"
            aria-label="Was this match relevant?"
          >
            <Button
              variant="ghost"
              size="sm"
              aria-label="This match is relevant"
              aria-pressed={feedback === true}
              disabled={sending || feedback !== null}
              onClick={() => void sendFeedback(true)}
            >
              <ThumbsUp className="size-4" aria-hidden />
            </Button>
            <Button
              variant="ghost"
              size="sm"
              aria-label="This match is not relevant"
              aria-pressed={feedback === false}
              disabled={sending || feedback !== null}
              onClick={() => void sendFeedback(false)}
            >
              <ThumbsDown className="size-4" aria-hidden />
            </Button>
          </div>
          {onSavedChange ? (
            <SaveToggle
              kind="opportunity"
              recordId={match.id}
              savedId={savedId}
              onChange={({ savedId: next }) => onSavedChange(match.id, next)}
            />
          ) : (
            onBookmark && (
              <Button
                variant="outline"
                size="sm"
                onClick={() => onBookmark(match)}
                aria-label="Bookmark this match"
              >
                <Bookmark className="size-4" aria-hidden />
              </Button>
            )
          )}
          {match.url && (
            <a
              href={match.url}
              target="_blank"
              rel="noopener noreferrer"
              className={buttonVariants({ variant: "outline", size: "sm" })}
            >
              Original <ExternalLink className="size-3.5" aria-hidden />
            </a>
          )}
        </div>
      </CardFooter>
      {aiEnabled && (
        <CoverLetterModal
          open={modalOpen}
          onOpenChange={setModalOpen}
          match={match}
        />
      )}
    </Card>
  );
}

function ScoreDim({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-md border p-2">
      <p className="text-muted-foreground">{label}</p>
      <p className="font-semibold">{value.toFixed(2)}</p>
    </div>
  );
}
