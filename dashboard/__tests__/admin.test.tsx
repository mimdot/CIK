import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import AdminPage from "@/app/admin/page";
import {
  ApiError,
  createInvite,
  fetchAdminMetrics,
  fetchAnomalies,
  fetchDeadLetters,
  fetchFeedbackIntel,
  fetchInvites,
  fetchSourceHealth,
  fetchWorkerHeartbeat,
  retryDeadLetter,
  runAnomalyDetect,
  runDriftCheck,
} from "@/lib/api";
import type { AdminMetrics, InviteList } from "@/types";

jest.mock("@/lib/api", () => ({
  ApiError: class ApiError extends Error {
    status: number;
    constructor(message: string, status: number) {
      super(message);
      this.status = status;
    }
  },
  getToken: jest.fn(() => "test-token"),
  fetchAdminMetrics: jest.fn(),
  fetchInvites: jest.fn(),
  createInvite: jest.fn(),
  fetchSourceHealth: jest.fn(),
  fetchFeedbackIntel: jest.fn(),
  fetchDeadLetters: jest.fn(),
  fetchWorkerHeartbeat: jest.fn(),
  fetchAnomalies: jest.fn(),
  runDriftCheck: jest.fn(),
  runAnomalyDetect: jest.fn(),
  retryDeadLetter: jest.fn(),
}));

const mockFetchAdminMetrics = fetchAdminMetrics as jest.Mock;
const mockFetchInvites = fetchInvites as jest.Mock;
const mockCreateInvite = createInvite as jest.Mock;
const mockFetchSourceHealth = fetchSourceHealth as jest.Mock;
const mockFetchFeedbackIntel = fetchFeedbackIntel as jest.Mock;
const mockFetchDeadLetters = fetchDeadLetters as jest.Mock;
const mockFetchWorkerHeartbeat = fetchWorkerHeartbeat as jest.Mock;
const mockFetchAnomalies = fetchAnomalies as jest.Mock;
const mockRunDriftCheck = runDriftCheck as jest.Mock;
const mockRunAnomalyDetect = runAnomalyDetect as jest.Mock;
const mockRetryDeadLetter = retryDeadLetter as jest.Mock;

const METRICS: AdminMetrics = {
  users: { total: 3, active: 1, profiles_built: 2 },
  content: {
    opportunities: 42,
    supervisors: 8,
    matches: 15,
    sources: [
      { source: "euraxess", records: 30, last_posted: "2026-08-01T00:00:00" },
      { source: "findaphd", records: 12, last_posted: null },
    ],
    feedback: { total: 5, helpful: 3 },
  },
  api: {
    requests: 100,
    errors: 1,
    error_rate: 0.01,
    avg_latency_ms: 12.5,
    p95_latency_ms: 40.0,
    median_latency_ms: 10.0,
  },
  jobs: { backend: "in-process", pending: 0, running: 1, completed: 4, failed: 0, total: 5 },
  invites: { created: 2, redeemed: 1, pending: 1 },
  updated_at: "2026-08-04T00:00:00Z",
};

const INVITES: InviteList = {
  items: [
    { id: 1, code: "abcd1234", created_by: 1, used: false },
    { id: 2, code: "efgh5678", created_by: 1, used: true },
  ],
  created: 2,
  redeemed: 1,
  pending: 1,
};

beforeEach(() => {
  jest.clearAllMocks();
  mockFetchSourceHealth.mockResolvedValue({
    sources: [
      { source: "euraxess", runs: 12, errors: 0, last_result: 9, mean: 10, std: 1.2, zscore: 0.4, drift: false },
      { source: "findaphd", runs: 8, errors: 3, last_result: 50, mean: 7, std: 0.8, zscore: 6.1, drift: true },
    ],
  });
  mockFetchFeedbackIntel.mockResolvedValue({
    summary: { total: 4, helpful: 2, unhelpful: 2, rate: 0.5 },
    brackets: [
      { key: "0-20", total: 2, helpful: 0, rate: 0.0 },
      { key: "80-100", total: 2, helpful: 2, rate: 1.0 },
    ],
    sources: [{ key: "euraxess", total: 4, helpful: 2, rate: 0.5 }],
    comments: {
      keywords: [{ keyword: "funding", count: 3 }],
      samples: [{ comment: "Missing funding details", score: 12, source: "euraxess" }],
    },
  });
  mockFetchDeadLetters.mockResolvedValue({
    jobs: [
      { job_id: "job123", status: "failed", error: "boom", attempts: 2 },
      { job_id: "job456", status: "failed", error: "disk full", attempts: 1 },
    ],
  });
  mockFetchWorkerHeartbeat.mockResolvedValue({ backend: "in-process", workers: {} });
  mockFetchAnomalies.mockResolvedValue({
    slot_s: 60,
    slots: [],
    current: null,
    summaries: { requests: 100, errors: 0, error_rate: 0.0, avg_latency_ms: 80.0 },
    anomalies: [
      { id: "anomaly1", kind: "latency-spike", ts: 1, message: "latency spike 900ms vs 80ms baseline" },
    ],
  });
});

