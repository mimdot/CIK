import { useState } from "react";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { KeywordPicker } from "@/components/KeywordPicker";
import { fetchField } from "@/lib/api";

jest.mock("@/lib/api", () => ({ fetchField: jest.fn() }));
const mockFetchField = fetchField as jest.Mock;

const CHEMISTRY = {
  name: "chemistry",
  label: "Chemistry",
  description: "",
  core_anchors: [],
  search_terms: [],
  sources: { dedicated: [], general: [], has_dedicated: false },
  subfields: [
    {
      id: "organic",
      label: "Organic Chemistry",
      keyword_count: 3,
      keywords: ["organic chemistry", "total synthesis", "organocatalysis"],
    },
    {
      id: "catalysis",
      label: "Catalysis",
      keyword_count: 2,
      keywords: ["heterogeneous catalysis", "photocatalysis"],
    },
  ],
};

/**
 * The keyword picker is the PRIMARY way a user describes their research —
 * it replaces the dependency on CV parsing and on a paid AI service.
 */
function Harness({ initial = [] as string[] }) {
  const [selected, setSelected] = useState<string[]>(initial);
  return (
    <KeywordPicker field="chemistry" selected={selected} onChange={setSelected} />
  );
}

describe("KeywordPicker", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockFetchField.mockResolvedValue(CHEMISTRY);
  });

  it("keeps groups collapsed so the interface never gets cluttered", async () => {
    render(<Harness />);
    // Group headers are visible; the keywords inside are not, until asked for.
    expect(await screen.findByText("Organic Chemistry")).toBeInTheDocument();
    expect(screen.getByText("Catalysis")).toBeInTheDocument();
    expect(screen.queryByLabelText("total synthesis")).not.toBeInTheDocument();
  });

  it("expands a subfield and selects a keyword", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await user.click(await screen.findByRole("button", { name: /Organic Chemistry/ }));
    await user.click(await screen.findByLabelText("total synthesis"));

    const chips = await screen.findByTestId("keyword-chips");
    expect(within(chips).getByText("total synthesis")).toBeInTheDocument();
    expect(screen.getByText("Your keywords (1)")).toBeInTheDocument();
  });

  it("selects and clears every keyword in one subfield", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    const row = (await screen.findByText("Catalysis")).closest("li")!;
    await user.click(within(row).getByRole("button", { name: "All" }));

    expect(screen.getByText("Your keywords (2)")).toBeInTheDocument();
    await user.click(within(row).getByRole("button", { name: "None" }));
    expect(screen.getByText("Your keywords (0)")).toBeInTheDocument();
  });

  it("removes a keyword by clicking its chip", async () => {
    const user = userEvent.setup();
    render(<Harness initial={["photocatalysis"]} />);
    const chips = await screen.findByTestId("keyword-chips");
    await user.click(within(chips).getByText("photocatalysis"));
    expect(screen.queryByTestId("keyword-chips")).not.toBeInTheDocument();
  });

  it("searches across groups and auto-expands the matches", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await screen.findByText("Organic Chemistry");
    await user.type(screen.getByLabelText("Search keywords"), "catalys");

    // A hit is never hidden behind a collapsed header.
    expect(await screen.findByLabelText("organocatalysis")).toBeInTheDocument();
    expect(screen.getByLabelText("photocatalysis")).toBeInTheDocument();
    expect(screen.queryByLabelText("total synthesis")).not.toBeInTheDocument();
  });

  it("lets the user add a term that is not in the list", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await screen.findByText("Organic Chemistry");
    await user.type(screen.getByLabelText("Add your own"), "click chemistry");
    await user.click(screen.getByRole("button", { name: "Add" }));

    const chips = await screen.findByTestId("keyword-chips");
    expect(within(chips).getByText("click chemistry")).toBeInTheDocument();
  });

  it("clears the whole selection", async () => {
    const user = userEvent.setup();
    render(<Harness initial={["organic chemistry", "photocatalysis"]} />);
    await user.click(await screen.findByRole("button", { name: "Clear all" }));
    expect(screen.getByText("Your keywords (0)")).toBeInTheDocument();
  });

  it("asks for a field first when none is chosen", async () => {
    render(<KeywordPicker field="" selected={[]} onChange={() => {}} />);
    expect(
      screen.getByText(/Choose a research field first/),
    ).toBeInTheDocument();
    expect(mockFetchField).not.toHaveBeenCalled();
  });

  it("reports a load failure instead of showing an empty list", async () => {
    mockFetchField.mockRejectedValue(new Error("boom"));
    render(<Harness />);
    await waitFor(() =>
      expect(
        screen.getByText(/Could not load the keyword list/),
      ).toBeInTheDocument(),
    );
  });
});
