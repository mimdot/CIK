import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import SupervisorsPage from "@/app/(app)/supervisors/page";
import {
  ApiError,
  fetchSupervisors,
  fetchFields,
  jobStatus,
  triggerSupervisorSearch,
} from "@/lib/api";
import type { Supervisor } from "@/types";
// shared auth mock loaded via jest.requireActual inside the factory

jest.mock("@/lib/api", () => {
  const { mockAuthApi } = jest.requireActual("../test-utils/mock-auth");
  return mockAuthApi({
    login: jest.fn(),
    register: jest.fn(),
    fetchSupervisors: jest.fn(),
    fetchFields: jest.fn(),
    triggerSupervisorSearch: jest.fn(),
    jobStatus: jest.fn(),
  });
});

const mockFetchSupervisors = fetchSupervisors as jest.Mock;
const mockFetchFields = fetchFields as jest.Mock;
const mockTriggerSupervisorSearch = triggerSupervisorSearch as jest.Mock;
const mockJobStatus = jobStatus as jest.Mock;

function supervisor(overrides: Partial<Supervisor>): Supervisor {
  return {
    id: 1,
    source: "ads",
    name: "Dr. Lena Kraft",
    institution: "MPIfR",
    department: "Radio Astronomy",
    country: "Germany",
    profile_url: "https://example.org/lena",
    email: "lena@mpifr.de",
    orcid: "0000-0001-2345-6789",
    topics: ["interstellar medium", "magnetic fields", "polarization"],
    methods: ["radio interferometry"],
    recent_papers: ["Faraday rotation in the ISM", "Polarization survey"],
    fit_score: 85,
    confidence: 0.9,
    ...overrides,
  };
}

const SUPERVISORS: Supervisor[] = [
  supervisor({
    id: 1,
    name: "Dr. Lena Kraft",
    institution: "MPIfR",
    country: "Germany",
    topics: ["interstellar medium", "magnetic fields"],
    fit_score: 85,
  }),
  supervisor({
    id: 2,
    name: "Prof. Omar Haddad",
    institution: "Leiden Observatory",
    country: "Netherlands",
    topics: ["galaxy formation", "cosmology"],
    fit_score: 60,
    orcid: null,
    profile_url: null,
  }),
];

