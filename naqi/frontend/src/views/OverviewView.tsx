import type { Job } from "../api/types";
import { formatDate, jobCounts } from "../lib/format";
import { EmptyState } from "../components/EmptyState";
import { PageHeader } from "../components/PageHeader";
import { StatusBadge } from "../components/StatusBadge";

interface OverviewViewProps {
  jobs: Job[];
  loading: boolean;
  onOpenJobs: () => void;
  onOpenSettings: () => void;
}

export function OverviewView({ jobs, loading, onOpenJobs, onOpenSettings }: OverviewViewProps): JSX.Element {
  const counts = jobCounts(jobs);
  const recent = jobs.slice(0, 8);
  return (
    <>
      <PageHeader
        eyebrow="WORKSPACE / OVERVIEW"
        title="资产与动作总览"
        description="从原始角色和视频动作，到可预览、可下载的动画 GLB。"
        actions={<button className="button button-subtle" onClick={onOpenSettings} type="button">连接设置</button>}
      />
      <section className="metric-grid">
        <Metric label="排队中" value={counts.queued} tone="queued" />
        <Metric label="运行中" value={counts.running} tone="running" />
        <Metric label="已完成" value={counts.succeeded} tone="succeeded" />
        <Metric label="失败" value={counts.failed} tone="failed" />
      </section>
      <section className="section-block">
        <div className="section-heading">
          <div>
            <div className="eyebrow">RECENT JOBS</div>
            <h2>最近任务</h2>
          </div>
          <button className="button button-subtle" onClick={onOpenJobs} type="button">查看全部</button>
        </div>
        {loading ? <div className="loading-line">正在读取任务…</div> : null}
        {!loading && recent.length === 0 ? (
          <EmptyState title="还没有任务" description="连接后端并上传角色或动作，任务会出现在这里。" />
        ) : (
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr><th>任务</th><th>状态</th><th>阶段</th><th>创建时间</th></tr>
              </thead>
              <tbody>
                {recent.map((job) => (
                  <tr key={job.id}>
                    <td><strong>{job.kind || "流水线任务"}</strong><div className="muted small">{job.id}</div></td>
                    <td><StatusBadge status={job.status} /></td>
                    <td>{job.stage || "—"}</td>
                    <td className="muted">{formatDate(job.createdAt)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </>
  );
}

function Metric({ label, value, tone }: { label: string; value: number; tone: string }): JSX.Element {
  return (
    <div className="metric-card">
      <div className={`metric-indicator indicator-${tone}`} />
      <div className="metric-label">{label}</div>
      <div className="metric-value">{value}</div>
    </div>
  );
}
