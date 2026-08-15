import type { ReactNode } from "react";
import type { ConnectionState } from "../api/types";

export type PageId = "overview" | "characters" | "motions" | "animations" | "jobs";

interface AppShellProps {
  page: PageId;
  onPageChange: (page: PageId) => void;
  onSettings: () => void;
  connectionState: ConnectionState;
  hasToken: boolean;
  children: ReactNode;
}

const navItems: Array<{ id: PageId; label: string; hint: string }> = [
  { id: "overview", label: "概览", hint: "运行总览" },
  { id: "characters", label: "角色", hint: "GLB 资产" },
  { id: "motions", label: "动作", hint: "视频与动捕" },
  { id: "animations", label: "动画组合", hint: "重定向输出" },
  { id: "jobs", label: "任务", hint: "队列与日志" },
];

const connectionLabels: Record<ConnectionState, string> = {
  unknown: "未检测",
  checking: "检测中",
  connected: "后端在线",
  unauthorized: "需要鉴权",
  offline: "后端离线",
};

export function AppShell({
  page,
  onPageChange,
  onSettings,
  connectionState,
  hasToken,
  children,
}: AppShellProps): JSX.Element {
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand-lockup">
          <div className="brand-mark">N</div>
          <div>
            <div className="brand-name">NAQI</div>
            <div className="brand-subtitle">角色动作工作台</div>
          </div>
        </div>
        <nav className="main-nav" aria-label="主导航">
          {navItems.map((item) => (
            <button className={`nav-item ${page === item.id ? "active" : ""}`} key={item.id} onClick={() => onPageChange(item.id)} type="button">
              <span className="nav-label">{item.label}</span>
              <span className="nav-hint">{item.hint}</span>
            </button>
          ))}
        </nav>
        <div className="sidebar-footer">
          <button className="connection-button" onClick={onSettings} type="button">
            <span className={`connection-dot connection-${connectionState}`} />
            <span>{connectionLabels[connectionState]}</span>
            {!hasToken && <span className="connection-action">配置</span>}
          </button>
          <div className="small muted">前端独立版 · API 驱动</div>
        </div>
      </aside>
      <main className="main-content">{children}</main>
    </div>
  );
}
