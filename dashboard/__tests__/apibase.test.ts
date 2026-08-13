import { apiBase } from "@/lib/api";

describe("apiBase (L2: sidecar port robustness)", () => {
  const w = window as unknown as {
    __TAURI__?: unknown;
    __CIK_API_BASE__?: string;
  };

  afterEach(() => {
    delete w.__TAURI__;
    delete w.__CIK_API_BASE__;
  });

  it("web mode: uses NEXT_PUBLIC_API_URL or localhost:8000", () => {
    delete w.__TAURI__;
    expect(apiBase()).toBe(
      process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000",
    );
  });

  it("tauri mode: uses the base injected by the Rust shell", () => {
    w.__TAURI__ = {};
    w.__CIK_API_BASE__ = "http://127.0.0.1:8731";
    expect(apiBase()).toBe("http://127.0.0.1:8731");
  });

  it("tauri mode: falls back to 127.0.0.1:8000 when nothing was injected", () => {
    w.__TAURI__ = {};
    delete w.__CIK_API_BASE__;
    expect(apiBase()).toBe("http://127.0.0.1:8000");
  });
});
