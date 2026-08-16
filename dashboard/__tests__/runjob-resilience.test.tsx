import { act, renderHook, waitFor } from "@testing-library/react";
import { useRunJob } from "@/hooks/useRunJob";
import { jobStatus } from "@/lib/api";

jest.mock("@/lib/api", () => ({
  ApiError: class MockApiError extends Error {
    status: number;
    constructor(message: string, status: number) {
      super(message);
      this.status = status;
    }
  },
  jobStatus: jest.fn(),
  cancelJob: jest.fn(),
}));

const mockStatus = jobStatus as jest.Mock;
const { ApiError: MockApiError } = jest.requireMock("@/lib/api") as {
  ApiError: new (m: string, s: number) => Error & { status: number };
};

/** What request() throws when the fetch itself never got an answer. */
function unreachable() {
  return new MockApiError("Cannot reach the API server. Is it running?", 0);
}

async function startRun(result: ReturnType<typeof renderHook<ReturnType<typeof useRunJob>, unknown>>) {
  await act(async () => {
    await result.result.current.start(() =>
      Promise.resolve({ run_id: "job-1" }),
    );
  });
}

beforeEach(() => {
  jest.clearAllMocks();
  jest.useFakeTimers();
});

afterEach(() => {
  jest.useRealTimers();
});

describe("a search survives losing contact with the backend", () => {
  it("keeps polling after a blip instead of ending the run", async () => {
    // One unreachable poll, then the backend is back and the job completes.
    mockStatus
      .mockRejectedValueOnce(unreachable())
      .mockResolvedValue({ status: "completed", records: 12 });

    const hook = renderHook(() => useRunJob());
    await startRun(hook);

    // The blip must NOT be reported as a failed run...
    await waitFor(() => expect(hook.result.current.reconnecting).toBe(true));
    expect(hook.result.current.busy).toBe(true);
    expect(hook.result.current.status).not.toBe("failed");

    // ...and the next poll finds the job finished normally.
    await act(async () => {
      jest.advanceTimersByTime(5000);
    });
    await waitFor(() => expect(hook.result.current.status).toBe("completed"));
    expect(hook.result.current.records).toBe(12);
    expect(hook.result.current.reconnecting).toBe(false);
  });

  it("clears the reconnecting flag once contact is restored", async () => {
    mockStatus
      .mockRejectedValueOnce(unreachable())
      .mockResolvedValue({ status: "running" });

    const hook = renderHook(() => useRunJob());
    await startRun(hook);
    await waitFor(() => expect(hook.result.current.reconnecting).toBe(true));

    await act(async () => {
      jest.advanceTimersByTime(5000);
    });
    await waitFor(() => expect(hook.result.current.reconnecting).toBe(false));
    expect(hook.result.current.busy).toBe(true);
  });

  it("gives up honestly after sustained silence", async () => {
    mockStatus.mockRejectedValue(unreachable());

    const hook = renderHook(() => useRunJob());
    await startRun(hook);

    // Five consecutive failures at a widened interval.
    for (let i = 0; i < 6; i += 1) {
      await act(async () => {
        jest.advanceTimersByTime(5000);
      });
    }

    await waitFor(() => expect(hook.result.current.busy).toBe(false));
    expect(hook.result.current.error).toMatch(/Cannot reach the API server/);
  });

  it("does not retry a real error — only unreachability", async () => {
    // A 404 means this job id is genuinely unknown; retrying is pointless.
    mockStatus.mockRejectedValue(new MockApiError("Job not found", 404));

    const hook = renderHook(() => useRunJob());
    await startRun(hook);

    await waitFor(() => expect(hook.result.current.busy).toBe(false));
    expect(hook.result.current.error).toBe("Job not found");
    expect(hook.result.current.reconnecting).toBe(false);
    expect(mockStatus).toHaveBeenCalledTimes(1);
  });
});
