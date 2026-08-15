import type { Job, JobCounts, JobStatus } from "../api/types";

export function formatBytes(value?: number): string {
  if (value === undefined || !Number.isFinite(value)) return "—";
  if (value < 1024) return `${Math.round(value)} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let size = value;
  let unitIndex = -1;
  while (size >= 1024 && unitIndex < units.length - 1) {
    size /= 1024;
    unitIndex += 1;
  }
  return `${size.toFixed(size >= 10 ? 0 : 1)} ${units[unitIndex]}`;
}

export function formatDuration(value?: number): string {
  if (value === undefined || !Number.isFinite(value)) return "—";
  const totalSeconds = Math.max(0, Math.round(value));
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return minutes ? `${minutes}分 ${String(seconds).padStart(2, "0")}秒` : `${seconds}秒`;
}

export function formatNumber(value?: number, suffix = ""): string {
  if (value === undefined || !Number.isFinite(value)) return "—";
  return `${new Intl.NumberFormat("zh-CN").format(value)}${suffix}`;
}

export function formatDate(value?: string): string {
  if (!value) return "—";
  const timestamp = Date.parse(value);
  if (!Number.isFinite(timestamp)) return value;
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(timestamp);
}

export function shortHash(value?: string): string {
  if (!value) return "—";
  return value.length > 18 ? `${value.slice(0, 10)}…${value.slice(-6)}` : value;
}

export function jobCounts(jobs: Job[]): JobCounts {
  const counts: JobCounts = { queued: 0, running: 0, succeeded: 0, failed: 0, cancelled: 0 };
  for (const job of jobs) {
    if (job.status in counts) counts[job.status as Exclude<JobStatus, "unknown">] += 1;
  }
  return counts;
}

export function sortNewestFirst<T extends { createdAt?: string }>(items: T[]): T[] {
  return [...items].sort((left, right) => {
    const leftTime = left.createdAt ? Date.parse(left.createdAt) : 0;
    const rightTime = right.createdAt ? Date.parse(right.createdAt) : 0;
    return rightTime - leftTime;
  });
}
