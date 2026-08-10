import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import BookmarksPage from "@/app/bookmarks/page";
import { ToastProvider } from "@/components/ui/toast";
import { ApiError, deleteBookmark, fetchBookmarks } from "@/lib/api";
import type { Bookmark, Opportunity } from "@/types";

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
  fetchBookmarks: jest.fn(),
  deleteBookmark: jest.fn(),
}));

jest.mock("@/components/AuthGate", () => ({
  __esModule: true,
  default: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

const mockFetchBookmarks = fetchBookmarks as jest.Mock;
const mockDeleteBookmark = deleteBookmark as jest.Mock;

function opp(overrides: Partial<Opportunity>): Opportunity {
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
    ...overrides,
  };
}

const BOOKMARKS: Bookmark[] = [
  {
    id: 11,
    opportunity_id: 1,
    created_at: "2026-07-01T10:00:00Z",
    opportunity: opp({ id: 1, title: "PhD in radio astronomy" }),
  },
  {
    id: 12,
    opportunity_id: 2,
    created_at: "2026-07-20T10:00:00Z",
    opportunity: opp({ id: 2, title: "Postdoc in cosmology" }),
  },
];

describe("BookmarksPage", () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  function renderPage() {
    return render(
      <ToastProvider>
        <BookmarksPage />
      </ToastProvider>,
    );
  }

  it("renders bookmarks sorted by newest first", async () => {
    mockFetchBookmarks.mockResolvedValue({ items: BOOKMARKS, total: 2 });
    renderPage();

    expect(
      await screen.findByText("PhD in radio astronomy"),
    ).toBeInTheDocument();
    expect(screen.getByText("Postdoc in cosmology")).toBeInTheDocument();

    const links = screen
      .getAllByRole("link", { name: /PhD|Postdoc/ })
      .map((el) => el.textContent);
    expect(links).toEqual(["Postdoc in cosmology", "PhD in radio astronomy"]);
  });

  it("deletes a bookmark after confirmation", async () => {
    mockFetchBookmarks.mockResolvedValue({ items: BOOKMARKS, total: 2 });
    mockDeleteBookmark.mockResolvedValue({ status: "ok" });
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("PhD in radio astronomy");

    await user.click(
      screen.getAllByRole("button", { name: /Remove/ })[0],
    );
    const dialog = await screen.findByRole("dialog");
    await user.click(
      within(dialog).getByRole("button", { name: "Remove" }),
    );

    await waitFor(() => expect(mockDeleteBookmark).toHaveBeenCalledWith(12));
    expect(await screen.findByText("Bookmark removed")).toBeInTheDocument();
    expect(screen.queryByText("Postdoc in cosmology")).not.toBeInTheDocument();
  });

  it("shows an empty state when there are no bookmarks", async () => {
    mockFetchBookmarks.mockResolvedValue({ items: [], total: 0 });
    renderPage();
    expect(
      await screen.findByText(/No bookmarks yet/),
    ).toBeInTheDocument();
  });

  it("shows an error state when the API fails", async () => {
    mockFetchBookmarks.mockRejectedValue(
      new ApiError("Unauthorized", 401),
    );
    renderPage();
    expect(await screen.findByText("Unauthorized")).toBeInTheDocument();
  });
});