describe("SupervisorsPage", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockFetchFields.mockResolvedValue({ default: "astronomy", profiles: ["astronomy", "biology", "physics"] });
  });

  it("renders supervisor cards with fit scores", async () => {
    mockFetchSupervisors.mockResolvedValue({ items: SUPERVISORS, total: 2 });
    render(<SupervisorsPage />);

    expect(await screen.findByText("Dr. Lena Kraft")).toBeInTheDocument();
    expect(screen.getByText("Prof. Omar Haddad")).toBeInTheDocument();
    const scores = screen
      .getAllByTestId("fit-score")
      .map((el) => el.textContent);
    expect(scores).toEqual(["Fit 85 / 100", "Fit 60 / 100"]);
  });

  it("sorts by fit ascending", async () => {
    mockFetchSupervisors.mockResolvedValue({ items: SUPERVISORS, total: 2 });
    const user = userEvent.setup();
    render(<SupervisorsPage />);
    await screen.findByText("Dr. Lena Kraft");

    await user.click(screen.getByLabelText("Sort"));
    await user.click(await screen.findByRole("option", { name: /low → high/ }));

    await waitFor(() => {
      const scores = screen
        .getAllByTestId("fit-score")
        .map((el) => el.textContent);
      expect(scores).toEqual(["Fit 60 / 100", "Fit 85 / 100"]);
    });
  });

  it("searches by topic text", async () => {
    mockFetchSupervisors.mockResolvedValue({ items: SUPERVISORS, total: 2 });
    const user = userEvent.setup();
    render(<SupervisorsPage />);
    await screen.findByText("Dr. Lena Kraft");

    await user.type(screen.getByLabelText("Search"), "galaxy formation");

    await waitFor(() => {
      expect(screen.queryByText("Dr. Lena Kraft")).not.toBeInTheDocument();
      expect(screen.getByText("Prof. Omar Haddad")).toBeInTheDocument();
    });
  });

  it("expands a card to show methods and recent papers", async () => {
    mockFetchSupervisors.mockResolvedValue({ items: SUPERVISORS, total: 2 });
    const user = userEvent.setup();
    render(<SupervisorsPage />);
    await screen.findByText("Dr. Lena Kraft");

    await user.click(screen.getAllByRole("button", { name: "Show details" })[0]);

    expect(screen.getByText(/radio interferometry/)).toBeInTheDocument();
    expect(screen.getByText("Faraday rotation in the ISM")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /ORCID/ })).toHaveAttribute(
      "href",
      "https://orcid.org/0000-0001-2345-6789",
    );
  });

  it("shows an empty state when no supervisors match", async () => {
    mockFetchSupervisors.mockResolvedValue({ items: [], total: 0 });
    render(<SupervisorsPage />);
    expect(
      await screen.findByText(/No supervisors found/),
    ).toBeInTheDocument();
  });

  it("shows an error state when the API fails", async () => {
    mockFetchSupervisors.mockRejectedValue(
      new ApiError("Bad gateway", 502),
    );
    render(<SupervisorsPage />);
    expect(await screen.findByText("Bad gateway")).toBeInTheDocument();
  });

  it("keeps the online search start button disabled until a country is entered", async () => {
    mockFetchSupervisors.mockResolvedValue({ items: SUPERVISORS, total: 2 });
    const user = userEvent.setup();
    render(<SupervisorsPage />);
    await screen.findByText("Dr. Lena Kraft");

    await user.click(screen.getByRole("button", { name: "Run online search" }));
    const dialog = await screen.findByRole("dialog");

    const startButton = within(dialog).getByRole("button", {
      name: "Start search",
    });
    expect(startButton).toBeDisabled();

    await user.type(within(dialog).getByLabelText("Country"), "Germany");
    expect(startButton).toBeEnabled();
  });

  it("runs an online search and shows completion", async () => {
    mockFetchSupervisors.mockResolvedValue({ items: SUPERVISORS, total: 2 });
    mockTriggerSupervisorSearch.mockResolvedValue({
      status: "started",
      run_id: "run-1",
    });
    mockJobStatus.mockResolvedValue({
      run_id: "run-1",
      status: "completed",
      records: 2,
    });
    const user = userEvent.setup();
    render(<SupervisorsPage />);
    await screen.findByText("Dr. Lena Kraft");

    await user.click(screen.getByRole("button", { name: "Run online search" }));
    const formDialog = await screen.findByRole("dialog");
    await user.type(within(formDialog).getByLabelText("Country"), "Germany");
    await user.click(
      within(formDialog).getByRole("button", { name: "Start search" }),
    );

    await waitFor(() =>
      expect(mockTriggerSupervisorSearch).toHaveBeenCalledWith(
        expect.objectContaining({ country: "Germany" }),
      ),
    );

    expect(await screen.findByText("Search completed.")).toBeInTheDocument();
    expect(screen.getByTestId("run-status")).toHaveTextContent("completed");
    expect(screen.getByTestId("run-records")).toHaveTextContent("2");
    expect(mockJobStatus).toHaveBeenCalledWith("run-1");

    await user.click(screen.getByRole("button", { name: "Done" }));
    await waitFor(() =>
      expect(screen.queryByText("Search completed.")).not.toBeInTheDocument(),
    );
  });

  it("shows an error when the online search fails to start", async () => {
    mockFetchSupervisors.mockResolvedValue({ items: SUPERVISORS, total: 2 });
    mockTriggerSupervisorSearch.mockRejectedValue(
      new ApiError("Rate limited", 429),
    );
    const user = userEvent.setup();
    render(<SupervisorsPage />);
    await screen.findByText("Dr. Lena Kraft");

    await user.click(screen.getByRole("button", { name: "Run online search" }));
    const formDialog = await screen.findByRole("dialog");
    await user.type(within(formDialog).getByLabelText("Country"), "Germany");
    await user.click(
      within(formDialog).getByRole("button", { name: "Start search" }),
    );

    expect(await screen.findByText("Rate limited")).toBeInTheDocument();
    expect(screen.getByTestId("run-status")).toHaveTextContent("failed");
  });

  it("exports the shown supervisors to CSV (2C)", async () => {
    mockFetchSupervisors.mockResolvedValue({ items: SUPERVISORS, total: 2 });
    // Capture the CSV string handed to the Blob (jsdom has no Blob.text()).
    let csv = "";
    const RealBlob = global.Blob;
    const blobSpy = jest
      .spyOn(global, "Blob")
      .mockImplementation((parts?: BlobPart[], opts?: BlobPropertyBag) => {
        csv = (parts ?? []).join("");
        return new RealBlob(parts, opts);
      });
    const createObjectURL = jest.fn(() => "blob:mock");
    Object.assign(URL, { createObjectURL, revokeObjectURL: jest.fn() });
    const clickSpy = jest
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(() => {});
    const user = userEvent.setup();
    render(<SupervisorsPage />);
    await screen.findByText("Dr. Lena Kraft");

    await user.click(screen.getByRole("button", { name: "Export CSV" }));

    expect(createObjectURL).toHaveBeenCalledTimes(1);
    expect(clickSpy).toHaveBeenCalledTimes(1);
    expect(csv.split("\n")[0]).toContain("name,institution");
    expect(csv).toContain("Dr. Lena Kraft");
    expect(csv).toContain("Prof. Omar Haddad");
    blobSpy.mockRestore();
    clickSpy.mockRestore();
  });

  it("runs an online search across several comma-separated countries (2C)", async () => {
    mockFetchSupervisors.mockResolvedValue({ items: SUPERVISORS, total: 2 });
    mockTriggerSupervisorSearch.mockResolvedValue({
      status: "started",
      run_id: "run-2",
    });
    mockJobStatus.mockResolvedValue({
      run_id: "run-2",
      status: "completed",
      records: 3,
    });
    const user = userEvent.setup();
    render(<SupervisorsPage />);
    await screen.findByText("Dr. Lena Kraft");

    await user.click(screen.getByRole("button", { name: "Run online search" }));
    const formDialog = await screen.findByRole("dialog");
    await user.type(
      within(formDialog).getByLabelText("Country"),
      "Germany, Netherlands",
    );
    await user.click(
      within(formDialog).getByRole("button", { name: "Start search" }),
    );

    await waitFor(() =>
      expect(mockTriggerSupervisorSearch).toHaveBeenCalledWith(
        expect.objectContaining({ country: ["Germany", "Netherlands"] }),
      ),
    );
  });
});

