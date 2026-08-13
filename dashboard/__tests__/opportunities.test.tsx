import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import OpportunitiesPage from "@/app/(app)/opportunities/page";
import { ApiError, fetchFields, fetchOpportunities, jobStatus, triggerPipeline } from "@/lib/api";
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
    triggerPipeline: jest.fn(),
    jobStatus: jest.fn(),
  };
});

const mockFetchOpportunities = fetchOpportunities as jest.Mock;
const mockFetchFields = fetchFields as jest.Mock;
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
    });
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

    await user.click(screen.getByLabelText("Field to crawl"));
    await user.click(await screen.findByRole("option", { name: "biology" }));
    await user.click(screen.getByRole("button", { name: "Run engine" }));

    await waitFor(() =>
      expect(mockTriggerPipeline).toHaveBeenCalledWith({
        country: undefined,
        field: "biology",
      }),
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
    await user.click(screen.getByRole("button", { name: "Run engine" }));

    expect(await screen.findByTestId("run-progress-count")).toHaveTextContent(
      "2 / 3",
    );
    expect(screen.getByText("eso")).toBeInTheDocument();
    expect(screen.getByText("aas")).toBeInTheDocument();
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
    await user.click(screen.getByRole("button", { name: "Run engine" }));

    await waitFor(() =>
      expect(mockTriggerPipeline).toHaveBeenCalledWith({
        country: "Germany",
      }),
    );

    expect(await screen.findByText("Run completed.")).toBeInTheDocument();
    expect(screen.getByTestId("run-status")).toHaveTextContent("completed");
    expect(screen.getByTestId("run-records")).toHaveTextContent("42");

    expect(await screen.findByText(/Engine run finished — 42 records/)).toBeInTheDocument();

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

    await user.click(screen.getByRole("button", { name: "Run engine" }));

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

    await user.click(screen.getByRole("button", { name: "Run engine" }));

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
