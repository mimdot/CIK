import { jest } from "@jest/globals";

export const AUTHED_USER = { user_id: 1, email: "you@example.com" };

export class MockApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

/**
 * Base jest.mock("@/lib/api", ...) factory shared by suites that render
 * AuthGate. Keeps the httpOnly-session mock (fetchMe resolves to a session)
 * in one place so a schema change can't silently drift across 5 test files.
 */
export function mockAuthApi(extra: Record<string, unknown> = {}): object {
  return {
    ApiError: MockApiError,
    getToken: jest.fn(() => "test-token"),
    fetchMe: jest.fn(() => Promise.resolve(AUTHED_USER)),
    // LoginForm asks which sign-in mode this deployment uses before rendering
    // a form, so any suite that can fall through to it needs this stubbed.
    fetchAuthConfig: jest.fn(() =>
      Promise.resolve({ auth_mode: "password", invite_required: false }),
    ),
    logout: jest.fn(() => Promise.resolve()),
    ...extra,
  };
}