import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import ProfilePage from "@/app/profile/page";
import { ToastProvider } from "@/components/ui/toast";
import { ApiError, buildProfile, fetchProfile, updateProfile } from "@/lib/api";
import type { UserProfile } from "@/types";

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
  buildProfile: jest.fn(),
  fetchProfile: jest.fn(),
  updateProfile: jest.fn(),
}));

const mockBuildProfile = buildProfile as jest.Mock;
const mockFetchProfile = fetchProfile as jest.Mock;
const mockUpdateProfile = updateProfile as jest.Mock;

const PROFILE: UserProfile = {
  domain: "astronomy",
  subfield: "interstellar medium",
  methods: ["radio interferometry"],
  tools: ["LOFAR"],
  skills: ["dust polarization"],
  experience_level: "phd_student",
  target_roles: ["postdoc"],
  countries_preferred: ["Germany"],
  funding_requirement: null,
  constraints: [],
  confidence: 0.9,
  raw_text: "Sample CV",
};

describe("ProfilePage", () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  function renderPage() {
    return render(
      <ToastProvider>
        <ProfilePage />
      </ToastProvider>,
    );
  }

  it("renders the CV textarea and build button", async () => {
    renderPage();
    expect(await screen.findByLabelText("CV / bio text")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Re-build from CV" }),
    ).toBeInTheDocument();
  });

  it("builds a profile and displays the extracted result", async () => {
    mockBuildProfile.mockResolvedValue(PROFILE);
    const user = userEvent.setup();
    renderPage();

    const textarea = await screen.findByLabelText("CV / bio text");
    await user.type(textarea, "I am an astronomer working on the ISM.");

    await user.click(screen.getByRole("button", { name: "Re-build from CV" }));

    await waitFor(() =>
      expect(mockBuildProfile).toHaveBeenCalledWith(
        "I am an astronomer working on the ISM.",
      ),
    );
    expect(await screen.findByText("Your profile")).toBeInTheDocument();
    expect(screen.getByDisplayValue("astronomy")).toBeInTheDocument();
    expect(screen.getByText(/90%/)).toBeInTheDocument();
    expect(screen.getByDisplayValue("radio interferometry")).toBeInTheDocument();
  });

  it("shows an error when extraction fails", async () => {
    mockBuildProfile.mockRejectedValue(
      new ApiError("Could not extract profile from text", 422),
    );
    const user = userEvent.setup();
    renderPage();

    const textarea = await screen.findByLabelText("CV / bio text");
    await user.type(textarea, "some text");
    await user.click(screen.getByRole("button", { name: "Re-build from CV" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Could not extract profile from text",
    );
  });

  it("loads an existing profile into the editable form", async () => {
    mockFetchProfile.mockResolvedValue(PROFILE);
    const user = userEvent.setup();
    renderPage();

    await user.click(
      await screen.findByRole("button", { name: "Reload profile" }),
    );

    expect(await screen.findByDisplayValue("astronomy")).toBeInTheDocument();
    expect(screen.getByDisplayValue("LOFAR")).toBeInTheDocument();
  });

  it("saves manual edits via updateProfile", async () => {
    mockFetchProfile.mockResolvedValue(PROFILE);
    mockUpdateProfile.mockResolvedValue({ ...PROFILE, domain: "physics" });
    const user = userEvent.setup();
    renderPage();

    await user.click(
      await screen.findByRole("button", { name: "Reload profile" }),
    );
    await screen.findByDisplayValue("astronomy");

    const domain = screen.getByDisplayValue("astronomy");
    await user.clear(domain);
    await user.type(domain, "physics");
    await user.click(screen.getByRole("button", { name: "Save profile" }));

    await waitFor(() =>
      expect(mockUpdateProfile).toHaveBeenCalledWith(
        expect.objectContaining({ domain: "physics" }),
      ),
    );
    expect(await screen.findByText("Profile saved")).toBeInTheDocument();
  });

  it("blocks save and shows inline errors when validation fails", async () => {
    mockFetchProfile.mockResolvedValue(PROFILE);
    const user = userEvent.setup();
    renderPage();

    await user.click(
      await screen.findByRole("button", { name: "Reload profile" }),
    );
    await screen.findByDisplayValue("astronomy");

    const domain = screen.getByDisplayValue("astronomy");
    await user.clear(domain);

    expect(
      await screen.findByText("Domain is required."),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Save profile" }),
    ).toBeDisabled();
    expect(mockUpdateProfile).not.toHaveBeenCalled();
  });

  it("blocks save when confidence is out of range", async () => {
    mockFetchProfile.mockResolvedValue(PROFILE);
    const user = userEvent.setup();
    renderPage();

    await user.click(
      await screen.findByRole("button", { name: "Reload profile" }),
    );
    await screen.findByDisplayValue("astronomy");

    const conf = screen.getByDisplayValue("0.9");
    await user.clear(conf);
    await user.type(conf, "1.5");

    expect(
      await screen.findByText("Confidence must be between 0 and 1."),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Save profile" }),
    ).toBeDisabled();
    expect(mockUpdateProfile).not.toHaveBeenCalled();
  });
});
