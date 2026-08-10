import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import ApiKeysPage from "@/app/(app)/keys/page";
import { ToastProvider } from "@/components/ui/toast";
import {
  ApiError,
  createKey,
  fetchKeys,
  fetchKeyUsage,
  revokeKey,
  rotateKey,
} from "@/lib/api";

jest.mock("@/lib/api", () => ({
  ApiError: class ApiError extends Error {
    status: number;
    constructor(message: string, status: number) {
      super(message);
      this.status = status;
    }
  },
  getToken: jest.fn(() => "test-token"),
  createKey: jest.fn(),
  fetchKeys: jest.fn(),
  fetchKeyUsage: jest.fn(),
  revokeKey: jest.fn(),
  rotateKey: jest.fn(),
}));

jest.mock("@/components/AuthGate", () => ({
  __esModule: true,
  default: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

const mockCreateKey = createKey as jest.Mock;
const mockFetchKeys = fetchKeys as jest.Mock;
const mockFetchKeyUsage = fetchKeyUsage as jest.Mock;
const mockRevokeKey = revokeKey as jest.Mock;
const mockRotateKey = rotateKey as jest.Mock;

const KEYS = [
  {
    id: 1,
    name: "Production ML app",
    key_prefix: "cik_a1b2c3d4",
    scopes: ["read:matches", "write:bookmarks"],
    quota_limit: null,
    rate_limit: null,
    last_used_at: "2026-08-07T09:00:00Z",
    expires_at: null,
    revoked_at: null,
    created_at: "2026-08-01T09:00:00Z",
  },
  {
    id: 2,
    name: "Old CI key",
    key_prefix: "cik_deadbeef",
    scopes: ["read:profile"],
    quota_limit: null,
    rate_limit: null,
    last_used_at: null,
    expires_at: null,
    revoked_at: "2026-08-02T09:00:00Z",
    created_at: "2026-07-20T09:00:00Z",
  },
];

describe("ApiKeysPage", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    localStorage.clear();
  });

  function renderPage() {
    return render(
      <ToastProvider>
        <ApiKeysPage />
      </ToastProvider>,
    );
  }

  it("shows an empty state when there are no keys", async () => {
    mockFetchKeys.mockResolvedValue([]);
    renderPage();
    expect(
      await screen.findByText(
        "No API keys yet — create one to start integrating.",
      ),
    ).toBeInTheDocument();
  });

  it("lists active and revoked keys with scope badges", async () => {
    mockFetchKeys.mockResolvedValue(KEYS);
    renderPage();

    expect(await screen.findByText("Production ML app")).toBeInTheDocument();
    expect(screen.getByText("cik_a1b2c3d4…")).toBeInTheDocument();
    // revoked keys collapse under a separate heading
    expect(screen.getByText("Old CI key")).toBeInTheDocument();
    expect(screen.getByText("read:matches")).toBeInTheDocument();
    expect(screen.getByText("write:bookmarks")).toBeInTheDocument();
  });

  it("creates a key and shows the one-time raw key", async () => {
    mockFetchKeys.mockResolvedValue([]).mockResolvedValueOnce([]).mockResolvedValueOnce(KEYS);
    const user = userEvent.setup();
    mockCreateKey.mockResolvedValue({
      id: 3,
      name: "Demo",
      key_prefix: "cik_abcd1234",
      scopes: ["read:profile"],
      quota_limit: null,
      rate_limit: null,
      last_used_at: null,
      expires_at: null,
      revoked_at: null,
      created_at: "2026-08-08T09:00:00Z",
      raw_key: "cik_0123456789abcdef0123456789abcdef01234567",
    });
    renderPage();
    await user.click(screen.getByRole("button", { name: "Create API key" }));
    await screen.findByRole("dialog");
    await user.type(screen.getByLabelText("Name"), "Demo");
    await user.click(screen.getByRole("button", { name: "Create" }));

    await waitFor(() => expect(mockCreateKey).toHaveBeenCalledWith(
      expect.objectContaining({ name: "Demo" }),
    ));
    expect(
      await screen.findByText("Key created"),
    ).toBeInTheDocument();
    expect(
      screen.getByDisplayValue("cik_0123456789abcdef0123456789abcdef01234567"),
    ).toBeInTheDocument();
  });

  it("shows an error when the key message cannot be parsed", async () => {
    mockFetchKeys.mockRejectedValue(new ApiError("Downstream error", 500));
    renderPage();
    expect(await screen.findByText("Downstream error")).toBeInTheDocument();
  });

  it("revokes a key after confirmation", async () => {
    mockFetchKeys.mockResolvedValue(KEYS);
    mockRevokeKey.mockResolvedValue({ status: "revoked" });
    const user = userEvent.setup();
    renderPage();

    await user.click(
      await screen.findByRole("button", { name: "Revoke Production ML app" }),
    );
    screen.getByRole("dialog");
    await user.click(screen.getByRole("button", { name: "Revoke" }));

    await waitFor(() => expect(mockRevokeKey).toHaveBeenCalledWith(1));
  });

  it("rotates a key and reveals the new one-time key", async () => {
    mockFetchKeys.mockResolvedValue(KEYS);
    mockRotateKey.mockResolvedValue({
      id: 5,
      name: "Production ML app",
      key_prefix: "cik_newkey0",
      scopes: ["read:matches", "write:bookmarks"],
      quota_limit: null,
      rate_limit: null,
      last_used_at: null,
      expires_at: null,
      revoked_at: null,
      created_at: "2026-08-08T09:00:00Z",
      raw_key: "cik_ffffffffffffffffffffffffffffffffffffffff",
    });
    const user = userEvent.setup();
    renderPage();

    await user.click(
      await screen.findByRole("button", { name: "Rotate Production ML app" }),
    );
    await user.click(screen.getByRole("button", { name: "Rotate" }));

    await waitFor(() => expect(mockRotateKey).toHaveBeenCalledWith(1));
    expect(
      await screen.findByDisplayValue("cik_ffffffffffffffffffffffffffffffffffffffff"),
    ).toBeInTheDocument();
  });

  it("loads and plots per-day usage", async () => {
    mockFetchKeys.mockResolvedValue(KEYS);
    mockFetchKeyUsage.mockResolvedValue({
      key_id: 1,
      quota_limit: null,
      rate_limit: null,
      total: 2,
      items: [
        { date: "2026-08-07", requests: 120, rate_limited: 0 },
        { date: "2026-08-06", requests: 80, rate_limited: 2 },
      ],
    });
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole("button", { name: "Usage" }));

    expect(await screen.findByRole("img", { name: "Requests per day, last 14 days" }))
      .toBeInTheDocument();
    expect(mockFetchKeyUsage).toHaveBeenCalledWith(1, 14);
  });
});