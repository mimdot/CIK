import { apiBase } from "@/lib/api";

describe("apiBase (L2: sidecar port robustness)", () => {
  const w = window as unknown as {
    __TAURI__?: unknown;
    __ASTRA_API_BASE__?: string;
  };

  afterEach(() => {
    delete w.__TAURI__;
    delete w.__ASTRA_API_BASE__;
  });

  it("web mode: uses NEXT_PUBLIC_API_URL or localhost:8000", () => {
    delete w.__ASTRA_API_BASE__;
    expect(apiBase()).toBe(
      process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000",
    );
  });

  it("desktop: uses the base injected by the Rust shell", () => {
    w.__ASTRA_API_BASE__ = "http://127.0.0.1:8731";
    expect(apiBase()).toBe("http://127.0.0.1:8731");
  });

  // The regression this file exists for. Tauri v2 only defines `window.__TAURI__`
  // when `app.withGlobalTauri` is set, and this app does not set it — so the
  // desktop app runs with the shell's base injected and NO `__TAURI__`. When
  // apiBase() gated on `__TAURI__`, that gate was always false, the injected
  // base was ignored, and every port the shell picked other than 8000 was
  // unreachable.
  it("desktop: honours the injected base even without window.__TAURI__", () => {
    delete w.__TAURI__;
    w.__ASTRA_API_BASE__ = "http://127.0.0.1:8731";
    expect(apiBase()).toBe("http://127.0.0.1:8731");
  });

  it("falls back to the web default when nothing was injected", () => {
    w.__TAURI__ = {};
    delete w.__ASTRA_API_BASE__;
    expect(apiBase()).toBe(
      process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000",
    );
  });
});