describe("SupervisorsPage — explainable fit + export parity (Phase 4)", () => {
  const EXPLAINED = supervisor({
    id: 3,
    name: "Dr. Explained",
    fit_score: 72,
    fit_explanation:
      "29 pts — matches your terms: interstellar medium; 19 pts — 9 recent " +
      "papers in the window; 20 pts — senior author on 5 of 9; 15 pts — " +
      "confirmed in Germany",
  });

  beforeEach(() => {
    jest.clearAllMocks();
    mockFetchFields.mockResolvedValue({
      default: "astronomy",
      profiles: ["astronomy"],
    });
  });

  it("never shows a bare number — expanding reveals the reasoning", async () => {
    mockFetchSupervisors.mockResolvedValue({ items: [EXPLAINED], total: 1 });
    const user = userEvent.setup();
    render(<SupervisorsPage />);
    await screen.findByText("Dr. Explained");

    // The badge is on the 0-100 scale (it used to multiply by 100 and print
    // an unbounded raw score as a percentage — "Fit 4300%").
    expect(screen.getByTestId("fit-score")).toHaveTextContent("Fit 72 / 100");
    expect(screen.queryByTestId("fit-explanation")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Show details" }));
    expect(screen.getByTestId("fit-explanation")).toHaveTextContent(
      /matches your terms: interstellar medium/,
    );
    expect(screen.getByTestId("fit-explanation")).toHaveTextContent(
      /senior author on 5 of 9/,
    );
  });

  it("exports exactly the rows on screen, reasoning included (4B)", async () => {
    mockFetchSupervisors.mockResolvedValue({
      items: [...SUPERVISORS, EXPLAINED],
      total: 3,
    });
    let csv = "";
    const RealBlob = global.Blob;
    jest
      .spyOn(global, "Blob")
      .mockImplementation((parts?: BlobPart[], opts?: BlobPropertyBag) => {
        csv = (parts ?? []).join("");
        return new RealBlob(parts, opts);
      });
    const createObjectURL = jest.fn(() => "blob:mock");
    Object.assign(URL, { createObjectURL, revokeObjectURL: jest.fn() });
    jest
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(() => {});

    const user = userEvent.setup();
    render(<SupervisorsPage />);
    await screen.findByText("Dr. Lena Kraft");

    // Narrow the view, then export: the file must contain the FILTERED set,
    // not everything the API returned. The export path shares the same
    // `filtered` array the cards render from, so the two cannot diverge.
    await user.type(screen.getByLabelText("Search"), "Explained");
    await waitFor(() =>
      expect(screen.queryByText("Dr. Lena Kraft")).not.toBeInTheDocument(),
    );
    await user.click(screen.getByRole("button", { name: /Export CSV/ }));

    expect(csv).toContain("Dr. Explained");
    expect(csv).not.toContain("Dr. Lena Kraft");
    expect(csv).not.toContain("Prof. Omar Haddad");
    expect(csv).toContain("fit_explanation");
    expect(csv).toContain("senior author on 5 of 9");
    jest.restoreAllMocks();
  });
});
