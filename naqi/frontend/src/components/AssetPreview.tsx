import { useEffect, useRef, useState } from "react";
import { ApiError, type ApiClient } from "../api";
import type { AssetKind, FileKind } from "../api/types";

type MediaType = "video" | "glb";

interface AssetPreviewProps {
  api: ApiClient;
  assetKind: AssetKind;
  assetId: string;
  fileKind: FileKind;
  mediaType: MediaType;
  label: string;
  available?: boolean;
  compact?: boolean;
}

function mediaError(error: unknown): string {
  if (error instanceof ApiError && error.status === 404) return "后端版本暂不支持这个预览文件";
  return error instanceof Error ? error.message : "预览加载失败";
}

export function AssetPreview({
  api,
  assetKind,
  assetId,
  fileKind,
  mediaType,
  label,
  available = true,
  compact = false,
}: AssetPreviewProps): JSX.Element {
  const objectUrl = useRef<string | null>(null);
  const [src, setSrc] = useState<string | null>(null);
  const [state, setState] = useState<"idle" | "loading" | "ready" | "error">("idle");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    if (objectUrl.current) URL.revokeObjectURL(objectUrl.current);
    objectUrl.current = null;
    setSrc(null);
    setError(null);

    if (!available) {
      setState("idle");
      return () => controller.abort();
    }

    setState("loading");
    api
      .getAssetFile(assetKind, assetId, fileKind, false, { signal: controller.signal })
      .then(({ blob }) => {
        if (controller.signal.aborted) return;
        const url = URL.createObjectURL(blob);
        objectUrl.current = url;
        setSrc(url);
        setState("ready");
      })
      .catch((caught: unknown) => {
        if (controller.signal.aborted) return;
        setError(mediaError(caught));
        setState("error");
      });

    return () => {
      controller.abort();
      if (objectUrl.current) URL.revokeObjectURL(objectUrl.current);
      objectUrl.current = null;
    };
  }, [api, assetId, assetKind, available, fileKind]);

  if (!available) return <div className="preview-empty">暂无{label}</div>;
  if (state === "loading") return <div className={`preview-loading ${compact ? "compact" : ""}`}>正在加载{label}…</div>;
  if (state === "error") return <div className="preview-error">{error}</div>;
  if (!src) return <div className="preview-empty">暂无{label}</div>;

  if (mediaType === "video") {
    return (
      <video className={`media-preview video-preview ${compact ? "compact" : ""}`} controls playsInline preload="metadata" src={src} />
    );
  }

  return (
    <model-viewer
      className={`media-preview model-preview ${compact ? "compact" : ""}`}
      src={src}
      alt={label}
      camera-controls="true"
      auto-rotate="true"
      autoplay="true"
      shadow-intensity="0.65"
      exposure="1"
      interaction-prompt="none"
    />
  );
}

interface DownloadButtonProps {
  api: ApiClient;
  assetKind: AssetKind;
  assetId: string;
  fileKind: FileKind;
  label?: string;
}

export function DownloadButton({ api, assetKind, assetId, fileKind, label = "下载" }: DownloadButtonProps): JSX.Element {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function download(): Promise<void> {
    setBusy(true);
    setError(null);
    try {
      const result = await api.getAssetFile(assetKind, assetId, fileKind, true);
      const url = URL.createObjectURL(result.blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = result.filename ?? `${assetId}-${fileKind}`;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(url);
    } catch (caught: unknown) {
      setError(mediaError(caught));
    } finally {
      setBusy(false);
    }
  }

  return (
    <span className="download-control">
      <button className="button button-subtle" disabled={busy} onClick={() => void download()} type="button">
        {busy ? "准备中…" : label}
      </button>
      {error ? <span className="inline-error">{error}</span> : null}
    </span>
  );
}

interface AssetFileRowProps {
  api: ApiClient;
  assetKind: AssetKind;
  assetId: string;
  fileKind: FileKind;
  label: string;
  filename?: string;
  available?: boolean;
  mediaType?: MediaType;
  onPreview?: () => void;
}

export function AssetFileRow({
  api,
  assetKind,
  assetId,
  fileKind,
  label,
  filename,
  available = true,
  mediaType,
  onPreview,
}: AssetFileRowProps): JSX.Element {
  return (
    <div className="file-row">
      <div>
        <div className="file-label">{label}</div>
        <div className="muted small">{available ? filename ?? fileKind : "未生成"}</div>
      </div>
      <div className="file-actions">
        {mediaType && available && onPreview ? (
          <button className="button button-subtle" onClick={onPreview} type="button">
            预览
          </button>
        ) : null}
        {available ? (
          <DownloadButton api={api} assetKind={assetKind} assetId={assetId} fileKind={fileKind} />
        ) : null}
      </div>
    </div>
  );
}