describe("AdminPage", () => {
  it("renders metrics and invites", async () => {
    mockFetchAdminMetrics.mockResolvedValue(METRICS);
    mockFetchInvites.mockResolvedValue(INVITES);

    render(<AdminPage />);

    expect(await screen.findByText("Total users")).toBeInTheDocument();
    expect(screen.getAllByText("100").length).toBeGreaterThan(0);
    expect(screen.getAllByText("euraxess").length).toBeGreaterThan(0);
    expect(screen.getByText("abcd1234")).toBeInTheDocument();
    expect(screen.getAllByText(/in-process/).length).toBeGreaterThan(0);
  });

  it("creates an invite and shows the new code", async () => {
    mockFetchAdminMetrics.mockResolvedValue(METRICS);
    mockFetchInvites.mockResolvedValue(INVITES);
    mockCreateInvite.mockResolvedValue({ id: 3, code: "newcode99", created_by: 1, used: false });
    const user = userEvent.setup();

    render(<AdminPage />);
    await screen.findByText("Total users");

    await user.click(screen.getByRole("button", { name: "Create invite" }));

    expect(mockCreateInvite).toHaveBeenCalled();
    await waitFor(() =>
      expect(screen.getByTestId("new-invite-code")).toHaveTextContent("newcode99"),
    );
  });

  it("shows an admin-required error on 403", async () => {
    mockFetchAdminMetrics.mockRejectedValue(new ApiError("Admin privileges required", 403));
    mockFetchInvites.mockRejectedValue(new ApiError("Admin privileges required", 403));

    render(<AdminPage />);

    expect(
      await screen.findByText("Admin privileges required to view this page."),
    ).toBeInTheDocument();
  });

  it("renders source-health drift rows", async () => {
    render(<AdminPage />);

    expect(await screen.findByTestId("source-row-euraxess")).toBeInTheDocument();
    const driftRow = screen.getByTestId("source-row-findaphd");
    expect(driftRow).toHaveTextContent("6.1");
    expect(driftRow).toHaveTextContent("drift");
  });

  it("renders feedback intel keywords and samples", async () => {
    render(<AdminPage />);

    expect(await screen.findByText("funding · 3")).toBeInTheDocument();
    expect(screen.getByText("“Missing funding details”")).toBeInTheDocument();
    expect(screen.getByText("50%")).toBeInTheDocument();
  });

  it("renders dead-letter jobs and requeues one", async () => {
    mockRetryDeadLetter.mockResolvedValue({ retried: true, job_id: "job123", new_job_id: "job999" });
    render(<AdminPage />);

    expect(await screen.findByTestId("dead-letter-job123")).toBeInTheDocument();
    expect(screen.getByText("boom")).toBeInTheDocument();

    await userEvent.click(
      within(screen.getByTestId("dead-letter-job123")).getByRole("button", {
        name: "Retry",
      }),
    );

    expect(mockRetryDeadLetter).toHaveBeenCalledWith("job123");
    await waitFor(() =>
      expect(screen.getByTestId("ops-msg")).toHaveTextContent("Requeued job job123"),
    );
  });

  it("renders API anomalies", async () => {
    render(<AdminPage />);

    expect(await screen.findByTestId("anomaly-row")).toHaveTextContent(
      "latency spike 900ms",
    );
    expect(screen.getByText("0.00%")).toBeInTheDocument();
    expect(screen.getByText("80 ms")).toBeInTheDocument();
  });

  it("runs drift check and anomaly detection on demand", async () => {
    mockRunDriftCheck.mockResolvedValue({ count: 1, alert_ids: ["a"] });
    mockRunAnomalyDetect.mockResolvedValue({
      slot_s: 60,
      slots: [],
      current: null,
      summaries: { requests: 10, errors: 0, error_rate: 0.0, avg_latency_ms: 5.0 },
      anomalies: [],
    });
    render(<AdminPage />);

    await screen.findByTestId("source-row-euraxess");

    await userEvent.click(screen.getByRole("button", { name: "Check drift" }));
    await waitFor(() =>
      expect(screen.getByTestId("ops-msg")).toHaveTextContent("1 source(s) drifted"),
    );

    await userEvent.click(screen.getByRole("button", { name: "Re-run detection" }));
    await waitFor(() =>
      expect(screen.getByTestId("ops-msg")).toHaveTextContent("No API anomalies detected"),
    );
  });
});
