import type { AssetStatus, JobStatus } from "../api/types";

type Status = AssetStatus | JobStatus;

const labels: Record<Status, string> = {
  ready: "就绪",
  processing: "处理中",
  queued: "排队中",
  running: "运行中",
  succeeded: "已完成",
  failed: "失败",
  cancelled: "已取消",
  unknown: "未知",
};

export function StatusBadge({ status }: { status: Status }): JSX.Element {
  return <span className={`status-badge status-${status}`}>{labels[status]}</span>;
}
