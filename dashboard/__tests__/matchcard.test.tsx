import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import MatchCard from "@/components/MatchCard";
import { submitMatchFeedback } from "@/lib/api";
import type { Match } from "@/types";

jest.mock("@/lib/api", () => ({
  ...jest.requireActual("@/lib/api"),
  submitMatchFeedback: jest.fn(),
}));

const mockSubmitFeedback = submitMatchFeedback as jest.Mock;

beforeEach(() => {
  jest.clearAllMocks();
});

const MATCH: Match = {
  id: 7,
  source: "euraxess",
  title: "PhD in radio astronomy",
  institution: "MPIfR",
  department: null,
  country: "Germany",
  city: null,
  url: "https://ex.org/job/7",
  type: null,
  field: null,
  subfield: null,
  topics: [],
  deadline: "2026-09-30",
  posted_date: null,
  effective_date: null,
  freshness: null,
  relevance_score: 8.0,
  short_description: "Doctoral project on radio astronomy and the ISM.",
  position_type: "phd",
  is_new: true,
  match_score: 0.9,
  match_explanation:
    "Strong topic match: your astronomy/interstellar medium aligns directly with this position.",
  topic_score: 0.9,
  method_score: 0.8,
  location_score: 1.0,
  confidence: 0.9,
};

describe("MatchCard", () => {
  it("renders title, institution, country, score and explanation", () => {
    render(<MatchCard match={MATCH} />);
    expect(screen.getByText("PhD in radio astronomy")).toBeInTheDocument();
    expect(screen.getByText(/MPIfR · Germany/)).toBeInTheDocument();
    expect(screen.getByTestId("match-score")).toHaveTextContent("90%");
    expect(screen.getByTestId("match-explanation")).toHaveTextContent(
      "Strong topic match",
    );
  });

  it("shows a raw match score badge", () => {
    render(<MatchCard match={MATCH} />);
    expect(screen.getByText(/match score 0\.900/)).toBeInTheDocument();
  });

  it("links to the original posting", () => {
    render(<MatchCard match={MATCH} />);
    const link = screen.getByText("Original");
    expect(link).toHaveAttribute("href", "https://ex.org/job/7");
  });

  it("expands to show dimension scores", async () => {
    const user = userEvent.setup();
    render(<MatchCard match={MATCH} />);
    expect(screen.queryByText("Why this matches")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Show details" }));

    expect(screen.getByText("Why this matches")).toBeInTheDocument();
    expect(screen.getByText("Topic")).toBeInTheDocument();
    expect(screen.getByText("Method")).toBeInTheDocument();
    expect(screen.getByText("Location")).toBeInTheDocument();
  });

  it("calls onBookmark when the bookmark button is clicked", async () => {
    const onBookmark = jest.fn();
    const user = userEvent.setup();
    render(<MatchCard match={MATCH} onBookmark={onBookmark} />);

    await user.click(
      screen.getByRole("button", { name: "Bookmark this match" }),
    );
    expect(onBookmark).toHaveBeenCalledWith(MATCH);
  });

  it("truncates long explanations until expanded", () => {
    const longMatch: Match = {
      ...MATCH,
      match_explanation: "word ".repeat(50).trim(),
    };
    render(<MatchCard match={longMatch} />);
    const text = screen.getByTestId("match-explanation").textContent ?? "";
    expect(text).toContain("…");
  });

  it("submits thumbs-up feedback and confirms", async () => {
    mockSubmitFeedback.mockResolvedValue({ status: "ok" });
    const user = userEvent.setup();
    render(<MatchCard match={MATCH} />);

    await user.click(
      screen.getByRole("button", { name: "This match is relevant" }),
    );

    expect(mockSubmitFeedback).toHaveBeenCalledWith(MATCH.id, true);
    expect(
      await screen.findByText("Marked as relevant"),
    ).toBeInTheDocument();
  });

  it("submits thumbs-down feedback", async () => {
    mockSubmitFeedback.mockResolvedValue({ status: "ok" });
    const user = userEvent.setup();
    render(<MatchCard match={MATCH} />);

    await user.click(
      screen.getByRole("button", { name: "This match is not relevant" }),
    );

    expect(mockSubmitFeedback).toHaveBeenCalledWith(MATCH.id, false);
    await waitFor(() =>
      expect(screen.getByTestId("feedback-msg")).toHaveTextContent(
        "Marked as not relevant",
      ),
    );
  });

  it("only submits feedback once per card", async () => {
    mockSubmitFeedback.mockResolvedValue({ status: "ok" });
    const user = userEvent.setup();
    render(<MatchCard match={MATCH} />);

    await user.click(
      screen.getByRole("button", { name: "This match is relevant" }),
    );
    await user.click(
      screen.getByRole("button", { name: "This match is not relevant" }),
    );

    expect(mockSubmitFeedback).toHaveBeenCalledTimes(1);
  });
});
