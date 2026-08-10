import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import SupervisorsPage from "@/app/(app)/supervisors/page";
import { ApiError, fetchSupervisors } from "@/lib/api";
import type { Supervisor } from "@/types";

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
  fetchSupervisors: jest.fn(),
}));

const mockFetchSupervisors = fetchSupervisors as jest.Mock;

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
    fit_score: 0.85,
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
    fit_score: 0.85,
  }),
  supervisor({
    id: 2,
    name: "Prof. Omar Haddad",
    institution: "Leiden Observatory",
    country: "Netherlands",
    topics: ["galaxy formation", "cosmology"],
    fit_score: 0.6,
    orcid: null,
    profile_url: null,
  }),
];

describe("SupervisorsPage", () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it("renders supervisor cards with fit scores", async () => {
    mockFetchSupervisors.mockResolvedValue({ items: SUPERVISORS, total: 2 });
    render(<SupervisorsPage />);

    expect(await screen.findByText("Dr. Lena Kraft")).toBeInTheDocument();
    expect(screen.getByText("Prof. Omar Haddad")).toBeInTheDocument();
    const scores = screen
      .getAllByTestId("fit-score")
      .map((el) => el.textContent);
    expect(scores).toEqual(["Fit 85%", "Fit 60%"]);
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
      expect(scores).toEqual(["Fit 60%", "Fit 85%"]);
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
});
