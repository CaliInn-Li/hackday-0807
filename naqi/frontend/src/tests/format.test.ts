import { describe, expect, it } from "vitest";
import type { Job } from "../api/types";
import { formatBytes, formatDuration, jobCounts, shortHash } from "../lib/format";

describe("format helpers", () => {
  it("formats byte sizes and durations for asset metadata", () => {
    expect(formatBytes(1024 * 2)).toBe("2.0 KB");
    expect(formatBytes(1024 * 1024 * 3)).toBe("3.0 MB");
    expect(formatDuration(71)).toBe("1分 11秒");
    expect(formatDuration(undefined)).toBe("—");
  });

  it("shortens hashes without changing short values", () => {
    expect(shortHash("abc")).toBe("abc");
    expect(shortHash("1234567890abcdefghijklmno")).toBe("1234567890…jklmno");
  });

  it("counts known job states", () => {
    const jobs: Job[] = ["queued", "running", "succeeded", "succeeded", "failed", "unknown"].map((status, index) => ({
      id: String(index),
      status: status as Job["status"],
      logAvailable: false,
      metadata: {},
    }));
    expect(jobCounts(jobs)).toEqual({ queued: 1, running: 1, succeeded: 2, failed: 1, cancelled: 0 });
  });
});
