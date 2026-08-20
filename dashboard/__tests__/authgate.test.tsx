import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import AuthGate from "@/components/AuthGate";
import { ApiError, apiStartupError, fetchMe, login } from "@/lib/api";
import { isDesktop } from "@/lib/desktop";

jest.mock("@/lib/api", () => ({
  ApiError: class ApiError extends Error {
    status: number;
    constructor(message: string, status: number) {
      super(message);
      this.status = status;
    }
  },
  getToken: jest.fn(),
  login: jest.fn(),
  registerWithInvite: jest.fn(),
  signInWithAccessCode: jest.fn(),
  // LoginForm asks the API which sign-in form to render before showing one.
  fetchAuthConfig: jest.fn(() =>
    Promise.resolve({ auth_mode: "password", invite_required: false }),
  ),
  fetchMe: jest.fn(),
  apiBase: jest.fn(() => "http://127.0.0.1:8000"),
  apiStartupError: jest.fn(() => null),
}));

jest.mock("@/lib/desktop", () => ({
  isDesktop: jest.fn(() => false),
}));

const mockIsDesktop = isDesktop as jest.Mock;
const mockFetchMe = fetchMe as jest.Mock;
const mockStartupError = apiStartupError as jest.Mock;
const mockLogin = login as jest.Mock;

describe("AuthGate", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockStartupError.mockReturnValue(null);
    mockIsDesktop.mockReturnValue(false);
    delete (window as { __ASTRA_API_READY__?: boolean }).__ASTRA_API_READY__;
  });

  it("shows the app when the API confirms a session", async () => {
    mockFetchMe.mockResolvedValue({ user_id: 1, email: "you@example.com" });
    render(
      <AuthGate>
        <div>secret page</div>
      </AuthGate>,
    );
    expect(await screen.findByText("secret page")).toBeInTheDocument();
    expect(screen.queryByText("Sign in")).not.toBeInTheDocument();
  });

  it("shows the login form when there is no session (401)", async () => {
    mockFetchMe.mockRejectedValue(new ApiError("Not authenticated", 401));
    render(
      <AuthGate>
        <div>secret page</div>
      </AuthGate>,
    );
    expect(await screen.findByText("Sign in")).toBeInTheDocument();
    expect(screen.queryByText("secret page")).not.toBeInTheDocument();
  });

  it("switches to the app after a successful login", async () => {
    mockFetchMe.mockRejectedValue(new ApiError("Not authenticated", 401));
    const user = userEvent.setup();
    render(
      <AuthGate>
        <div>secret page</div>
      </AuthGate>,
    );
    await screen.findByText("Sign in");

    mockLogin.mockResolvedValue({ token: "t" });
    await user.type(screen.getByLabelText("Email"), "you@example.com");
    await user.type(screen.getByLabelText("Password"), "password123");
    await user.click(screen.getByRole("button", { name: "Log in" }));

    await waitFor(() => expect(mockLogin).toHaveBeenCalled());
    expect(await screen.findByText("secret page")).toBeInTheDocument();
    expect(screen.queryByText("Sign in")).not.toBeInTheDocument();
  });

  it("shows a network error with Retry instead of the login form when the API is unreachable", async () => {
    mockFetchMe.mockRejectedValue(
      new ApiError("Cannot reach the API server. Is it running?", 0),
    );
    render(
      <AuthGate>
        <div>secret page</div>
      </AuthGate>,
    );
    expect(
      await screen.findByText("Cannot reach the API server. Is it running?"),
    ).toBeInTheDocument();
    expect(screen.queryByText("Sign in")).not.toBeInTheDocument();

    mockFetchMe.mockResolvedValue({ user_id: 1, email: "you@example.com" });
    await userEvent.setup().click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByText("secret page")).toBeInTheDocument();
  });

  it("shows WHY the backend is down instead of asking if it is running", async () => {
    // The desktop shell is what starts the backend, so "is it running?" is the
    // one question the user cannot answer. When the shell knows the reason it
    // publishes it, and the gate must show that instead.
    mockFetchMe.mockRejectedValue(
      new ApiError("Cannot reach the API server. Is it running?", 0),
    );
    mockStartupError.mockReturnValue(
      "the backend process exited (exit status: 1) before it was ready.\n\n" +
        "Backend log (/home/me/.local/share/astra/api.log):\n" +
        "ModuleNotFoundError: No module named 'feedparser'",
    );
    render(
      <AuthGate>
        <div>secret page</div>
      </AuthGate>,
    );
    expect(
      await screen.findByText("The backend could not be started."),
    ).toBeInTheDocument();
    expect(screen.getByTestId("api-offline-reason")).toHaveTextContent(
      "No module named 'feedparser'",
    );
    expect(
      screen.queryByText("Cannot reach the API server. Is it running?"),
    ).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
  });
  it("waits instead of failing when the shell has not published its state yet", async () => {
    // The cold-start race that produced a sticky "Cannot reach the API server"
    // on every launch. The shell sets __ASTRA_API_READY__ from on_page_load,
    // whose eval is asynchronous, so the first fetchMe() can lose that race and
    // find the flag `undefined` -- neither true nor false. The old guard tested
    // `=== false`, so undefined fell through to the terminal offline screen,
    // which never retries; a backend that came up a second later never cleared
    // it. Inside the desktop shell, unknown means "not yet", not "down".
    mockIsDesktop.mockReturnValue(true);
    mockFetchMe.mockRejectedValue(
      new ApiError("Cannot reach the API server. Is it running?", 0),
    );
    render(
      <AuthGate>
        <div>secret page</div>
      </AuthGate>,
    );
    expect(await screen.findByTestId("api-starting")).toBeInTheDocument();
    expect(
      screen.queryByText("Cannot reach the API server. Is it running?"),
    ).not.toBeInTheDocument();
  });

  it("still reports an unreachable API immediately on the web build", async () => {
    // The same unknown state on the web is a real failure: nothing there ever
    // defines these globals, so treating unknown as "starting" would hang the
    // page on a spinner forever.
    mockIsDesktop.mockReturnValue(false);
    mockFetchMe.mockRejectedValue(
      new ApiError("Cannot reach the API server. Is it running?", 0),
    );
    render(
      <AuthGate>
        <div>secret page</div>
      </AuthGate>,
    );
    expect(
      await screen.findByText("Cannot reach the API server. Is it running?"),
    ).toBeInTheDocument();
    expect(screen.queryByTestId("api-starting")).not.toBeInTheDocument();
  });
});
