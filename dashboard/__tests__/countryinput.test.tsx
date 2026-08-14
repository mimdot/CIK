import { useState } from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { CountryInput } from "@/components/CountryInput";
import { normalizeName } from "@/lib/api";

jest.mock("@/lib/api", () => ({ normalizeName: jest.fn() }));
const mockNormalize = normalizeName as jest.Mock;

function Harness({ initial = "" }: { initial?: string }) {
  const [value, setValue] = useState(initial);
  return <CountryInput id="c" value={value} onChange={setValue} />;
}

/**
 * Phase 2D on the INPUT side. It suggests rather than rewrites: silently
 * replacing what someone typed is worse than a wrong search, because they
 * would never know why the results changed.
 */
describe("CountryInput — auto-correct (2D)", () => {
  beforeEach(() => jest.clearAllMocks());

  it("offers the canonical form for a misspelling", async () => {
    mockNormalize.mockResolvedValue({
      country: { input: "Germny", value: "Germany", how: "fuzzy",
                 score: 0.923, corrected: true },
    });
    const user = userEvent.setup();
    render(<Harness />);
    await user.type(screen.getByLabelText("Country"), "Germny");

    const suggestion = await screen.findByTestId("country-suggestion", {}, {
      timeout: 3000,
    });
    expect(suggestion).toHaveTextContent("Did you mean Germany?");
    // Not rewritten behind the user's back.
    expect(screen.getByLabelText("Country")).toHaveValue("Germny");
  });

  it("applies the suggestion only when the user clicks it", async () => {
    mockNormalize.mockResolvedValue({
      country: { input: "UK", value: "United Kingdom", how: "code",
                 score: 1, corrected: true },
    });
    const user = userEvent.setup();
    render(<Harness />);
    await user.type(screen.getByLabelText("Country"), "UK");

    await user.click(
      await screen.findByRole("button", { name: "United Kingdom" }, {
        timeout: 3000,
      }),
    );
    expect(screen.getByLabelText("Country")).toHaveValue("United Kingdom");
  });

  it("says nothing when the input is already canonical", async () => {
    mockNormalize.mockResolvedValue({
      country: { input: "Germany", value: "Germany", how: "exact",
                 score: 1, corrected: false },
    });
    const user = userEvent.setup();
    render(<Harness />);
    await user.type(screen.getByLabelText("Country"), "Germany");

    await waitFor(() => expect(mockNormalize).toHaveBeenCalled());
    expect(screen.queryByTestId("country-suggestion")).not.toBeInTheDocument();
    expect(screen.queryByTestId("country-unknown")).not.toBeInTheDocument();
  });

  it("warns when the country is not recognised at all", async () => {
    mockNormalize.mockResolvedValue({ country: null });
    const user = userEvent.setup();
    render(<Harness />);
    await user.type(screen.getByLabelText("Country"), "Freedonia");

    expect(
      await screen.findByTestId("country-unknown", {}, { timeout: 3000 }),
    ).toHaveTextContent(/not a country we recognise/);
  });

  it("does not query on a single character", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await user.type(screen.getByLabelText("Country"), "G");
    await new Promise((r) => setTimeout(r, 600));
    expect(mockNormalize).not.toHaveBeenCalled();
  });

  it("stays usable when the lookup fails", async () => {
    mockNormalize.mockRejectedValue(new Error("offline"));
    const user = userEvent.setup();
    render(<Harness />);
    await user.type(screen.getByLabelText("Country"), "Germany");

    await waitFor(() => expect(mockNormalize).toHaveBeenCalled());
    expect(screen.getByLabelText("Country")).toHaveValue("Germany");
    expect(screen.queryByTestId("country-suggestion")).not.toBeInTheDocument();
  });
});
