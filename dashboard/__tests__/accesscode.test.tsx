import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import LoginForm from "@/components/LoginForm";
import { fetchAuthConfig, login, signInWithAccessCode } from "@/lib/api";

jest.mock("@/lib/api", () => ({
  ApiError: class MockApiError extends Error {
    status: number;
    constructor(message: string, status: number) {
      super(message);
      this.status = status;
    }
  },
  login: jest.fn(() => Promise.resolve("t")),
  registerWithInvite: jest.fn(() => Promise.resolve()),
  signInWithAccessCode: jest.fn(() => Promise.resolve("t")),
  fetchAuthConfig: jest.fn(),
}));

const mockConfig = fetchAuthConfig as jest.Mock;
const mockAccess = signInWithAccessCode as jest.Mock;
const mockLogin = login as jest.Mock;

function inMode(auth_mode: "access_code" | "password") {
  mockConfig.mockResolvedValue({ auth_mode, invite_required: false });
}

beforeEach(() => {
  jest.clearAllMocks();
  mockAccess.mockResolvedValue("t");
});

describe("sign-in form follows the API's configured mode", () => {
  it("access-code mode asks for email and code, and never for a password", async () => {
    inMode("access_code");
    render(<LoginForm />);

    expect(await screen.findByLabelText("Access code")).toBeInTheDocument();
    expect(screen.getByLabelText("Email")).toBeInTheDocument();
    // The whole point: there is no password field to fill in.
    expect(screen.queryByLabelText("Password")).not.toBeInTheDocument();
  });

  it("password mode keeps the existing email + password form", async () => {
    inMode("password");
    render(<LoginForm />);

    expect(await screen.findByLabelText("Password")).toBeInTheDocument();
    expect(screen.queryByLabelText("Access code")).not.toBeInTheDocument();
  });

  it("never flashes the password field before the mode is known", () => {
    // A promise that stays pending: the form must show neither form yet.
    mockConfig.mockReturnValue(new Promise(() => {}));
    render(<LoginForm />);
    expect(screen.queryByLabelText("Password")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Access code")).not.toBeInTheDocument();
  });

  it("falls back to the password form if the mode cannot be fetched", async () => {
    mockConfig.mockRejectedValue(new Error("offline"));
    render(<LoginForm />);
    expect(await screen.findByLabelText("Password")).toBeInTheDocument();
  });
});

describe("access-code submission", () => {
  it("sends the email and code, trimmed", async () => {
    inMode("access_code");
    render(<LoginForm />);
    await screen.findByLabelText("Access code");

    await userEvent.type(screen.getByLabelText("Email"), "me@example.com");
    await userEvent.type(screen.getByLabelText("Access code"), " 1819 ");
    await userEvent.click(screen.getByRole("button", { name: "Continue" }));

    await waitFor(() =>
      expect(mockAccess).toHaveBeenCalledWith("me@example.com", "1819"),
    );
    expect(mockLogin).not.toHaveBeenCalled();
  });

  it("calls onAuth once accepted", async () => {
    inMode("access_code");
    const onAuth = jest.fn();
    render(<LoginForm onAuth={onAuth} />);
    await screen.findByLabelText("Access code");

    await userEvent.type(screen.getByLabelText("Email"), "me@example.com");
    await userEvent.type(screen.getByLabelText("Access code"), "1819");
    await userEvent.click(screen.getByRole("button", { name: "Continue" }));

    await waitFor(() => expect(onAuth).toHaveBeenCalled());
  });

  it("shows the API's reason when the code is wrong", async () => {
    inMode("access_code");
    const { ApiError } = jest.requireMock("@/lib/api") as {
      ApiError: new (m: string, s: number) => Error;
    };
    mockAccess.mockRejectedValue(
      new ApiError("That access code is not right", 401),
    );
    render(<LoginForm />);
    await screen.findByLabelText("Access code");

    await userEvent.type(screen.getByLabelText("Email"), "me@example.com");
    await userEvent.type(screen.getByLabelText("Access code"), "0000");
    await userEvent.click(screen.getByRole("button", { name: "Continue" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "That access code is not right",
    );
  });
});
