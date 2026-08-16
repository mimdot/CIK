import * as React from "react";
import { render, screen, fireEvent } from "@testing-library/react";
import LandingPage from "@/app/(public)/landing/page";
import PrivacyPage from "@/app/(public)/privacy/page";
import TermsPage from "@/app/(public)/terms/page";
import AboutPage from "@/app/(public)/about/page";
import CookieBanner from "@/components/CookieBanner";

// The public pages render plain static markup — no API calls, no auth.
jest.mock("next/link", () => ({
  __esModule: true,
  default: ({ href, children, ...props }: Record<string, unknown>) =>
    React.createElement(
      "a",
      { href, ...props },
      children as React.ReactNode,
    ),
}));

describe("landing", () => {
  it("shows the value proposition and CTA to the app", () => {
    render(<LandingPage />);
    expect(
      screen.getByRole("heading", {
        name: /your next research position, matched to you/i,
      }),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /get started/i })).toHaveAttribute(
      "href",
      "/",
    );
    expect(screen.getByRole("link", { name: /how it works/i })).toBeInTheDocument();
  });

  it("describes the three steps", () => {
    render(<LandingPage />);
    expect(screen.getAllByText(/^Step \d of 3$/)).toHaveLength(3);
    expect(screen.getByText(/build your profile/i)).toBeInTheDocument();
    expect(screen.getByText(/find matches/i)).toBeInTheDocument();
    expect(screen.getByText(/apply with confidence/i)).toBeInTheDocument();
  });

  it("mentions the privacy line", () => {
    render(<LandingPage />);
    expect(screen.getByText(/your data stays yours/i)).toBeInTheDocument();
  });
});

describe("privacy", () => {
  it("describes collection, cookies, and rights", () => {
    render(<PrivacyPage />);
    expect(
      screen.getByRole("heading", { name: /privacy policy/i }),
    ).toBeInTheDocument();
    expect(screen.getByText(/functional cookies/i)).toBeInTheDocument();
    expect(screen.getByText(/erase your account/i)).toBeInTheDocument();
  });
});

describe("terms", () => {
  it("describes beta access and limits", () => {
    render(<TermsPage />);
    expect(
      screen.getByRole("heading", { name: /terms of service/i }),
    ).toBeInTheDocument();
    expect(screen.getByText(/private beta by invitation/i)).toBeInTheDocument();
  });
});

describe("about", () => {
  it("shows the FAQ", () => {
    render(<AboutPage />);
    expect(
      screen.getByRole("heading", { name: /about astra/i }),
    ).toBeInTheDocument();
    expect(screen.getByText(/what is astra/i)).toBeInTheDocument();
  });
});

describe("cookie banner", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("acknowledges via accept and remembers choice", () => {
    render(<CookieBanner />);
    const accept = screen.getByRole("button", { name: /accept/i });
    fireEvent.click(accept);
    expect(localStorage.getItem("cik_cookie_consent")).toBe("accepted");
    expect(
      screen.queryByRole("button", { name: /accept/i }),
    ).not.toBeInTheDocument();
  });

  it("does not reappear when already accepted", () => {
    localStorage.setItem("cik_cookie_consent", "accepted");
    render(<CookieBanner />);
    expect(
      screen.queryByRole("button", { name: /accept/i }),
    ).not.toBeInTheDocument();
  });
});