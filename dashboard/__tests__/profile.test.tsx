import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import ProfilePage from "@/app/(app)/profile/page";
import { ToastProvider } from "@/components/ui/toast";
import {
  analyseCv,
  ApiError,
  buildProfile,
  extractCv,
  fetchField,
  fetchFields,
  fetchParserSupport,
  fetchProfile,
  updateProfile,
} from "@/lib/api";
import type { UserProfile } from "@/types";
// shared auth mock loaded via jest.requireActual inside the factory

jest.mock("@/lib/api", () => {
  const { mockAuthApi } = jest.requireActual("../test-utils/mock-auth");
  return mockAuthApi({
    login: jest.fn(), register: jest.fn(),
    buildProfile: jest.fn(), extractCv: jest.fn(),
    fetchProfile: jest.fn(), updateProfile: jest.fn(),
    // Phase 3: the keyword picker is the primary path; the CV only pre-fills.
    analyseCv: jest.fn(), fetchParserSupport: jest.fn(),
    fetchFields: jest.fn(), fetchField: jest.fn(),
  });
});

const mockBuildProfile = buildProfile as jest.Mock;
const mockExtractCv = extractCv as jest.Mock;
const mockFetchProfile = fetchProfile as jest.Mock;
const mockUpdateProfile = updateProfile as jest.Mock;
const mockAnalyseCv = analyseCv as jest.Mock;
const mockParserSupport = fetchParserSupport as jest.Mock;
const mockFetchFields = fetchFields as jest.Mock;
const mockFetchField = fetchField as jest.Mock;

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
    mockParserSupport.mockResolvedValue({ txt: true, pdf: true, docx: true });
    mockFetchFields.mockResolvedValue({
      default: "astronomy",
      profiles: ["astronomy", "chemistry"],
      fields: [
        { name: "astronomy", label: "Astronomy", description: "", subfields: [] },
        { name: "chemistry", label: "Chemistry", description: "", subfields: [] },
      ],
    });
    mockFetchField.mockImplementation(async (name: string) => ({
      name,
      label: name === "chemistry" ? "Chemistry" : "Astronomy",
      description: "",
      subfields: [
        {
          id: "organic", label: "Organic Chemistry", keyword_count: 3,
          keywords: ["organic chemistry", "total synthesis", "organocatalysis"],
        },
        {
          id: "catalysis", label: "Catalysis", keyword_count: 2,
          keywords: ["heterogeneous catalysis", "photocatalysis"],
        },
      ],
      core_anchors: [],
      search_terms: [],
      sources: { dedicated: [], general: [], has_dedicated: true },
    }));
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
      screen.getByRole("button", { name: "Build full profile" }),
    ).toBeInTheDocument();
  });

  it("uploads a CV file and fills the text area with extracted text (2B)", async () => {
    mockExtractCv.mockResolvedValue({
      filename: "cv.txt",
      chars: 37,
      raw_text: "Extracted CV: astronomer, ISM, LOFAR.",
    });
    const user = userEvent.setup();
    renderPage();

    const input = await screen.findByLabelText("Upload CV file");
    const file = new File(["binary-bytes"], "cv.txt", { type: "text/plain" });
    await user.upload(input, file);

    await waitFor(() => expect(mockExtractCv).toHaveBeenCalledWith(file));
    await waitFor(() =>
      expect(screen.getByLabelText("CV / bio text")).toHaveValue(
        "Extracted CV: astronomer, ISM, LOFAR.",
      ),
    );
  });

  it("builds a profile and displays the extracted result", async () => {
    mockBuildProfile.mockResolvedValue(PROFILE);
    const user = userEvent.setup();
    renderPage();

    const textarea = await screen.findByLabelText("CV / bio text");
    await user.type(textarea, "I am an astronomer working on the ISM.");

    await user.click(screen.getByRole("button", { name: "Build full profile" }));

    await waitFor(() =>
      expect(mockBuildProfile).toHaveBeenCalledWith(
        "I am an astronomer working on the ISM.",
      ),
    );
    expect(await screen.findByText("Your profile")).toBeInTheDocument();
    expect(screen.getByLabelText("Domain")).toHaveValue("astronomy");
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
    await user.click(screen.getByRole("button", { name: "Build full profile" }));

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

    expect(await screen.findByLabelText("Domain")).toHaveValue("astronomy");
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
    await screen.findByLabelText("Domain");

    const domain = screen.getByLabelText("Domain");
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
    await screen.findByLabelText("Domain");

    const domain = screen.getByLabelText("Domain");
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
    await screen.findByLabelText("Domain");

    const conf = screen.getByLabelText("Confidence (0–1)");
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

describe("ProfilePage — CV pre-fills the keyword picker (3B/3C)", () => {
  function renderPage() {
    return render(
      <ToastProvider>
        <ProfilePage />
      </ToastProvider>,
    );
  }

  beforeEach(() => {
    mockFetchProfile.mockResolvedValue(PROFILE);
  });

  it("ticks the keywords a CV mentions instead of failing", async () => {
    mockAnalyseCv.mockResolvedValue({
      field: "chemistry",
      field_scores: { chemistry: 4 },
      subfields: ["organic"],
      keywords: ["organic chemistry", "total synthesis"],
      tools: ["python"],
      countries: ["Switzerland"],
      experience_level: "phd",
      found_anything: true,
      notes: [],
      reason: null,
    });
    const user = userEvent.setup();
    renderPage();
    await screen.findByLabelText("Domain");

    await user.type(screen.getByLabelText("CV / bio text"), "organic chemistry");
    await user.click(screen.getByRole("button", { name: "Pre-fill my keywords" }));

    // No AI service involved, and the result lands in the picker as chips.
    const chips = await screen.findByTestId("keyword-chips");
    expect(within(chips).getByText("total synthesis")).toBeInTheDocument();
    expect(await screen.findByText(/Found 2 keywords/)).toBeInTheDocument();
  });

  it("explains WHY nothing was found rather than showing a generic error", async () => {
    mockAnalyseCv.mockResolvedValue({
      field: null, field_scores: {}, subfields: [], keywords: [], tools: [],
      countries: [], experience_level: null, found_anything: false,
      notes: ["No research field could be recognised from this text."],
      reason: "no_field_match",
    });
    const user = userEvent.setup();
    renderPage();
    await screen.findByLabelText("Domain");

    await user.type(screen.getByLabelText("CV / bio text"), "asdf qwerty");
    await user.click(screen.getByRole("button", { name: "Pre-fill my keywords" }));

    expect(
      await screen.findByText(/No research field could be recognised/),
    ).toBeInTheDocument();
  });

  it("warns when this installation cannot read PDFs", async () => {
    mockParserSupport.mockResolvedValue({ txt: true, pdf: false, docx: false });
    renderPage();
    expect(
      await screen.findByText(/cannot read PDF files/),
    ).toBeInTheDocument();
  });
});
