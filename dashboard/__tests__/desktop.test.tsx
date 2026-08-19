import { render } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import ExternalLinks from "@/components/ExternalLinks";
import {
  isDesktop,
  isExternalHref,
  openExternal,
  saveTextFile,
} from "@/lib/desktop";

// The Tauri plugins are ESM-only and have no meaning outside the shell, so they
// are mocked here as the shell's side of the contract: what the frontend is
// expected to call, and with what.
const openUrl = jest.fn(() => Promise.resolve());
const revealItemInDir = jest.fn(() => Promise.resolve());
const openPath = jest.fn(() => Promise.resolve());
const save = jest.fn<Promise<string | null>, unknown[]>(() =>
  Promise.resolve("/home/u/Documents/supervisors.csv"),
);
const invoke = jest.fn((_cmd: string, args: { path: string }) =>
  Promise.resolve(args.path),
);

jest.mock(
  "@tauri-apps/plugin-opener",
  () => ({
    openUrl: (...a: unknown[]) => openUrl(...(a as [])),
    revealItemInDir: (...a: unknown[]) => revealItemInDir(...(a as [])),
    openPath: (...a: unknown[]) => openPath(...(a as [])),
  }),
  { virtual: true },
);
jest.mock(
  "@tauri-apps/plugin-dialog",
  () => ({ save: (...a: unknown[]) => save(...a) }),
  { virtual: true },
);
jest.mock(
  "@tauri-apps/api/core",
  () => ({ invoke: (...a: unknown[]) => invoke(...(a as [string, { path: string }])) }),
  { virtual: true },
);

const w = window as unknown as { __ASTRA_DESKTOP__?: boolean };

function asDesktop() {
  w.__ASTRA_DESKTOP__ = true;
}

beforeEach(() => {
  jest.clearAllMocks();
  delete w.__ASTRA_DESKTOP__;
});

describe("isExternalHref", () => {
  it.each(["https://x.com/a", "http://x.com", "mailto:a@b.c", "tel:+123"])(
    "treats %s as external",
    (href) => expect(isExternalHref(href)).toBe(true),
  );

  it.each(["/opportunities", "#top", "?q=1", "supervisors"])(
    "treats %s as in-app",
    (href) => expect(isExternalHref(href)).toBe(false),
  );
});

describe("isDesktop", () => {
  it("is false in a browser", () => {
    expect(isDesktop()).toBe(false);
  });

  it("is true once the shell has marked the webview", () => {
    asDesktop();
    expect(isDesktop()).toBe(true);
  });
});

describe("openExternal", () => {
  it("desktop: hands the URL to the system browser", async () => {
    asDesktop();
    await openExternal("https://example.org/post/1");
    expect(openUrl).toHaveBeenCalledWith("https://example.org/post/1");
  });

  it("web: opens a new tab instead", async () => {
    const spy = jest.spyOn(window, "open").mockImplementation(() => null);
    await openExternal("https://example.org");
    expect(spy).toHaveBeenCalled();
    expect(openUrl).not.toHaveBeenCalled();
    spy.mockRestore();
  });
});

describe("saveTextFile", () => {
  it("desktop: asks where to save, then writes there", async () => {
    asDesktop();
    const result = await saveTextFile({
      suggestedName: "supervisors.csv",
      contents: "a,b\n1,2",
      mime: "text/csv",
    });
    expect(save).toHaveBeenCalled();
    expect(invoke).toHaveBeenCalledWith("write_text_file", {
      path: "/home/u/Documents/supervisors.csv",
      contents: "a,b\n1,2",
    });
    expect(result).toEqual({
      path: "/home/u/Documents/supervisors.csv",
      revealable: true,
    });
  });

  it("desktop: a cancelled dialog writes nothing and is not an error", async () => {
    asDesktop();
    save.mockResolvedValueOnce(null);
    const result = await saveTextFile({
      suggestedName: "x.csv",
      contents: "x",
      mime: "text/csv",
    });
    expect(result).toBeNull();
    expect(invoke).not.toHaveBeenCalled();
  });

  it("desktop: a failed write surfaces the real error", async () => {
    asDesktop();
    invoke.mockRejectedValueOnce(new Error("cannot write /ro/x.csv: read-only"));
    await expect(
      saveTextFile({ suggestedName: "x.csv", contents: "x", mime: "text/csv" }),
    ).rejects.toThrow("read-only");
  });
});

describe("ExternalLinks interceptor", () => {
  it("sends an external anchor to the system browser", async () => {
    asDesktop();
    render(
      <>
        <ExternalLinks />
        <a href="https://example.org/posting">Posting</a>
      </>,
    );
    await userEvent.click(document.querySelector("a")!);
    expect(openUrl).toHaveBeenCalledWith("https://example.org/posting");
  });

  it("sends a mailto anchor to the mail client", async () => {
    asDesktop();
    render(
      <>
        <ExternalLinks />
        <a href="mailto:a@b.c">Mail</a>
      </>,
    );
    await userEvent.click(document.querySelector("a")!);
    expect(openUrl).toHaveBeenCalledWith("mailto:a@b.c");
  });

  it("catches anchors nested inside other markup", async () => {
    asDesktop();
    render(
      <>
        <ExternalLinks />
        <a href="https://example.org/x">
          <span>deep</span>
        </a>
      </>,
    );
    await userEvent.click(document.querySelector("span")!);
    expect(openUrl).toHaveBeenCalledWith("https://example.org/x");
  });

  it("leaves in-app routes to the router", async () => {
    asDesktop();
    render(
      <>
        <ExternalLinks />
        <a href="/opportunities">Opportunities</a>
      </>,
    );
    await userEvent.click(document.querySelector("a")!);
    expect(openUrl).not.toHaveBeenCalled();
  });

  it("does nothing on the web build", async () => {
    render(
      <>
        <ExternalLinks />
        <a href="https://example.org">Site</a>
      </>,
    );
    await userEvent.click(document.querySelector("a")!);
    expect(openUrl).not.toHaveBeenCalled();
  });
});
