import { useState } from "react";
import type { ApiClient } from "../api";
import type { MotionAsset } from "../api/types";
import { AssetDrawer, type DrawerFile } from "../components/AssetDrawer";
import { EmptyState } from "../components/EmptyState";
import { PageHeader } from "../components/PageHeader";
import { StatusBadge } from "../components/StatusBadge";
import { formatDate, formatDuration, formatNumber, shortHash } from "../lib/format";

interface MotionsViewProps {
  api: ApiClient;
  motions: MotionAsset[];
  loading: boolean;
  unsupported: boolean;
  onUpload: (file: File, cameraMode: string) => Promise<void>;
}

export function MotionsView({ api, motions, loading, unsupported, onUpload }: MotionsViewProps): JSX.Element {
  const [selected, setSelected] = useState<MotionAsset | null>(null);
  const [cameraMode, setCameraMode] = useState("static");
  const [uploading, setUploading] = useState(false);
  const [uploadMessage, setUploadMessage] = useState<string | null>(null);

  async function chooseFile(file: File | undefined): Promise<void> {
    if (!file) return;
    setUploading(true);
    setUploadMessage(null);
    try {
      await onUpload(file, cameraMode);
      setUploadMessage("已提交动作识别任务；完成后可在详情中播放视频和下载 NPZ。");
    } catch (error) {
      setUploadMessage(error instanceof Error ? error.message : "上传失败");
    } finally {
      setUploading(false);
    }
  }

  const drawerFiles: DrawerFile[] = selected ? [
    { kind: "source_mp4", label: "原始 MP4", file: selected.files.source_mp4, mediaType: "video" },
    { kind: "motion_npz", label: "动作 NPZ", file: selected.files.motion_npz },
    { kind: "preview_mp4", label: "预览 MP4", file: selected.files.preview_mp4, mediaType: "video" },
    { kind: "preview_glb", label: "动作预览 GLB", file: selected.files.preview_glb, mediaType: "glb" },
  ] : [];

  return (
    <>
      <PageHeader
        eyebrow="ASSETS / MOTIONS"
        title="动作"
        description="上传人体视频并复用已识别动作；NPZ 是动作数据，preview MP4/GLB 用于快速检查。"
        actions={<div className="upload-group">
          <select className="select-input" value={cameraMode} onChange={(event) => setCameraMode(event.target.value)} aria-label="镜头模式">
            <option value="static">固定镜头</option>
            <option value="moving">移动镜头</option>
          </select>
          <label className={`button button-primary ${uploading ? "disabled" : ""}`}>
            {uploading ? "上传中…" : "上传 MP4"}
            <input className="visually-hidden" type="file" accept=".mp4,video/mp4" disabled={uploading} onChange={(event) => void chooseFile(event.target.files?.[0])} />
          </label>
        </div>}
      />
      {uploadMessage ? <div className="notice">{uploadMessage}</div> : null}
      {unsupported ? <div className="notice notice-warning">当前后端版本暂不支持动作资产接口；请先对齐 backend API。</div> : null}
      {loading ? <div className="loading-line">正在读取动作资产…</div> : null}
      {!loading && !unsupported && motions.length === 0 ? <EmptyState title="暂无动作" description="上传一个单人 MP4，完成 GVHMR 后动作可以被多个角色复用。" /> : null}
      <div className="asset-grid">
        {motions.map((motion) => (
          <article className="asset-card" key={motion.id}>
            <div className="asset-card-topline"><StatusBadge status={motion.status} /><span className="muted small">{formatDate(motion.createdAt)}</span></div>
            <h3>{motion.name}</h3>
            <div className="asset-source">{motion.source || "来源未记录"}</div>
            <dl className="compact-detail">
              <div><dt>帧数 / FPS</dt><dd>{formatNumber(motion.frames)} / {motion.fps ?? "—"}</dd></div>
              <div><dt>时长</dt><dd>{formatDuration(motion.durationSeconds)}</dd></div>
              <div><dt>SHA-256</dt><dd title={motion.sha256}>{shortHash(motion.sha256)}</dd></div>
            </dl>
            <button className="card-link" onClick={() => setSelected(motion)} type="button">打开详情与预览 →</button>
          </article>
        ))}
      </div>
      {selected ? <AssetDrawer api={api} assetKind="motions" assetId={selected.id} title={selected.name} subtitle={selected.source} fields={[
        { label: "状态", value: selected.status },
        { label: "帧数 / FPS", value: `${selected.frames ?? "—"} / ${selected.fps ?? "—"}` },
        { label: "时长", value: formatDuration(selected.durationSeconds) },
        { label: "SHA-256", value: selected.sha256 },
        { label: "镜头模式", value: selected.cameraMode },
      ]} files={drawerFiles} onClose={() => setSelected(null)} /> : null}
    </>
  );
}
