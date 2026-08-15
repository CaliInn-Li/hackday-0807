import { useMemo, useState } from "react";
import type { ApiClient } from "../api";
import type { AnimationAsset, CharacterAsset, MotionAsset } from "../api/types";
import { AssetDrawer, type DrawerFile } from "../components/AssetDrawer";
import { EmptyState } from "../components/EmptyState";
import { PageHeader } from "../components/PageHeader";
import { StatusBadge } from "../components/StatusBadge";
import { formatDate, shortHash } from "../lib/format";

interface AnimationsViewProps {
  api: ApiClient;
  animations: AnimationAsset[];
  characters: CharacterAsset[];
  motions: MotionAsset[];
  loading: boolean;
  unsupported: boolean;
  onCreate: (characterId: string, motionId: string) => Promise<void>;
}

export function AnimationsView({ api, animations, characters, motions, loading, unsupported, onCreate }: AnimationsViewProps): JSX.Element {
  const [characterId, setCharacterId] = useState("");
  const [motionId, setMotionId] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [selected, setSelected] = useState<AnimationAsset | null>(null);

  const readyCharacters = useMemo(
    () => characters.filter((item) => item.status === "ready" && item.files.rigged_glb?.available),
    [characters],
  );
  const readyMotions = useMemo(
    () => motions.filter((item) => item.status === "ready" && item.files.motion_npz?.available),
    [motions],
  );

  async function submit(): Promise<void> {
    if (!characterId || !motionId) {
      setMessage("请选择一个已绑骨角色和一个已完成动作。");
      return;
    }
    setSubmitting(true);
    setMessage(null);
    try {
      await onCreate(characterId, motionId);
      setMessage("重定向任务已提交，请在任务页查看进度。");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "提交失败");
    } finally {
      setSubmitting(false);
    }
  }

  const drawerFiles: DrawerFile[] = selected ? [
    { kind: "animated_glb", label: "动画 GLB", file: selected.files.animated_glb, mediaType: "glb" },
  ] : [];

  return (
    <>
      <PageHeader eyebrow="PIPELINE / RETARGET" title="动画组合" description="把一次动作识别结果套到任意已绑骨角色上，动作和角色各自只计算一次。" />
      <section className="compose-panel">
        <div className="compose-copy">
          <div className="eyebrow">NEW COMBINATION</div>
          <h2>创建重定向任务</h2>
          <p className="muted">选择 ready 资产后，后端会生成动画 GLB。此处只提交 ID，不上传重复文件。</p>
        </div>
        <div className="compose-fields">
          <label className="field-label" htmlFor="character-select">已绑骨角色</label>
          <select id="character-select" className="select-input wide" value={characterId} onChange={(event) => setCharacterId(event.target.value)}>
            <option value="">请选择角色</option>
            {readyCharacters.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
          </select>
          <label className="field-label" htmlFor="motion-select">已识别动作</label>
          <select id="motion-select" className="select-input wide" value={motionId} onChange={(event) => setMotionId(event.target.value)}>
            <option value="">请选择动作</option>
            {readyMotions.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
          </select>
          <button className="button button-primary compose-submit" disabled={submitting || unsupported} onClick={() => void submit()} type="button">
            {submitting ? "提交中…" : "生成动画 GLB"}
          </button>
        </div>
      </section>
      {message ? <div className="notice">{message}</div> : null}
      {unsupported ? <div className="notice notice-warning">当前后端版本暂不支持动画列表接口；组合提交可能也尚未实现。</div> : null}
      <section className="section-block">
        <div className="section-heading"><div><div className="eyebrow">OUTPUTS</div><h2>已生成动画</h2></div></div>
        {loading ? <div className="loading-line">正在读取动画资产…</div> : null}
        {!loading && !unsupported && animations.length === 0 ? <EmptyState title="暂无动画输出" description="选择上方两个 ready 资产，创建第一条动画 GLB。" /> : null}
        <div className="asset-grid">
          {animations.map((animation) => (
            <article className="asset-card" key={animation.id}>
              <div className="asset-card-topline"><StatusBadge status={animation.status} /><span className="muted small">{formatDate(animation.createdAt)}</span></div>
              <h3>{animation.name}</h3>
              <div className="asset-source">角色 {animation.characterId || "—"} · 动作 {animation.motionId || "—"}</div>
              <dl className="compact-detail"><div><dt>SHA-256</dt><dd title={animation.sha256}>{shortHash(animation.sha256)}</dd></div><div><dt>动画文件</dt><dd>{animation.files.animated_glb?.available ? "可预览 / 下载" : "未生成"}</dd></div></dl>
              <button className="card-link" onClick={() => setSelected(animation)} type="button">打开详情与预览 →</button>
            </article>
          ))}
        </div>
      </section>
      {selected ? <AssetDrawer api={api} assetKind="animations" assetId={selected.id} title={selected.name} subtitle={`角色 ${selected.characterId || "—"} · 动作 ${selected.motionId || "—"}`} fields={[
        { label: "状态", value: selected.status },
        { label: "SHA-256", value: selected.sha256 },
        { label: "创建时间", value: formatDate(selected.createdAt) },
      ]} files={drawerFiles} onClose={() => setSelected(null)} /> : null}
    </>
  );
}
