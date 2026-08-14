import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import SettingsPage from "@/app/(app)/settings/page";
import { ToastProvider } from "@/components/ui/toast";
import {
  ApiError,
  fetchFields,
  fetchMe,
  fetchPreferences,
  fetchProfile,
  updateDigestPreference,
  updateProfile,
} from "@/lib/api";
import type { User } from "@/types";

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
  fetchFields: jest.fn(),
  fetchMe: jest.fn(),
  fetchPreferences: jest.fn(),
  updateDigestPreference: jest.fn(),
  // The field control is now a REAL setting stored on the user's profile,
  // not a local-only dropdown that reset on every reload.
  fetchProfile: jest.fn(),
  updateProfile: jest.fn(),
}));

jest.mock("@/components/AuthGate", () => ({
  __esModule: true,
  default: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

const mockFetchFields = fetchFields as jest.Mock;
const mockFetchMe = fetchMe as jest.Mock;
const mockFetchPreferences = fetchPreferences as jest.Mock;
const mockUpdateDigestPreference = updateDigestPreference as jest.Mock;
const mockFetchProfile = fetchProfile as jest.Mock;
const mockUpdateProfile = updateProfile as jest.Mock;

const USER: User = { user_id: 1, email: "astronomer@example.org" };
const PREFS = { digest_enabled: false, frequency: null };

describe("SettingsPage", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    localStorage.clear();
    mockFetchPreferences.mockResolvedValue(PREFS);
    mockFetchProfile.mockResolvedValue({ domain: "astronomy", skills: [] });
    mockUpdateProfile.mockImplementation(async (patch) => ({
      domain: patch.domain ?? "astronomy", skills: [],
    }));
  });

  function renderPage() {
    return render(
      <ToastProvider>
        <SettingsPage />
      </ToastProvider>,
    );
  }

  it("shows the signed-in account email", async () => {
    mockFetchFields.mockResolvedValue({ default: "astronomy", profiles: ["astronomy", "physics"] });
    mockFetchMe.mockResolvedValue(USER);
    renderPage();

    expect(
      await screen.findByText("astronomer@example.org"),
    ).toBeInTheDocument();
  });

  it("lists field profiles in the dropdown", async () => {
    mockFetchFields.mockResolvedValue({ default: "astronomy", profiles: ["astronomy", "physics"] });
    mockFetchMe.mockResolvedValue(USER);
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("astronomer@example.org");

    await user.click(screen.getByLabelText("Field profile"));
    expect(
      await screen.findByRole("option", { name: "astronomy" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("option", { name: "physics" }),
    ).toBeInTheDocument();
  });

  it("toggles the email digest via the API", async () => {
    mockFetchFields.mockResolvedValue({ default: "astronomy", profiles: ["astronomy"] });
    mockFetchMe.mockResolvedValue(USER);
    mockUpdateDigestPreference.mockResolvedValue({
      digest_enabled: true,
      frequency: "weekly",
    });
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("astronomer@example.org");

    const toggle = screen.getByRole("button", { name: "No thanks" });
    await user.click(toggle);

    await waitFor(() =>
      expect(mockUpdateDigestPreference).toHaveBeenCalledWith(true),
    );
    expect(await screen.findByText("Email digest enabled")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Yes, when ready" })).toBeInTheDocument();
  });

  it("restores the server-side digest state on load", async () => {
    mockFetchFields.mockResolvedValue({ default: "astronomy", profiles: ["astronomy"] });
    mockFetchMe.mockResolvedValue(USER);
    mockFetchPreferences.mockResolvedValue({
      digest_enabled: true,
      frequency: "weekly",
    });
    renderPage();

    expect(
      await screen.findByRole("button", { name: "Yes, when ready" }),
    ).toBeInTheDocument();
  });

  it("reverts the toggle when the API save fails", async () => {
    mockFetchFields.mockResolvedValue({ default: "astronomy", profiles: ["astronomy"] });
    mockFetchMe.mockResolvedValue(USER);
    mockUpdateDigestPreference.mockRejectedValue(
      new ApiError("No active profile — build one first", 404),
    );
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("astronomer@example.org");

    await user.click(screen.getByRole("button", { name: "No thanks" }));

    expect(
      await screen.findAllByText("No active profile — build one first"),
    ).toHaveLength(2);
    expect(screen.getByRole("button", { name: "No thanks" })).toBeInTheDocument();
  });

  it("shows an error state when fields cannot be loaded", async () => {
    mockFetchFields.mockRejectedValue(new ApiError("Downstream error", 500));
    mockFetchMe.mockResolvedValue(USER);
    renderPage();

    expect(
      await screen.findByText("Downstream error"),
    ).toBeInTheDocument();
  });
});

describe("SettingsPage — plain language and a real control (Phase 5)", () => {
  function renderPage() {
    return render(
      <ToastProvider>
        <SettingsPage />
      </ToastProvider>,
    );
  }

  beforeEach(() => {
    jest.clearAllMocks();
    mockFetchPreferences.mockResolvedValue(PREFS);
    mockFetchMe.mockResolvedValue(USER);
    mockFetchFields.mockResolvedValue({
      default: "astronomy",
      profiles: ["astronomy", "chemistry"],
    });
    mockFetchProfile.mockResolvedValue({ domain: "chemistry", skills: [] });
    mockUpdateProfile.mockImplementation(async (patch) => ({
      domain: patch.domain ?? "chemistry", skills: [],
    }));
  });

  it("leaks no CLI flags or internal jargon into the UI", async () => {
    renderPage();
    await screen.findByText(/astronomer@example.org/);
    const body = document.body.textContent ?? "";
    // The old copy read: "Pass this to the pipeline runner with --field."
    expect(body).not.toContain("--field");
    expect(body).not.toContain("pipeline runner");
    expect(body).not.toContain("Active profile:");
  });

  it("shows the field already saved on the profile, not a server default", async () => {
    renderPage();
    // A second control that reset to the server default on every load was
    // exactly the "confusing / competing setting" problem.
    await waitFor(() =>
      expect(screen.getByLabelText("Field profile")).toHaveTextContent(
        "chemistry",
      ),
    );
  });

  it("actually saves the field when it is changed", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText(/astronomer@example.org/);

    await user.click(screen.getByLabelText("Field profile"));
    await user.click(await screen.findByRole("option", { name: "astronomy" }));

    await waitFor(() =>
      expect(mockUpdateProfile).toHaveBeenCalledWith({ domain: "astronomy" }),
    );
  });

  it("labels the email digest as a planned feature", async () => {
    renderPage();
    await screen.findByText(/astronomer@example.org/);
    expect(screen.getAllByText("Coming soon").length).toBeGreaterThan(0);
  });

  it("reserves a place for a future donation option (6C)", async () => {
    renderPage();
    expect(
      await screen.findByTestId("donation-placeholder"),
    ).toBeInTheDocument();
    // A placeholder, not a live button that goes nowhere.
    expect(
      screen.queryByRole("button", { name: /donate/i }),
    ).not.toBeInTheDocument();
  });
});
