import { ApiError, login } from "@/lib/api";

describe("API error message normalization", () => {
  const originalFetch = global.fetch;

  afterEach(() => {
    global.fetch = originalFetch;
    jest.resetModules();
  });

  function mockFetchOnce(status: number, body: unknown) {
    global.fetch = jest.fn().mockResolvedValue({
      ok: status >= 200 && status < 300,
      status,
      text: async () => JSON.stringify(body),
    }) as jest.Mock;
  }

  it("surfaces a string detail verbatim", async () => {
    mockFetchOnce(401, { detail: "Invalid email or password" });
    await expect(login("a@b.com", "whatever123")).rejects.toMatchObject({
      status: 401,
      message: "Invalid email or password",
    });
  });

  it("joins FastAPI validation errors into a readable message, not [object Object]", async () => {
    mockFetchOnce(422, {
      detail: [
        {
          type: "value_error",
          loc: ["body", "password"],
          msg: "Value error, Password must contain at least one uppercase letter",
        },
        {
          type: "value_error",
          loc: ["body", "password"],
          msg: "Value error, Password must contain at least one digit",
        },
      ],
    });
    await expect(login("a@b.com", "weakpass")).rejects.toBeInstanceOf(ApiError);
    await expect(login("a@b.com", "weakpass")).rejects.toMatchObject({
      status: 422,
      message:
        "Value error, Password must contain at least one uppercase letter; Value error, Password must contain at least one digit",
    });
  });

  it("falls back to a generic message when there is no detail", async () => {
    mockFetchOnce(500, { error: "boom" });
    await expect(login("a@b.com", "whatever123")).rejects.toMatchObject({
      status: 500,
      message: "Request failed (500)",
    });
  });
});