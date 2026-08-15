import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import OpportunitiesPage from "@/app/(app)/opportunities/page";
import {
  ApiError,
  cancelJob,
  fetchField,
  fetchFieldDepartments,
  fetchPositionTypes,
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
    cancelJob: jest.fn(),
    fetchFieldDepartments: jest.fn(),
    fetchPositionTypes: jest.fn(),
  };
});

const mockFetchOpportunities = fetchOpportunities as jest.Mock;
const mockFetchFields = fetchFields as jest.Mock;
const mockFetchField = fetchField as jest.Mock;
const mockTriggerPipeline = triggerPipeline as jest.Mock;
const mockJobStatus = jobStatus as jest.Mock;
const mockCancelJob = cancelJob as jest.Mock;
const mockFetchFieldDepartments = fetchFieldDepartments as jest.Mock;
const mockFetchPositionTypes = fetchPositionTypes as jest.Mock;

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
    mockFetchFieldDepartments.mockResolvedValue({
      field: "astronomy", total: 0, countries: [], departments: [],
    });
    mockFetchPositionTypes.mockResolvedValue({
      types: [
        { name: "phd", label: "PhD", description: "Doctoral positions.",
          enabled: true },
        { name: "postdoc", label: "Postdoc", description: "Postdoc roles.",
          enabled: true },
        { name: "masters", label: "Master's", description: "Master's.",
          enabled: false },
        { name: "scholarship", label: "Scholarship", description: "Funding.",
          enabled: false },
      ],
      default: ["phd", "postdoc"],
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
    expect(screen.getByText("2 open PhD positions.")).toBeInTheDocument();
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
        position_types: ["phd"],
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
        position_types: ["phd"],
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
        position_types: ["phd"],
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

  it("leaves the slow department sweep OFF by default, with its cost stated (2B)", async () => {
    mockTriggerPipeline.mockResolvedValue({ status: "started", run_id: "s1" });
    mockJobStatus.mockResolvedValue({ run_id: "s1", status: "running" });
    const user = userEvent.setup();
    render(<OpportunitiesPage />);
    await screen.findByText("PhD in radio astronomy");

    const box = screen.getByLabelText("Also sweep university department pages");
    expect(box).not.toBeChecked();
    // The time price must be visible before the user opts in, not after.
    expect(screen.getByText(/several minutes/)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Search for positions" }));
    await waitFor(() =>
      expect(mockTriggerPipeline).toHaveBeenCalledWith(
        expect.not.objectContaining({ include_slow: true }),
      ),
    );
  });

  it("opts in to the department sweep when asked (2B)", async () => {
    mockTriggerPipeline.mockResolvedValue({ status: "started", run_id: "s2" });
    mockJobStatus.mockResolvedValue({ run_id: "s2", status: "running" });
    const user = userEvent.setup();
    render(<OpportunitiesPage />);
    await screen.findByText("PhD in radio astronomy");

    await user.click(
      screen.getByLabelText("Also sweep university department pages"),
    );
    await user.click(screen.getByRole("button", { name: "Search for positions" }));
    await waitFor(() =>
      expect(mockTriggerPipeline).toHaveBeenCalledWith(
        expect.objectContaining({ include_slow: true }),
      ),
    );
  });

  it("offers browsing the departments manually instead (2B)", async () => {
    mockFetchFieldDepartments.mockResolvedValue({
      field: "astronomy",
      total: 2,
      countries: ["Germany", "United Kingdom"],
      departments: [
        { country: "Germany", institution: "MPIfR Bonn",
          url: "https://mpifr-bonn.mpg.de/joboffers", field_specific: true },
        { country: "United Kingdom", institution: "Institute of Astronomy",
          url: "https://ast.cam.ac.uk/", field_specific: true },
      ],
    });
    const user = userEvent.setup();
    render(<OpportunitiesPage />);
    await screen.findByText("PhD in radio astronomy");

    await user.click(screen.getByLabelText("Research field"));
    await user.click(await screen.findByRole("option", { name: "Astronomy" }));
    await user.click(
      screen.getByRole("button", { name: /browse the department list yourself/i }),
    );

    // The list is handed over directly — no crawl, nothing to wait for.
    const link = await screen.findByRole("link", { name: "MPIfR Bonn" });
    expect(link).toHaveAttribute("href", "https://mpifr-bonn.mpg.de/joboffers");
    expect(screen.getByText(/2 departments/)).toBeInTheDocument();
  });

  it("cancels a running search and keeps the partial results (2A)", async () => {
    mockTriggerPipeline.mockResolvedValue({ status: "started", run_id: "cx" });
    // running -> (cancel pressed) -> cancelled, with partial results.
    mockJobStatus
      .mockResolvedValueOnce({
        run_id: "cx",
        status: "running",
        progress: {
          total: 3,
          completed: 1,
          sources: [{ source: "eso", status: "done", records: 4 }],
        },
      })
      .mockResolvedValue({
        run_id: "cx",
        status: "cancelled",
        records: 4,
        progress: {
          total: 3,
          completed: 3,
          sources: [
            { source: "eso", status: "done", records: 4 },
            { source: "aas", status: "skipped", records: 0 },
            { source: "euraxess", status: "skipped", records: 0 },
          ],
          funnel: {
            cancelled: true,
            found: 4,
            after_field_filter: 4,
            after_freshness: 4,
            after_dedupe: 4,
            stored: 4,
            dropped: {
              position_type: 0, off_field: 0, expired: 0,
              country: 0, stale: 0, duplicate: 0,
            },
          },
        },
      });
    mockCancelJob.mockResolvedValue({ status: "cancelling" });

    const user = userEvent.setup();
    render(<OpportunitiesPage />);
    await screen.findByText("PhD in radio astronomy");
    await user.click(screen.getByRole("button", { name: "Search for positions" }));

    await user.click(await screen.findByRole("button", { name: "Cancel search" }));
    expect(mockCancelJob).toHaveBeenCalledWith("cx");

    // The app must NOT close, crash or need a restart — it lands in a usable
    // idle state with the partial results kept. Waits past one poll interval
    // (POLL_MS = 2s), which is when the run reports back.
    expect(
      await screen.findByText(/Search stopped/, {}, { timeout: 4000 }),
    ).toBeInTheDocument();
    expect(screen.getByTestId("run-status")).toHaveTextContent("cancelled");
    expect(screen.getAllByText("skipped").length).toBe(2);

    await user.click(screen.getByRole("button", { name: "Done" }));
    await waitFor(() =>
      expect(screen.queryByText(/Search stopped/)).not.toBeInTheDocument(),
    );
    // ...and the list reloaded, so what was found is on screen.
    expect(screen.getByText("PhD in radio astronomy")).toBeInTheDocument();
  });

  it("shows elapsed time so a search never looks frozen (6A)", async () => {
    mockTriggerPipeline.mockResolvedValue({ status: "started", run_id: "el" });
    mockJobStatus.mockResolvedValue({ run_id: "el", status: "running" });
    const user = userEvent.setup();
    render(<OpportunitiesPage />);
    await screen.findByText("PhD in radio astronomy");
    await user.click(screen.getByRole("button", { name: "Search for positions" }));

    expect(await screen.findByTestId("run-elapsed")).toBeInTheDocument();
  });

  it("does not surface a 409 when the run finished before Cancel landed", async () => {
    mockTriggerPipeline.mockResolvedValue({ status: "started", run_id: "rc" });
    mockJobStatus.mockResolvedValue({ run_id: "rc", status: "running" });
    mockCancelJob.mockRejectedValue(
      new ApiError("Job has already finished", 409),
    );
    const user = userEvent.setup();
    render(<OpportunitiesPage />);
    await screen.findByText("PhD in radio astronomy");
    await user.click(screen.getByRole("button", { name: "Search for positions" }));
    await user.click(await screen.findByRole("button", { name: "Cancel search" }));

    await waitFor(() => expect(mockCancelJob).toHaveBeenCalled());
    expect(
      screen.queryByText(/Job has already finished/),
    ).not.toBeInTheDocument();
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

  it("tells the user where a failed save rescued the results to", async () => {
    mockTriggerPipeline.mockResolvedValue({ status: "started", run_id: "pr" });
    mockJobStatus.mockResolvedValue({
      run_id: "pr",
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
          storage_error: "RuntimeError: database is locked",
          storage_rescue_path: "/home/me/phd_positions.rescue-20260815T101500Z.json",
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

    // Losing a completed crawl is the worst failure there is. If the database
    // refused it, the user must be told the exact file it survived in.
    expect(await screen.findByTestId("run-rescue-path")).toHaveTextContent(
      "/home/me/phd_positions.rescue-20260815T101500Z.json",
    );
  });

  it("names the profile terms a run actually used", async () => {
    mockTriggerPipeline.mockResolvedValue({ status: "started", run_id: "pt" });
    mockJobStatus.mockResolvedValue({
      run_id: "pt",
      status: "completed",
      records: 5,
      progress: {
        total: 1, completed: 1, sources: [],
        funnel: {
          found: 5, after_field_filter: 5, after_freshness: 5, after_dedupe: 5,
          profile_active: true,
          profile_terms: ["interstellar medium", "radio interferometry", "LOFAR"],
          dropped: { position_type: 0, off_field: 0, expired: 0,
                     country: 0, stale: 0, duplicate: 0 },
        },
      },
    });
    const user = userEvent.setup();
    render(<OpportunitiesPage />);
    await screen.findByText("PhD in radio astronomy");
    await user.click(screen.getByRole("button", { name: "Search for positions" }));

    // "Did my research profile do anything?" must be answerable by looking.
    expect(await screen.findByTestId("run-profile-terms")).toHaveTextContent(
      "interstellar medium, radio interferometry, LOFAR",
    );
  });

  it("says so when no research profile was used", async () => {
    mockTriggerPipeline.mockResolvedValue({ status: "started", run_id: "pn" });
    mockJobStatus.mockResolvedValue({
      run_id: "pn",
      status: "completed",
      records: 5,
      progress: {
        total: 1, completed: 1, sources: [],
        funnel: {
          found: 5, after_field_filter: 5, after_freshness: 5, after_dedupe: 5,
          profile_active: false, profile_terms: [],
          dropped: { position_type: 0, off_field: 0, expired: 0,
                     country: 0, stale: 0, duplicate: 0 },
        },
      },
    });
    const user = userEvent.setup();
    render(<OpportunitiesPage />);
    await screen.findByText("PhD in radio astronomy");
    await user.click(screen.getByRole("button", { name: "Search for positions" }));

    expect(await screen.findByTestId("run-profile-terms")).toHaveTextContent(
      /No research profile was used/,
    );
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
        position_types: ["phd"],
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
      expect(mockTriggerPipeline).toHaveBeenCalledWith(
        expect.objectContaining({ country: undefined, position_types: ["phd"] }),
      ),
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

describe("OpportunitiesPage — PhD and Postdoc are separate searches (2C)", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockFetchOpportunities.mockResolvedValue({
      items: OPPORTUNITIES, total: 2, pages: 1,
    });
    mockFetchFields.mockResolvedValue({
      default: "astronomy", profiles: ["astronomy"],
      fields: [{ name: "astronomy", label: "Astronomy", description: "",
                 subfields: [] }],
    });
    mockFetchField.mockResolvedValue({
      name: "astronomy", label: "Astronomy", description: "", subfields: [],
      core_anchors: [], search_terms: [],
      sources: { dedicated: [], general: [], has_dedicated: true },
    });
    mockFetchFieldDepartments.mockResolvedValue({
      field: "astronomy", total: 0, countries: [], departments: [],
    });
    mockFetchPositionTypes.mockResolvedValue({
      types: [
        { name: "phd", label: "PhD", description: "Doctoral positions.",
          enabled: true },
        { name: "postdoc", label: "Postdoc", description: "Postdoc roles.",
          enabled: true },
        { name: "masters", label: "Master's", description: "Master's.",
          enabled: false },
        { name: "scholarship", label: "Scholarship", description: "Funding.",
          enabled: false },
      ],
      default: ["phd", "postdoc"],
    });
  });

  it("defaults to PhD and searches only PhD", async () => {
    mockTriggerPipeline.mockResolvedValue({ status: "started", run_id: "t1" });
    mockJobStatus.mockResolvedValue({ run_id: "t1", status: "running" });
    const user = userEvent.setup();
    render(<OpportunitiesPage />);
    await screen.findByText("PhD in radio astronomy");

    expect(screen.getByRole("tab", { name: /^PhD/ })).toHaveAttribute(
      "aria-selected", "true",
    );
    await user.click(screen.getByRole("button", { name: "Search for positions" }));
    await waitFor(() =>
      expect(mockTriggerPipeline).toHaveBeenCalledWith(
        expect.objectContaining({ position_types: ["phd"] }),
      ),
    );
  });

  it("switching to Postdoc searches postdocs only — not a blended list", async () => {
    mockTriggerPipeline.mockResolvedValue({ status: "started", run_id: "t2" });
    mockJobStatus.mockResolvedValue({ run_id: "t2", status: "running" });
    const user = userEvent.setup();
    render(<OpportunitiesPage />);
    await screen.findByText("PhD in radio astronomy");

    await user.click(screen.getByRole("tab", { name: /^Postdoc/ }));
    await user.click(screen.getByRole("button", { name: "Search for positions" }));

    await waitFor(() =>
      expect(mockTriggerPipeline).toHaveBeenCalledWith(
        expect.objectContaining({ position_types: ["postdoc"] }),
      ),
    );
    // ...and the stored list is scoped the same way, so the two never mix.
    await waitFor(() =>
      expect(mockFetchOpportunities).toHaveBeenCalledWith(
        expect.objectContaining({ type: "postdoc" }),
      ),
    );
  });

  it("shows Master's and Scholarships as disabled 'coming soon'", async () => {
    render(<OpportunitiesPage />);
    const masters = await screen.findByRole("tab", { name: /Master/ });
    const scholarship = screen.getByRole("tab", { name: /Scholarship/ });
    expect(masters).toBeDisabled();
    expect(scholarship).toBeDisabled();
    expect(screen.getAllByText("Coming soon")).toHaveLength(2);
  });

  it("a coming-soon type cannot be selected", async () => {
    const user = userEvent.setup();
    render(<OpportunitiesPage />);
    const masters = await screen.findByRole("tab", { name: /Master/ });
    await user.click(masters).catch(() => {});

    expect(screen.getByRole("tab", { name: /^PhD/ })).toHaveAttribute(
      "aria-selected", "true",
    );
  });

  it("names the position type in the headline count", async () => {
    const user = userEvent.setup();
    render(<OpportunitiesPage />);
    expect(await screen.findByText("2 open PhD positions.")).toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: /^Postdoc/ }));
    expect(
      await screen.findByText("2 open postdoc positions."),
    ).toBeInTheDocument();
  });
});

describe("OpportunitiesPage — results stream in as they arrive (6A)", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockFetchOpportunities.mockResolvedValue({ items: [], total: 0, pages: 0 });
    mockFetchFields.mockResolvedValue({
      default: "astronomy", profiles: ["astronomy"],
      fields: [{ name: "astronomy", label: "Astronomy", description: "",
                 subfields: [] }],
    });
    mockFetchField.mockResolvedValue({
      name: "astronomy", label: "Astronomy", description: "", subfields: [],
      core_anchors: [], search_terms: [],
      sources: { dedicated: [], general: [], has_dedicated: true },
    });
    mockFetchFieldDepartments.mockResolvedValue({
      field: "astronomy", total: 0, countries: [], departments: [],
    });
    mockFetchPositionTypes.mockResolvedValue({
      types: [
        { name: "phd", label: "PhD", description: "Doctoral.", enabled: true },
        { name: "postdoc", label: "Postdoc", description: "Postdoc.",
          enabled: true },
      ],
      default: ["phd", "postdoc"],
    });
  });

  it("shows positions as each source answers, not only at the end", async () => {
    mockTriggerPipeline.mockResolvedValue({ status: "started", run_id: "st" });
    mockJobStatus.mockResolvedValue({
      run_id: "st",
      status: "running",
      progress: {
        total: 3,
        completed: 2,
        found_count: 2,
        sources: [
          { source: "eso", status: "done", records: 4 },
          { source: "euraxess", status: "done", records: 6 },
        ],
        found: [
          { title: "PhD in Radio Astronomy", institution: "MPIfR",
            country: "Germany", url: "https://x/1", source: "eso",
            position_type: "phd" },
          { title: "PhD in Cosmology", institution: "Leiden Observatory",
            country: "Netherlands", url: "https://x/2", source: "euraxess",
            position_type: "phd" },
        ],
      },
    });
    const user = userEvent.setup();
    render(<OpportunitiesPage />);
    await user.click(
      await screen.findByRole("button", { name: /Search for positions/ }),
    );

    // Results appear DURING the search — the stored list is still empty.
    const panel = await screen.findByTestId("run-live-results");
    expect(within(panel).getByText("PhD in Radio Astronomy")).toBeInTheDocument();
    expect(within(panel).getByText("PhD in Cosmology")).toBeInTheDocument();
    // ...with a running found-count beside them.
    expect(screen.getByTestId("run-found-count")).toHaveTextContent("2");
    expect(screen.getByTestId("run-progress-count")).toHaveTextContent("2 / 3");
  });

  it("links each streamed position to its advert", async () => {
    mockTriggerPipeline.mockResolvedValue({ status: "started", run_id: "sl" });
    mockJobStatus.mockResolvedValue({
      run_id: "sl", status: "running",
      progress: {
        total: 1, completed: 1, found_count: 1,
        sources: [{ source: "eso", status: "done", records: 1 }],
        found: [{ title: "PhD in Radio Astronomy", institution: "MPIfR",
                  country: "Germany", url: "https://example.test/job",
                  source: "eso", position_type: "phd" }],
      },
    });
    const user = userEvent.setup();
    render(<OpportunitiesPage />);
    await user.click(
      await screen.findByRole("button", { name: /Search for positions/ }),
    );

    // The run dialog is modal, so the page behind it is aria-hidden — the
    // streamed results have to be reachable INSIDE the dialog, which is where
    // the user is looking while a search runs.
    const panel = await screen.findByTestId("run-live-results");
    expect(
      within(panel).getByRole("link", { name: "PhD in Radio Astronomy" }),
    ).toHaveAttribute("href", "https://example.test/job");
  });

  it("replaces the live list with the deduped one when the run finishes", async () => {
    mockTriggerPipeline.mockResolvedValue({ status: "started", run_id: "sf" });
    mockJobStatus.mockResolvedValue({
      run_id: "sf",
      status: "completed",
      records: 1,
      progress: {
        total: 1, completed: 1, found_count: 2,
        sources: [{ source: "eso", status: "done", records: 2 }],
        found: [
          { title: "Live one", institution: null, country: null,
            url: "https://x/1", source: "eso", position_type: "phd" },
          { title: "Live two", institution: null, country: null,
            url: "https://x/2", source: "eso", position_type: "phd" },
        ],
      },
    });
    mockFetchOpportunities.mockResolvedValue({
      items: [opportunity({ id: 9, title: "Final deduped result" })],
      total: 1, pages: 1,
    });
    const user = userEvent.setup();
    render(<OpportunitiesPage />);
    await user.click(
      await screen.findByRole("button", { name: /Search for positions/ }),
    );

    // Once finished, only the authoritative list remains — the live preview
    // is not left on screen alongside it.
    expect(
      await screen.findByText("Final deduped result", {}, { timeout: 4000 }),
    ).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.queryByTestId("live-count")).not.toBeInTheDocument(),
    );
  });
});
