import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import SavedPage from "@/app/(app)/bookmarks/page";
import { ToastProvider } from "@/components/ui/toast";
import { deleteSaved, fetchSaved, updateSaved } from "@/lib/api";
import type { SavedItem } from "@/types";

jest.mock("@/lib/api", () => {
  const { mockAuthApi } = jest.requireActual("../test-utils/mock-auth");
  return mockAuthApi({
    fetchSaved: jest.fn(),
    updateSaved: jest.fn(),
    deleteSaved: jest.fn(),
  });
});

const mockFetchSaved = fetchSaved as jest.Mock;
const mockUpdate = updateSaved as jest.Mock;
const mockDelete = deleteSaved as jest.Mock;

function saved(over: Partial<SavedItem> = {}): SavedItem {
  return {
    id: 1,
    kind: "opportunity",
    stable_key: "url:example.org/p/1",
    record: {
      title: "PhD in radio astronomy",
      institution: "MPIfR",
      country: "Germany",
      url: "https://example.org/p/1",
    },
    note: null,
    status: "interested",
    still_listed: true,
    record_id: 11,
    created_at: "2026-08-16T10:00:00",
    ...over,
  };
}

function sup(over: Partial<SavedItem> = {}): SavedItem {
  return saved({
    id: 2,
    kind: "supervisor",
    stable_key: "orcid:0000-0002-1825-0097",
    record: { name: "Ada Lovelace", institution: "MPIfR", country: "Germany" },
    ...over,
  });
}

function byKind(opps: SavedItem[], sups: SavedItem[]) {
  mockFetchSaved.mockImplementation((kind: string) =>
    Promise.resolve(
      kind === "opportunity"
        ? { items: opps, total: opps.length }
        : { items: sups, total: sups.length },
    ),
  );
}

function renderPage() {
  return render(
    <ToastProvider>
      <SavedPage />
    </ToastProvider>,
  );
}

beforeEach(() => {
  jest.clearAllMocks();
  mockDelete.mockResolvedValue({ status: "deleted" });
});

describe("Saved view", () => {
  it("separates the two kinds and shows a real count on each tab", async () => {
    byKind([saved(), saved({ id: 3 })], [sup()]);
    renderPage();

    // Counts are right from the first paint, without visiting the tab.
    expect(
      await screen.findByRole("tab", { name: /Opportunities \(2\)/ }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("tab", { name: /Supervisors \(1\)/ }),
    ).toBeInTheDocument();
  });

  it("switches between the tabs", async () => {
    byKind([saved()], [sup()]);
    const user = userEvent.setup();
    renderPage();

    expect(await screen.findByText("PhD in radio astronomy")).toBeInTheDocument();
    await user.click(screen.getByRole("tab", { name: /Supervisors/ }));

    expect(await screen.findByText("Ada Lovelace")).toBeInTheDocument();
    expect(screen.queryByText("PhD in radio astronomy")).not.toBeInTheDocument();
  });

  it("marks an entry that is no longer listed, and still shows it", async () => {
    byKind([saved({ still_listed: false, record_id: null })], []);
    renderPage();

    expect(await screen.findByTestId("delisted")).toHaveTextContent(
      "No longer listed",
    );
    // The snapshot is what makes this possible: the posting is gone, the entry
    // is not.
    expect(screen.getByText("PhD in radio astronomy")).toBeInTheDocument();
  });

  it("searches within the current tab", async () => {
    byKind([saved(), saved({ id: 3, record: { title: "Postdoc in cosmology" } })], []);
    const user = userEvent.setup();
    renderPage();
    await screen.findAllByTestId("saved-card");

    await user.type(screen.getByLabelText("Search"), "cosmology");

    await waitFor(() =>
      expect(screen.getAllByTestId("saved-card")).toHaveLength(1),
    );
    expect(screen.getByText("Postdoc in cosmology")).toBeInTheDocument();
  });

  it("removes an entry", async () => {
    byKind([saved()], []);
    const user = userEvent.setup();
    renderPage();
    await screen.findByTestId("saved-card");

    await user.click(
      screen.getByRole("button", {
        name: "Remove PhD in radio astronomy from saved",
      }),
    );

    await waitFor(() => expect(mockDelete).toHaveBeenCalledWith(1));
    await waitFor(() =>
      expect(screen.queryByTestId("saved-card")).not.toBeInTheDocument(),
    );
  });

  it("records an application status", async () => {
    byKind([saved()], []);
    mockUpdate.mockResolvedValue(saved({ status: "applied" }));
    const user = userEvent.setup();
    renderPage();
    await screen.findByTestId("saved-card");

    await user.click(
      screen.getByRole("combobox", { name: /Status for PhD in radio astronomy/ }),
    );
    await user.click(await screen.findByRole("option", { name: "Applied" }));

    await waitFor(() =>
      expect(mockUpdate).toHaveBeenCalledWith(1, { status: "applied" }),
    );
  });

  it("keeps a personal note", async () => {
    byKind([saved()], []);
    mockUpdate.mockResolvedValue(saved({ note: "email the PI" }));
    const user = userEvent.setup();
    renderPage();
    await screen.findByTestId("saved-card");

    await user.click(screen.getByRole("button", { name: "Add a note" }));
    await user.type(screen.getByLabelText("Note"), "email the PI");
    await user.click(screen.getByRole("button", { name: "Save note" }));

    await waitFor(() =>
      expect(mockUpdate).toHaveBeenCalledWith(1, { note: "email the PI" }),
    );
  });

  it("says what to do when nothing is saved yet", async () => {
    byKind([], []);
    renderPage();
    expect(
      await screen.findByText(/press the star on any card/),
    ).toBeInTheDocument();
  });

  it("reports a failure to load", async () => {
    const { ApiError } = jest.requireMock("@/lib/api") as {
      ApiError: new (m: string, s: number) => Error;
    };
    mockFetchSaved.mockRejectedValue(new ApiError("Cannot reach the API", 0));
    renderPage();
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Cannot reach the API",
    );
  });

  it("offers an export per section", async () => {
    byKind([saved()], []);
    renderPage();
    const csv = await screen.findByRole("button", { name: "Export CSV" });
    expect(csv).toBeEnabled();
    expect(within(document.body).getByRole("button", { name: "Export JSON" }))
      .toBeEnabled();
  });
});
