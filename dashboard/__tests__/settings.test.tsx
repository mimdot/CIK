import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import SettingsPage from "@/app/settings/page";
import { ToastProvider } from "@/components/ui/toast";
import {
  ApiError,
  fetchFields,
  fetchMe,
  fetchPreferences,
  updateDigestPreference,
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
}));

jest.mock("@/components/AuthGate", () => ({
  __esModule: true,
  default: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

const mockFetchFields = fetchFields as jest.Mock;
const mockFetchMe = fetchMe as jest.Mock;
const mockFetchPreferences = fetchPreferences as jest.Mock;
const mockUpdateDigestPreference = updateDigestPreference as jest.Mock;

const USER: User = { user_id: 1, email: "astronomer@example.org" };
const PREFS = { digest_enabled: false, frequency: null };

describe("SettingsPage", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    localStorage.clear();
    mockFetchPreferences.mockResolvedValue(PREFS);
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

    const toggle = screen.getByRole("button", { name: "Disabled" });
    await user.click(toggle);

    await waitFor(() =>
      expect(mockUpdateDigestPreference).toHaveBeenCalledWith(true),
    );
    expect(await screen.findByText("Email digest enabled")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Enabled" })).toBeInTheDocument();
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
      await screen.findByRole("button", { name: "Enabled" }),
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

    await user.click(screen.getByRole("button", { name: "Disabled" }));

    expect(
      await screen.findAllByText("No active profile — build one first"),
    ).toHaveLength(2);
    expect(screen.getByRole("button", { name: "Disabled" })).toBeInTheDocument();
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
