import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import OnboardingPage from "@/app/(app)/onboarding/page";
import {
  ApiError,
  buildProfile,
  fetchFields,
  fetchProfile,
  updateProfile,
  validateInvite,
} from "@/lib/api";
import type { UserProfile } from "@/types";

jest.mock("next/navigation", () => ({
  useRouter: jest.fn(),
}));

jest.mock("@/lib/api", () => ({
  ApiError: class ApiError extends Error {
    status: number;
    constructor(message: string, status: number) {
      super(message);
      this.status = status;
    }
  },
  getToken: jest.fn(() => "test-token"),
  fetchProfile: jest.fn(),
  fetchFields: jest.fn(),
  buildProfile: jest.fn(),
  updateProfile: jest.fn(),
  validateInvite: jest.fn(),
}));

const mockFetchProfile = fetchProfile as jest.Mock;
const mockFetchFields = fetchFields as jest.Mock;
const mockBuildProfile = buildProfile as jest.Mock;
const mockUpdateProfile = updateProfile as jest.Mock;
const mockValidateInvite = validateInvite as jest.Mock;

const PROFILE: UserProfile = {
  domain: "astronomy",
  subfield: "interstellar medium",
  methods: ["radio interferometry"],
  tools: ["Python"],
  skills: ["data analysis"],
  experience_level: "phd_student",
  target_roles: [],
  countries_preferred: [],
  funding_requirement: null,
  constraints: [],
  confidence: 0.9,
  raw_text: "CV text",
};

beforeEach(() => {
  jest.clearAllMocks();
  localStorage.clear();
  const { useRouter } = jest.requireMock("next/navigation") as {
    useRouter: jest.Mock;
  };
  (useRouter as jest.Mock).mockReturnValue({ push: jest.fn(), replace: jest.fn() });
});

describe("OnboardingPage", () => {
  it("shows the welcome step when no profile exists", async () => {
    mockFetchProfile.mockRejectedValue(new ApiError("no profile", 404));
    mockFetchFields.mockResolvedValue({ default: "astronomy", profiles: ["astronomy", "biology"] });

    render(<OnboardingPage />);

    expect(await screen.findByText("Get started")).toBeInTheDocument();
    expect(screen.getByTestId("onboarding-progress")).toHaveAttribute(
      "style",
      "width: 17%;",
    );
  });

  it("redirects to the dashboard when a profile already exists", async () => {
    mockFetchProfile.mockResolvedValue(PROFILE);
    mockFetchFields.mockResolvedValue({ default: "astronomy", profiles: [] });
    const { useRouter } = jest.requireMock("next/navigation") as {
      useRouter: jest.Mock;
    };
    const replace = jest.fn();
    (useRouter as jest.Mock).mockReturnValue({ push: jest.fn(), replace });

    render(<OnboardingPage />);

    await waitFor(() => expect(replace).toHaveBeenCalledWith("/"));
  });

  it("walks through the full wizard to completion", async () => {
    mockFetchProfile.mockRejectedValue(new ApiError("no profile", 404));
    mockFetchFields.mockResolvedValue({ default: "astronomy", profiles: ["astronomy", "biology"] });
    mockBuildProfile.mockResolvedValue(PROFILE);
    mockUpdateProfile.mockImplementation(async (patch) => ({ ...PROFILE, ...patch }));
    mockValidateInvite.mockResolvedValue({ valid: true, code: "SPRINT06" });
    const { useRouter } = jest.requireMock("next/navigation") as {
      useRouter: jest.Mock;
    };
    const push = jest.fn();
    (useRouter as jest.Mock).mockReturnValue({ push, replace: jest.fn() });
    const user = userEvent.setup();

    render(<OnboardingPage />);

    await user.type(await screen.findByLabelText("Invite code"), "SPRINT06");
    await user.click(screen.getByRole("button", { name: "Start" }));
    expect(mockValidateInvite).toHaveBeenCalledWith("SPRINT06");
    await user.type(screen.getByLabelText("CV / bio text"), "I am a PhD student in astronomy.");
    await user.click(screen.getByRole("button", { name: "Extract profile" }));

    expect(mockBuildProfile).toHaveBeenCalledWith("I am a PhD student in astronomy.");
    expect(await screen.findByText("Review your profile")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Looks good" }));
    expect(await screen.findByText("Select your field")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Continue" }));
    await waitFor(() => expect(mockUpdateProfile).toHaveBeenCalledWith({ domain: "astronomy" }));

    expect(await screen.findByText("Preferred countries")).toBeInTheDocument();
    await user.type(screen.getByLabelText("Countries"), "Germany, Netherlands");
    await user.click(screen.getByRole("button", { name: "Continue" }));

    await waitFor(() =>
      expect(mockUpdateProfile).toHaveBeenCalledWith({
        countries_preferred: ["Germany", "Netherlands"],
      }),
    );
    expect(await screen.findByText("You are all set")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Go to dashboard" }));
    expect(push).toHaveBeenCalledWith("/");
    expect(localStorage.getItem("cik_onboarding")).toBeNull();
  });
});
