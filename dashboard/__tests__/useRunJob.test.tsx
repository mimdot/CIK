import { act, renderHook } from "@testing-library/react";
import { useRunJob } from "@/hooks/useRunJob";

jest.mock("@/lib/api", () => {
  class MockApiError extends Error {
    status: number;
    constructor(message: string, status: number) {
      super(message);
      this.status = status;
    }
  }
  return {
    ApiError: MockApiError,
    jobStatus: jest.fn(),
  };
});

import { ApiError, jobStatus } from "@/lib/api";

const mockJobStatus = jobStatus as jest.Mock;

const trigger = (runId: string) => () => Promise.resolve({ run_id: runId });

/** Flush pending microtasks without firing the 2s poll timer. */
const flush = async () => {
  await act(async () => {
    await jest.advanceTimersByTimeAsync(1);
  });
};

describe("useRunJob", () => {
  beforeEach(() => {
    jest.useFakeTimers();
    mockJobStatus.mockReset();
  });

  afterEach(() => {
    jest.useRealTimers();
  });

  it("starts open and busy, then completes with the record count", async () => {
    mockJobStatus.mockResolvedValue({
      run_id: "r1",
      status: "completed",
      records: 7,
    });
    const onCompleted = jest.fn();
    const { result } = renderHook(() => useRunJob(onCompleted));

    await act(async () => {
      await result.current.start(trigger("r1"));
    });
    await flush();

    expect(result.current.open).toBe(true);
    expect(result.current.busy).toBe(false);
    expect(result.current.status).toBe("completed");
    expect(result.current.records).toBe(7);
    expect(mockJobStatus).toHaveBeenCalledWith("r1");
    expect(onCompleted).toHaveBeenCalledWith(7);
  });

  it("transitions running -> completed across polls", async () => {
    mockJobStatus
      .mockResolvedValueOnce({ run_id: "r1", status: "running" })
      .mockResolvedValueOnce({ run_id: "r1", status: "completed", records: 3 });
    const onCompleted = jest.fn();
    const { result } = renderHook(() => useRunJob(onCompleted));

    await act(async () => {
      await result.current.start(trigger("r1"));
    });
    await flush();
    expect(result.current.status).toBe("running");
    expect(result.current.busy).toBe(true);

    await act(async () => {
      await jest.advanceTimersByTimeAsync(2000);
    });

    expect(result.current.status).toBe("completed");
    expect(result.current.records).toBe(3);
    expect(result.current.busy).toBe(false);
    expect(onCompleted).toHaveBeenCalledWith(3);
  });

  it("surfaces a failed trigger as an error without polling", async () => {
    const { result } = renderHook(() => useRunJob());

    await act(async () => {
      await result.current.start(() =>
        Promise.reject(new ApiError("boom", 500)),
      );
    });

    expect(result.current.open).toBe(true);
    expect(result.current.busy).toBe(false);
    expect(result.current.status).toBe("failed");
    expect(result.current.error).toBe("boom");
    expect(mockJobStatus).not.toHaveBeenCalled();
  });

  it("reports a failed job status and skips onCompleted", async () => {
    mockJobStatus.mockResolvedValue({
      run_id: "r1",
      status: "failed",
      error: "job exploded",
    });
    const onCompleted = jest.fn();
    const { result } = renderHook(() => useRunJob(onCompleted));

    await act(async () => {
      await result.current.start(trigger("r1"));
    });
    await flush();

    expect(result.current.status).toBe("failed");
    expect(result.current.error).toBe("job exploded");
    expect(result.current.busy).toBe(false);
    expect(onCompleted).not.toHaveBeenCalled();
  });

  it("keeps polling while the job reports running", async () => {
    mockJobStatus.mockResolvedValue({ run_id: "r1", status: "running" });
    const { result } = renderHook(() => useRunJob());

    await act(async () => {
      await result.current.start(trigger("r1"));
    });
    await flush();

    expect(mockJobStatus).toHaveBeenCalledTimes(1);
    await act(async () => {
      await jest.advanceTimersByTimeAsync(2000);
    });
    expect(mockJobStatus).toHaveBeenCalledTimes(2);
  });

  it("closes the dialog without resetting job state", async () => {
    mockJobStatus.mockResolvedValue({ run_id: "r1", status: "running" });
    const { result } = renderHook(() => useRunJob());

    await act(async () => {
      await result.current.start(trigger("r1"));
    });
    await flush();
    expect(result.current.open).toBe(true);

    act(() => result.current.close());

    expect(result.current.open).toBe(false);
  });

  it("resets stale results on a fresh start", async () => {
    mockJobStatus.mockResolvedValue({
      run_id: "r1",
      status: "completed",
      records: 7,
    });
    const { result } = renderHook(() => useRunJob());

    await act(async () => {
      await result.current.start(trigger("r1"));
    });
    await flush();
    expect(result.current.records).toBe(7);

    mockJobStatus.mockResolvedValue({ run_id: "r2", status: "running" });
    await act(async () => {
      await result.current.start(trigger("r2"));
    });
    await flush();

    expect(result.current.records).toBeNull();
    expect(result.current.status).toBe("running");
    expect(mockJobStatus).toHaveBeenLastCalledWith("r2");
  });
});
