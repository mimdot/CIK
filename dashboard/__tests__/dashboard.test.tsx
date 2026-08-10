import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import DashboardPage from "@/app/(app)/page";
import { ApiError, createBookmark, fetchMatches } from "@/lib/api";
import type { Match } from "@/types";

jest.mock("@/lib/api", () => ({
  ApiError: class ApiError extends Error {
    status: number;
    constructor(message: string, status: number) {
      super(message);
      this.status = status;
    }
  },
  getToken: jest.fn(() => "test-token"),
  login: jest.fn(),
  register: jest.fn(),
  fetchMatches: jest.fn(),
  createBookmark: jest.fn(),
}));

const mockFetchMatches = fetchMatches as jest.Mock;
const mockCreateBookmark = createBookmark as jest.Mock;

function match(overrides: Partial<Match>): Match {
  return {
    id: 1,
    source: "euraxess",
    title: "PhD in radio astronomy",
    institution: "MPIfR",
    department: null,
    country: "Germany",
    city: null,
    url: "https://ex.org/job/1",
    type: null,
    field: null,
    subfield: null,
    topics: [],
    deadline: null,
    posted_date: null,
    effective_date: null,
    freshness: null,
    relevance_score: 8,
    short_description: null,
    position_type: "phd",
    is_new: true,
    match_score: 0.5,
    match_explanation: "Partial topic match",
    topic_score: 0.5,
    method_score: 0.5,
    location_score: 0.5,
    confidence: 0.9,
    ...overrides,
  };
}

const MATCHES: Match[] = [
  match({ id: 1, title: "PhD in radio astronomy", country: "Germany", source: "euraxess", match_score: 0.9, match_explanation: "Strong topic match: radio astronomy aligns with your background." }),
  match({ id: 2, title: "Postdoc in cosmology", country: "Netherlands", source: "findaphd", position_type: "postdoc", match_score: 0.7, match_explanation: "Partial topic match" }),
  match({ id: 3, title: "PhD in ISM", country: "Germany", source: "eso", match_score: 0.5, match_explanation: "Partial topic match" }),
];

describe("DashboardPage", () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it("renders match cards sorted by score", async () => {
    mockFetchMatches.mockResolvedValue({ items: MATCHES, total: 3 });
    render(<DashboardPage />);

    const cards = await screen.findAllByTestId("match-card");
    expect(cards).toHaveLength(3);

    const scores = screen
      .getAllByTestId("match-score")
      .map((el) => el.textContent);
    expect(scores).toEqual(["90%", "70%", "50%"]);
  });

  it("shows the match explanation on each card", async () => {
    mockFetchMatches.mockResolvedValue({ items: MATCHES, total: 3 });
    render(<DashboardPage />);
    await screen.findAllByTestId("match-card");
    expect(
      screen.getByText(/Strong topic match: radio astronomy aligns/),
    ).toBeInTheDocument();
  });

  it("filters matches by country", async () => {
    mockFetchMatches.mockResolvedValue({ items: MATCHES, total: 3 });
    const user = userEvent.setup();
    render(<DashboardPage />);
    await screen.findAllByTestId("match-card");
    expect(screen.getAllByTestId("match-card")).toHaveLength(3);

    await user.click(screen.getByLabelText("Country"));
    await user.click(await screen.findByRole("option", { name: "Germany" }));

    await waitFor(() =>
      expect(screen.getAllByTestId("match-card")).toHaveLength(2),
    );
  });

  it("filters matches by position type", async () => {
    mockFetchMatches.mockResolvedValue({ items: MATCHES, total: 3 });
    const user = userEvent.setup();
    render(<DashboardPage />);
    await screen.findAllByTestId("match-card");

    await user.click(screen.getByLabelText("Type"));
    await user.click(await screen.findByRole("option", { name: "postdoc" }));

    await waitFor(() =>
      expect(screen.getAllByTestId("match-card")).toHaveLength(1),
    );
    expect(screen.getByText("Postdoc in cosmology")).toBeInTheDocument();
  });

  it("searches by title text", async () => {
    mockFetchMatches.mockResolvedValue({ items: MATCHES, total: 3 });
    const user = userEvent.setup();
    render(<DashboardPage />);
    await screen.findAllByTestId("match-card");

    await user.type(screen.getByLabelText("Search"), "cosmology");

    await waitFor(() =>
      expect(screen.getAllByTestId("match-card")).toHaveLength(1),
    );
  });

  it("shows an empty state when there are no matches", async () => {
    mockFetchMatches.mockResolvedValue({ items: [], total: 0 });
    render(<DashboardPage />);
    expect(
      await screen.findByText(/No matches yet/),
    ).toBeInTheDocument();
  });

  it("shows an error state when the API is unreachable", async () => {
    mockFetchMatches.mockRejectedValue(
      new ApiError("Cannot reach the API server. Is it running?", 0),
    );
    render(<DashboardPage />);
    expect(
      await screen.findByText("Cannot reach the API server. Is it running?"),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
  });

  it("bookmarks a match", async () => {
    mockFetchMatches.mockResolvedValue({ items: MATCHES, total: 3 });
    mockCreateBookmark.mockResolvedValue({ id: 1, opportunity_id: 1 });
    const user = userEvent.setup();
    render(<DashboardPage />);
    await screen.findAllByTestId("match-card");

    await user.click(
      screen.getAllByRole("button", { name: "Bookmark this match" })[0],
    );

    await waitFor(() => expect(mockCreateBookmark).toHaveBeenCalledWith(1));
    expect(
      await screen.findByText(/Saved "PhD in radio astronomy" to bookmarks/),
    ).toBeInTheDocument();
  });
});
