import { useState } from "react";
import type { ApiClient } from "../api";
import type { CharacterAsset } from "../api/types";
import { AssetDrawer, type DrawerFile } from "../components/AssetDrawer";
import { EmptyState } from "../components/EmptyState";
import { PageHeader } from "../components/PageHeader";
import { StatusBadge } from "../components/StatusBadge";
import { formatBytes, formatDate, shortHash } from "../lib/format";

interface CharactersViewProps {
  api: ApiClient;
  characters: CharacterAsset[];
  loading: boolean;
  unsupported: boolean;
  onUpload: (file: File) => Promise<void>;
}

export function CharactersView({ api, characters, loading, unsupported, onUpload }: CharactersViewProps): JSX.Element {
  const [selected, setSelected] = useState<CharacterAsset | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadMessage, setUploadMessage] = useState<string | null>(null);

  async function chooseFile(file: File | undefined): Promise<void> {
    if (!file) return;
    setUploading(true);
    setUploadMessage(null);
    try {
      await onUpload(file);
      setUploadMessage("已提交，后端开始处理后会在任务中显示状态。");
    } catch (error) {
      setUploadMessage(error instanceof Error ? error.message : "上传失败");
    } finally {
      setUploading(false);
    }
  }

  const drawerFiles: DrawerFile[] = selected ? [
    { kind: "source_glb", label: "原始 GLB", file: selected.files.source_glb, mediaType: "glb" },
    { kind: "rigged_glb", label: "已绑骨 GLB", file: selected.files.rigged_glb, mediaType: "glb" },
  ] : [];

  return (
    <>
      <PageHeader
        eyebrow="ASSETS / CHARACTERS"
        title="角色"
        description="管理原始 GLB 与 SkinTokens 生成的已绑骨 GLB，作为后续动画组合的目标。"
        actions={<label className={`button button-primary ${uploading ? "disabled" : ""}`}>
          {uploading ? "上传中…" : "上传 GLB"}
          <input className="visually-hidden" type="file" accept=".glb,model/gltf-binary" disabled={uploading} onChange={(event) => void chooseFile(event.target.files?.[0])} />
        </label>}
      />
      {uploadMessage ? <div className="notice">{uploadMessage}</div> : null}
      {unsupported ? <Unsupported /> : null}
      {loading ? <div className="loading-line">正在读取角色资产…</div> : null}
      {!loading && !unsupported && characters.length === 0 ? <EmptyState title="暂无角色" description="上传一个没有骨骼的 GLB，后端会生成可重定向的已绑骨版本。" /> : null}
      <div className="asset-grid">
        {characters.map((character) => (
          <article className="asset-card" key={character.id}>
            <div className="asset-card-topline"><StatusBadge status={character.status} /><span className="muted small">{formatDate(character.createdAt)}</span></div>
            <h3>{character.name}</h3>
            <div className="asset-source">{character.source || "来源未记录"}</div>
            <dl className="compact-detail">
              <div><dt>SHA-256</dt><dd title={character.sha256}>{shortHash(character.sha256)}</dd></div>
              <div><dt>原始文件</dt><dd>{character.files.source_glb?.filename || (character.files.source_glb?.available ? "可用" : "—")}</dd></div>
              <div><dt>已绑骨</dt><dd>{character.files.rigged_glb?.available ? formatBytes(character.files.rigged_glb.sizeBytes) : "未生成"}</dd></div>
            </dl>
            <button className="card-link" onClick={() => setSelected(character)} type="button">打开详情与预览 →</button>
          </article>
        ))}
      </div>
      {selected ? <AssetDrawer api={api} assetKind="characters" assetId={selected.id} title={selected.name} subtitle={selected.source} fields={[
        { label: "状态", value: selected.status },
        { label: "SHA-256", value: selected.sha256 },
        { label: "创建时间", value: formatDate(selected.createdAt) },
      ]} files={drawerFiles} onClose={() => setSelected(null)} /> : null}
    </>
  );
}

function Unsupported(): JSX.Element {
  return <div className="notice notice-warning">当前后端版本暂不支持角色资产接口；前端已启动，但请先升级或对齐 backend API。</div>;
}
