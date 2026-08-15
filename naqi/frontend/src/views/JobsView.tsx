import * as React from "react";
import type { ApiClient } from "../api";
import type { Job } from "../api/types";
import { EmptyState } from "../components/EmptyState";
import { PageHeader } from "../components/PageHeader";
import { StatusBadge } from "../components/StatusBadge";
import { formatDate } from "../lib/format";

interface JobsViewProps {
  api: ApiClient;
  jobs: Job[];
  loading: boolean;
  unsupported: boolean;
  onRefresh: () => void;
}

export function JobsView({ api, jobs, loading, unsupported, onRefresh }: JobsViewProps): JSX.Element {
  return (
    <>
      <PageHeader eyebrow="OPERATIONS / JOBS" title="任务" description="查看排队、运行、失败与完成状态；日志和产物由后端按任务权限提供。" actions={<button className="button button-subtle" onClick={onRefresh} type="button">刷新</button>} />
      {unsupported ? <div className="notice notice-warning">当前后端版本暂不支持任务列表接口；任务状态会显示为空态。</div> : null}
      {loading ? <div className="loading-line">正在读取任务…</div> : null}
      {!loading && jobs.length === 0 ? <EmptyState title="暂无任务" description="当后端收到上传、动作识别或重定向请求后，任务会出现在这里。" /> : null}
      {!loading && jobs.length > 0 ? (
        <div className="table-wrap jobs-table-wrap">
          <table className="data-table">
            <thead><tr><th>任务 ID</th><th>类型</th><th>状态</th><th>当前阶段</th><th>时间</th><th>错误</th><th>日志 / 产物</th><th>入口</th></tr></thead>
            <tbody>
              {jobs.map((job) => <JobRow api={api} key={job.id} job={job} />)}
            </tbody>
          </table>
        </div>
      ) : null}
    </>
  );
}

function JobRow({ api, job }: { api: ApiClient; job: Job }): JSX.Element {
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  async function openDetail(): Promise<void> {
    setBusy(true);
    setError(null);
    try {
      const detail = await api.getJob(job.id);
      const text = JSON.stringify(detail.metadata, null, 2);
      const blob = new Blob([text], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `${job.id}.json`;
      anchor.click();
      URL.revokeObjectURL(url);
    } catch (caught: unknown) {
      setError(caught instanceof Error ? caught.message : "读取任务详情失败");
    } finally {
      setBusy(false);
    }
  }

  return <tr>
    <td><strong className="mono">{job.id}</strong></td>
    <td>{job.kind || "—"}</td>
    <td><StatusBadge status={job.status} /></td>
    <td>{job.stage || "—"}</td>
    <td className="muted"><div>{formatDate(job.createdAt)}</div><div className="small">{job.finishedAt ? `完成 ${formatDate(job.finishedAt)}` : job.startedAt ? `开始 ${formatDate(job.startedAt)}` : ""}</div></td>
    <td className="error-cell">{job.error || "—"}</td>
    <td className="small">{job.logAvailable ? "日志可用" : "无日志"}{job.artifactCount !== undefined ? ` · ${job.artifactCount} 个产物` : ""}</td>
    <td><button className="button button-subtle" disabled={busy} onClick={() => void openDetail()} type="button">{busy ? "读取中…" : "详情 / JSON"}</button>{error ? <div className="inline-error">{error}</div> : null}</td>
  </tr>;
}
