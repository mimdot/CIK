import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import AuthGate from "@/components/AuthGate";
import { ApiError, fetchMe, login } from "@/lib/api";

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
  fetchMe: jest.fn(),
}));

const mockFetchMe = fetchMe as jest.Mock;
const mockLogin = login as jest.Mock;

describe("AuthGate", () => {
  beforeEach(() => {
    jest.clearAllMocks();
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
});