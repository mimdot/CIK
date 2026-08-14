import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import OpportunitiesPage from "@/app/(app)/opportunities/page";
import {
  ApiError,
  fetchField,
  fetchFields,
  fetchOpportunities,
  jobStatus,
  triggerPipeline,
} from "@/lib/api";
import type { Opportunity } from "@/types";

jest.mock("@/lib/api", () => {
  class MockApiError extends Error {
    status: number;
    constructor(message: string, status: number) {
      super(message);
      this.status = status;
    }
  }
  return {
    ApiError: MockApiError,
    fetchOpportunities: jest.fn(),
    fetchFields: jest.fn(),
    fetchField: jest.fn(),
    triggerPipeline: jest.fn(),
    jobStatus: jest.fn(),
  };
});

const mockFetchOpportunities = fetchOpportunities as jest.Mock;
const mockFetchFields = fetchFields as jest.Mock;
const mockFetchField = fetchField as jest.Mock;
const mockTriggerPipeline = triggerPipeline as jest.Mock;
const mockJobStatus = jobStatus as jest.Mock;

function opportunity(overrides: Partial<Opportunity>): Opportunity {
  return {
    id: 1,
    source: "euraxess",
    title: "PhD in radio astronomy",
    institution: "MPIfR",
    country: "Germany",
    url: "https://euraxess.ec.europa.eu/jobs/1",
    position_type: "PhD",
    topics: ["interstellar medium"],
    deadline: "2026-10-01T00:00:00",
    is_new: false,
    ...overrides,
  };
}

const OPPORTUNITIES: Opportunity[] = [
  opportunity({ id: 1, title: "PhD in radio astronomy", country: "Germany" }),
  opportunity({ id: 2, title: "Postdoc in cosmology", country: "France" }),
];

