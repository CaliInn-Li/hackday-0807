import { useEffect, useState } from "react";
import type { ApiClient } from "../api";
import type { ConnectionState } from "../api/types";

interface ConnectionPanelProps {
  open: boolean;
  api: ApiClient;
  baseUrl: string;
  hasToken: boolean;
  connectionState: ConnectionState;
  connectionMessage?: string;
  onClose: () => void;
  onSave: (baseUrl: string, token?: string) => void;
  onClearToken: () => void;
  onTest: () => void;
}

const stateLabels: Record<ConnectionState, string> = {
  unknown: "未检测",
  checking: "检测中",
  connected: "已连接",
  unauthorized: "鉴权失败",
  offline: "无法连接",
};

export function ConnectionPanel({
  open,
  api,
  baseUrl,
  hasToken,
  connectionState,
  connectionMessage,
  onClose,
  onSave,
  onClearToken,
  onTest,
}: ConnectionPanelProps): JSX.Element | null {
  const [draftBaseUrl, setDraftBaseUrl] = useState(baseUrl);
  const [draftToken, setDraftToken] = useState("");

  useEffect(() => setDraftBaseUrl(baseUrl), [baseUrl]);

  if (!open) return null;

  return (
    <div className="drawer-backdrop" role="presentation" onClick={onClose}>
      <aside className="settings-panel" role="dialog" aria-label="连接设置" onClick={(event) => event.stopPropagation()}>
        <div className="drawer-header">
          <div>
            <div className="eyebrow">连接设置</div>
            <h2>Naqi 后端</h2>
          </div>
          <button className="icon-button" onClick={onClose} type="button" aria-label="关闭">
            ×
          </button>
        </div>
        <div className="settings-body">
          <p className="muted">API Key 仅保存到当前浏览器标签页的 sessionStorage，不会写入 URL、日志或项目文件。</p>
          <label className="field-label" htmlFor="api-base-url">API 基址</label>
          <input id="api-base-url" className="text-input" value={draftBaseUrl} onChange={(event) => setDraftBaseUrl(event.target.value)} />
          <label className="field-label" htmlFor="api-key">Bearer API Key</label>
          <input
            id="api-key"
            className="text-input"
            type="password"
            autoComplete="off"
            placeholder={hasToken ? "已保存，留空则保留现有 Key" : "粘贴后仅保存在当前会话"}
            value={draftToken}
            onChange={(event) => setDraftToken(event.target.value)}
          />
          <div className="connection-detail">
            <span className={`connection-dot connection-${connectionState}`} />
            <span>{stateLabels[connectionState]}</span>
            {connectionMessage ? <span className="muted"> · {connectionMessage}</span> : null}
          </div>
          <div className="settings-actions">
            <button className="button button-primary" onClick={() => { onSave(draftBaseUrl, draftToken || undefined); setDraftToken(""); }} type="button">
              保存并测试
            </button>
            <button className="button button-subtle" onClick={onTest} type="button">
              重新检测
            </button>
            {hasToken ? <button className="button button-danger" onClick={onClearToken} type="button">清除 Key</button> : null}
          </div>
          <div className="small muted">当前请求地址：{api.baseUrl}</div>
        </div>
      </aside>
    </div>
  );
}
