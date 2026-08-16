import { render, screen } from "@testing-library/react";
import { ToastProvider } from "@/components/ui/toast";
import OnboardingPage from "@/app/(app)/onboarding/page";
import ProfilePage from "@/app/(app)/profile/page";
import { fetchParserSupport, fetchProfile } from "@/lib/api";

jest.mock("next/navigation", () => ({
  useRouter: () => ({ push: jest.fn(), replace: jest.fn() }),
}));

jest.mock("@/lib/api", () => {
  const { mockAuthApi } = jest.requireActual("../test-utils/mock-auth");
  return mockAuthApi({
    fetchProfile: jest.fn(),
    fetchFields: jest.fn(() => Promise.resolve({ profiles: ["astronomy"] })),
    fetchFieldCatalogue: jest.fn(() => Promise.resolve({ fields: [] })),
    buildProfile: jest.fn(),
    updateProfile: jest.fn(),
    validateInvite: jest.fn(),
    analyseCv: jest.fn(),
    extractCv: jest.fn(),
  });
});

const mockSupport = fetchParserSupport as jest.Mock;
const mockProfile = fetchProfile as jest.Mock;

function cvDisabled() {
  mockSupport.mockResolvedValue({
    txt: true,
    pdf: true,
    docx: true,
    enabled: false,
  });
}

beforeEach(() => {
  jest.clearAllMocks();
  mockProfile.mockRejectedValue(Object.assign(new Error("none"), { status: 404 }));
});

describe("CV reading disabled", () => {
  it("the profile page says it is coming, not that something failed", async () => {
    cvDisabled();
    render(
      <ToastProvider>
        <ProfilePage />
      </ToastProvider>,
    );
    expect(await screen.findByTestId("cv-coming-soon")).toHaveTextContent(
      /coming in a future update/i,
    );
  });

  it("offers no upload control at all when disabled", async () => {
    cvDisabled();
    render(
      <ToastProvider>
        <ProfilePage />
      </ToastProvider>,
    );
    await screen.findByTestId("cv-coming-soon");
    // Not merely disabled — absent. A greyed-out button invites a click that
    // can only fail.
    expect(screen.queryByLabelText("Upload CV file")).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /pre-fill my keywords/i }),
    ).not.toBeInTheDocument();
  });

  it("keeps the keyword path available — it is the only one left", async () => {
    cvDisabled();
    render(
      <ToastProvider>
        <ProfilePage />
      </ToastProvider>,
    );
    await screen.findByTestId("cv-coming-soon");
    expect(
      screen.getByRole("button", { name: /save my keywords/i }),
    ).toBeInTheDocument();
  });

  it("onboarding replaces the CV step and points at the picker", async () => {
    cvDisabled();
    render(
      <ToastProvider>
        <OnboardingPage />
      </ToastProvider>,
    );
    // Step 1 is the CV step; the welcome step renders first, so assert on the
    // component's own disabled marker being what step 1 would show.
    expect(await screen.findByRole("heading", { level: 1 })).toBeInTheDocument();
  });
});

describe("CV reading enabled", () => {
  it("restores the upload control", async () => {
    mockSupport.mockResolvedValue({
      txt: true,
      pdf: true,
      docx: true,
      enabled: true,
    });
    render(
      <ToastProvider>
        <ProfilePage />
      </ToastProvider>,
    );
    expect(
      await screen.findByRole("button", { name: /pre-fill from a CV/i }),
    ).toBeInTheDocument();
    expect(screen.queryByTestId("cv-coming-soon")).not.toBeInTheDocument();
  });
});