describe("OpportunitiesPage", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockFetchOpportunities.mockResolvedValue({
      items: OPPORTUNITIES,
      total: 2,
      pages: 1,
    });
    mockFetchFields.mockResolvedValue({
      default: "astronomy",
      profiles: ["astronomy", "biology"],
      fields: [
        { name: "astronomy", label: "Astronomy", description: "",
          subfields: [{ id: "ism", label: "Interstellar medium",
                        keyword_count: 5 }] },
        { name: "biology", label: "Biology", description: "",
          subfields: [
            { id: "genetics", label: "Genetics", keyword_count: 6 },
            { id: "ecology", label: "Ecology", keyword_count: 4 },
          ] },
      ],
    });
    mockFetchField.mockImplementation(async (name: string) => ({
      name,
      label: name === "biology" ? "Biology" : "Astronomy",
      description: "",
      subfields:
        name === "biology"
          ? [
              { id: "genetics", label: "Genetics", keyword_count: 6,
                keywords: ["genomics", "crispr"] },
              { id: "ecology", label: "Ecology", keyword_count: 4,
                keywords: ["biodiversity"] },
            ]
          : [{ id: "ism", label: "Interstellar medium", keyword_count: 5,
               keywords: ["interstellar medium"] }],
      core_anchors: [],
      search_terms: [],
      sources: { dedicated: [], general: [], has_dedicated: name !== "biology" },
    }));
  });

  it("renders opportunity cards with filters", async () => {
    render(<OpportunitiesPage />);

    expect(
      await screen.findByText("PhD in radio astronomy"),
    ).toBeInTheDocument();
    expect(screen.getByText("Postdoc in cosmology")).toBeInTheDocument();
    expect(screen.getByText("2 open positions.")).toBeInTheDocument();
  });

  it("runs the engine under the selected field profile (H1/2A)", async () => {
    mockTriggerPipeline.mockResolvedValue({ status: "started", run_id: "pf" });
    mockJobStatus.mockResolvedValue({
      run_id: "pf",
      status: "completed",
      records: 7,
    });
    const user = userEvent.setup();
    render(<OpportunitiesPage />);
    await screen.findByText("PhD in radio astronomy");

    await user.click(screen.getByLabelText("Research field"));
    await user.click(await screen.findByRole("option", { name: "Biology" }));
    await user.click(screen.getByRole("button", { name: "Search for positions" }));

    await waitFor(() =>
      expect(mockTriggerPipeline).toHaveBeenCalledWith({
        country: undefined,
        field: "biology",
      }),
    );
  });

  it("scopes the search to the selected subfields (1B)", async () => {
    mockTriggerPipeline.mockResolvedValue({ status: "started", run_id: "sf" });
    mockJobStatus.mockResolvedValue({ run_id: "sf", status: "running" });
    const user = userEvent.setup();
    render(<OpportunitiesPage />);
    await screen.findByText("PhD in radio astronomy");

    await user.click(screen.getByLabelText("Research field"));
    await user.click(await screen.findByRole("option", { name: "Biology" }));

    // Subfields are collapsed by default so the page never gets cluttered.
    expect(screen.queryByLabelText("Genetics")).not.toBeInTheDocument();
    await user.click(await screen.findByRole("button", { name: /Narrow by subfield/ }));
    await user.click(await screen.findByLabelText("Genetics"));

    await user.click(screen.getByRole("button", { name: "Search for positions" }));
    await waitFor(() =>
      expect(mockTriggerPipeline).toHaveBeenCalledWith({
        country: undefined,
        field: "biology",
        subfields: ["genetics"],
      }),
    );
  });

  it("clears subfields when the field changes (stale-scope bleed)", async () => {
    mockTriggerPipeline.mockResolvedValue({ status: "started", run_id: "sc" });
    mockJobStatus.mockResolvedValue({ run_id: "sc", status: "running" });
    const user = userEvent.setup();
    render(<OpportunitiesPage />);
    await screen.findByText("PhD in radio astronomy");

    await user.click(screen.getByLabelText("Research field"));
    await user.click(await screen.findByRole("option", { name: "Biology" }));
    await user.click(await screen.findByRole("button", { name: /Narrow by subfield/ }));
    await user.click(await screen.findByLabelText("Ecology"));

    // Switching field must drop them — a subfield id only means something
    // inside its own field, so carrying it over would silently scope the new
    // search by the old field's vocabulary.
    await user.click(screen.getByLabelText("Research field"));
    await user.click(await screen.findByRole("option", { name: "Astronomy" }));

    await user.click(screen.getByRole("button", { name: "Search for positions" }));
    await waitFor(() =>
      expect(mockTriggerPipeline).toHaveBeenCalledWith({
        country: undefined,
        field: "astronomy",
      }),
    );
  });

  it("says so when a field has no dedicated job board yet", async () => {
    const user = userEvent.setup();
    render(<OpportunitiesPage />);
    await screen.findByText("PhD in radio astronomy");

    await user.click(screen.getByLabelText("Research field"));
    await user.click(await screen.findByRole("option", { name: "Biology" }));

    expect(
      await screen.findByText(/No board is dedicated to Biology yet/),
    ).toBeInTheDocument();
  });

  it("lists only the selected field's stored rows", async () => {
    const user = userEvent.setup();
    render(<OpportunitiesPage />);
    await screen.findByText("PhD in radio astronomy");

    await user.click(screen.getByLabelText("Research field"));
    await user.click(await screen.findByRole("option", { name: "Biology" }));

    // The list request carries the field, so astronomy rows stored by an
    // earlier run cannot appear under biology.
    await waitFor(() =>
      expect(mockFetchOpportunities).toHaveBeenCalledWith(
        expect.objectContaining({ field: "biology" }),
      ),
    );
  });

  it("streams per-source progress in the run dialog (M3)", async () => {
    mockTriggerPipeline.mockResolvedValue({ status: "started", run_id: "pp" });
    mockJobStatus.mockResolvedValue({
      run_id: "pp",
      status: "running",
      progress: {
        total: 3,
        completed: 2,
        sources: [
          { source: "eso", status: "done", records: 5 },
          { source: "aas", status: "error", records: 0 },
        ],
      },
    });
    const user = userEvent.setup();
    render(<OpportunitiesPage />);
    await screen.findByText("PhD in radio astronomy");
    await user.click(screen.getByRole("button", { name: "Search for positions" }));

    expect(await screen.findByTestId("run-progress-count")).toHaveTextContent(
      "2 / 3",
    );
    expect(screen.getByText("eso")).toBeInTheDocument();
    expect(screen.getByText("aas")).toBeInTheDocument();
  });

  it("explains the headline number with the run funnel (18-vs-63)", async () => {
    mockTriggerPipeline.mockResolvedValue({ status: "started", run_id: "pf" });
    mockJobStatus.mockResolvedValue({
      run_id: "pf",
      status: "completed",
      records: 18,
      progress: {
        total: 1,
        completed: 1,
        sources: [{ source: "euraxess", status: "done", records: 63 }],
        funnel: {
          field: "astronomy",
          found: 63,
          after_field_filter: 41,
          after_freshness: 41,
          after_dedupe: 22,
          stored: 18,
          dropped: {
            position_type: 0,
            off_field: 22,
            expired: 4,
            country: 0,
            stale: 0,
            duplicate: 19,
          },
        },
      },
    });
    const user = userEvent.setup();
    render(<OpportunitiesPage />);
    await screen.findByText("PhD in radio astronomy");
    await user.click(screen.getByRole("button", { name: "Search for positions" }));

    // Every stage of the shrink is visible, not just the endpoints, so the
    // user can see 63 become 18 step by step.
    const funnel = await screen.findByTestId("run-funnel");
    const chain = funnel.textContent?.replace(/\s+/g, " ") ?? "";
    expect(chain).toContain("63 found");
    expect(chain).toContain("41 after field filter");
    expect(chain).toContain("22 after dedupe");
    expect(chain).toContain("18 stored");
    // ...and the reasons it shrank.
    expect(within(funnel).getByText(/22 off-field/)).toBeInTheDocument();
    expect(within(funnel).getByText(/19 duplicate/)).toBeInTheDocument();
  });

  it("warns when results were found but could not be saved", async () => {
    mockTriggerPipeline.mockResolvedValue({ status: "started", run_id: "pe" });
    mockJobStatus.mockResolvedValue({
      run_id: "pe",
      status: "completed",
      records: 63,
      progress: {
        total: 1,
        completed: 1,
        sources: [],
        funnel: {
          found: 63,
          after_field_filter: 63,
          after_freshness: 63,
          after_dedupe: 63,
          storage_error: "database is locked",
          dropped: {
            position_type: 0, off_field: 0, expired: 0,
            country: 0, stale: 0, duplicate: 0,
          },
        },
      },
    });
    const user = userEvent.setup();
    render(<OpportunitiesPage />);
    await screen.findByText("PhD in radio astronomy");
    await user.click(screen.getByRole("button", { name: "Search for positions" }));

    // A silently swallowed seeding failure is exactly how the UI count and the
    // engine count drift apart. It must be said out loud.
    expect(
      await screen.findByText(/could not be saved \(database is locked\)/),
    ).toBeInTheDocument();
  });

  it("runs the engine scoped to the active country filter", async () => {
    mockTriggerPipeline.mockResolvedValue({ status: "started", run_id: "p1" });
    mockJobStatus.mockResolvedValue({
      run_id: "p1",
      status: "completed",
      records: 42,
    });
    const user = userEvent.setup();
    render(<OpportunitiesPage />);
    await screen.findByText("PhD in radio astronomy");

    await user.click(screen.getByLabelText("Country"));
    await user.click(await screen.findByRole("option", { name: "Germany" }));
    await user.click(screen.getByRole("button", { name: "Search for positions" }));

    await waitFor(() =>
      expect(mockTriggerPipeline).toHaveBeenCalledWith({
        country: "Germany",
      }),
    );

    expect(await screen.findByText("Run completed.")).toBeInTheDocument();
    expect(screen.getByTestId("run-status")).toHaveTextContent("completed");
    expect(screen.getByTestId("run-records")).toHaveTextContent("42");

    // The completion notice no longer quotes a second, differently-derived
    // count. Quoting the engine's "42 records" next to the page's "N open
    // positions" is what produced the 18-vs-63 confusion; the per-stage
    // breakdown explains the number instead (see RunFunnelSummary).
    expect(await screen.findByText(/Search finished/)).toBeInTheDocument();
    expect(screen.queryByText(/Engine run finished/)).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Done" }));
    await waitFor(() =>
      expect(screen.queryByText("Run completed.")).not.toBeInTheDocument(),
    );
  });

  it("runs the engine worldwide when no country filter is set", async () => {
    mockTriggerPipeline.mockResolvedValue({ status: "started", run_id: "p2" });
    mockJobStatus.mockResolvedValue({ run_id: "p2", status: "running" });
    const user = userEvent.setup();
    render(<OpportunitiesPage />);
    await screen.findByText("PhD in radio astronomy");

    await user.click(screen.getByRole("button", { name: "Search for positions" }));

    await waitFor(() =>
      expect(mockTriggerPipeline).toHaveBeenCalledWith({ country: undefined }),
    );
    expect(await screen.findByText("Aggregating opportunities from sources…")).toBeInTheDocument();
  });

  it("shows an error when the engine run fails to start", async () => {
    mockTriggerPipeline.mockRejectedValue(new ApiError("Rate limited", 429));
    const user = userEvent.setup();
    render(<OpportunitiesPage />);
    await screen.findByText("PhD in radio astronomy");

    await user.click(screen.getByRole("button", { name: "Search for positions" }));

    expect(await screen.findByText("Rate limited")).toBeInTheDocument();
    expect(screen.getByTestId("run-status")).toHaveTextContent("failed");
  });

  it("shows an empty state that offers to run the engine", async () => {
    mockFetchOpportunities.mockResolvedValue({ items: [], total: 0, pages: 0 });
    render(<OpportunitiesPage />);

    expect(await screen.findByText("No opportunities yet.")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /Run the engine to discover positions/ }),
    ).toBeInTheDocument();
  });

  it("shows an error state when the list fails to load", async () => {
    mockFetchOpportunities.mockRejectedValue(new ApiError("Bad gateway", 502));
    render(<OpportunitiesPage />);
    expect(await screen.findByText("Bad gateway")).toBeInTheDocument();
  });
});
