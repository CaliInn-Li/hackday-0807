import { useEffect, useState } from "react";
import { type ApiClient } from "../api";
import type { AssetFile, AssetKind, FileKind } from "../api/types";
import { AssetFileRow, AssetPreview } from "./AssetPreview";

export interface DrawerField {
  label: string;
  value?: string;
}

export interface DrawerFile {
  kind: FileKind;
  label: string;
  file?: AssetFile;
  mediaType?: "video" | "glb";
}

interface AssetDrawerProps {
  api: ApiClient;
  assetKind: AssetKind;
  assetId: string;
  title: string;
  subtitle?: string;
  fields: DrawerField[];
  files: DrawerFile[];
  onClose: () => void;
}

export function AssetDrawer({
  api,
  assetKind,
  assetId,
  title,
  subtitle,
  fields,
  files,
  onClose,
}: AssetDrawerProps): JSX.Element {
  const defaultPreview = files.find((file) => file.file?.available && (file.kind === "preview_mp4" || file.kind === "preview_glb"))
    ?? files.find((file) => file.file?.available && file.mediaType);
  const [preview, setPreview] = useState<DrawerFile | null>(defaultPreview ?? null);

  useEffect(() => {
    setPreview(defaultPreview ?? null);
  }, [assetId]);

  return (
    <div className="drawer-backdrop" role="presentation" onClick={onClose}>
      <aside className="asset-drawer" role="dialog" aria-label={title} onClick={(event) => event.stopPropagation()}>
        <div className="drawer-header">
          <div>
            <div className="eyebrow">资产详情</div>
            <h2>{title}</h2>
            {subtitle ? <div className="muted">{subtitle}</div> : null}
          </div>
          <button className="icon-button" onClick={onClose} type="button" aria-label="关闭">
            ×
          </button>
        </div>

        <div className="drawer-content">
          <dl className="detail-grid">
            {fields.map((field) => (
              <div key={field.label}>
                <dt>{field.label}</dt>
                <dd>{field.value || "—"}</dd>
              </div>
            ))}
          </dl>

          <section className="drawer-section">
            <div className="section-label">文件</div>
            <div className="file-list">
              {files.map((file) => (
                <AssetFileRow
                  key={file.kind}
                  api={api}
                  assetKind={assetKind}
                  assetId={assetId}
                  fileKind={file.kind}
                  label={file.label}
                  filename={file.file?.filename}
                  available={file.file?.available ?? false}
                  mediaType={file.mediaType}
                  onPreview={() => setPreview(file)}
                />
              ))}
            </div>
          </section>

          {preview?.mediaType ? (
            <section className="drawer-section preview-section">
              <div className="section-label">预览 · {preview.label}</div>
              <AssetPreview
                api={api}
                assetKind={assetKind}
                assetId={assetId}
                fileKind={preview.kind}
                mediaType={preview.mediaType}
                label={preview.label}
                available={preview.file?.available ?? false}
              />
            </section>
          ) : null}
        </div>
      </aside>
    </div>
  );
}
