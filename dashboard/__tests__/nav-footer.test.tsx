import { render, screen, waitFor } from "@testing-library/react";
import Nav from "@/components/Nav";
import { SiteFooter } from "@/components/SiteFooter";
import { fetchMe } from "@/lib/api";

jest.mock("@/lib/api", () => ({ fetchMe: jest.fn() }));
jest.mock("next/navigation", () => ({ usePathname: () => "/" }));

const mockFetchMe = fetchMe as jest.Mock;

describe("Nav — operator pages are hidden from ordinary users (Phase 5C)", () => {
  beforeEach(() => jest.clearAllMocks());

  it("hides Admin and API Keys from a normal user", async () => {
    mockFetchMe.mockResolvedValue({
      user_id: 1, email: "a@b.c", role: "user",
    });
    render(<Nav />);

    // The features every user needs stay visible...
    expect(await screen.findByText("Opportunities")).toBeInTheDocument();
    expect(screen.getByText("Supervisors")).toBeInTheDocument();
    expect(screen.getByText("Settings")).toBeInTheDocument();
    // ...operator tooling does not. The backend already answers 403 on those
    // routes; this stops the app advertising them at all.
    await waitFor(() => {
      expect(screen.queryByText("Admin")).not.toBeInTheDocument();
      expect(screen.queryByText("API Keys")).not.toBeInTheDocument();
    });
  });

  it("shows them to an admin", async () => {
    mockFetchMe.mockResolvedValue({
      user_id: 1, email: "a@b.c", role: "admin",
    });
    render(<Nav />);
    expect(await screen.findByText("Admin")).toBeInTheDocument();
    expect(screen.getByText("API Keys")).toBeInTheDocument();
  });

  it("hides them when the role cannot be determined", async () => {
    mockFetchMe.mockRejectedValue(new Error("offline"));
    render(<Nav />);
    expect(await screen.findByText("Opportunities")).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.queryByText("Admin")).not.toBeInTheDocument(),
    );
  });
});

describe("SiteFooter — contact links (Phase 6D)", () => {
  it("links the project's GitHub and a mailto address", () => {
    render(<SiteFooter />);
    expect(screen.getByRole("link", { name: "GitHub" })).toHaveAttribute(
      "href",
      "https://github.com/mimdot",
    );
    expect(
      screen.getByRole("link", { name: "mr.nasirzadeh@live.com" }),
    ).toHaveAttribute("href", "mailto:mr.nasirzadeh@live.com");
  });

  it("opens GitHub safely in a new tab", () => {
    render(<SiteFooter />);
    const github = screen.getByRole("link", { name: "GitHub" });
    expect(github).toHaveAttribute("target", "_blank");
    expect(github).toHaveAttribute("rel", expect.stringContaining("noopener"));
  });
});
