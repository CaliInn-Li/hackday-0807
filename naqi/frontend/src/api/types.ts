export type AssetKind = "characters" | "motions" | "animations";

export type FileKind =
  | "source_glb"
  | "rigged_glb"
  | "source_mp4"
  | "motion_npz"
  | "preview_mp4"
  | "preview_glb"
  | "animated_glb";

export type AssetStatus = "ready" | "processing" | "failed" | "unknown";

export type JobStatus =
  | "queued"
  | "running"
  | "succeeded"
  | "failed"
  | "cancelled"
  | "unknown";

export interface AssetFile {
  kind: FileKind;
  available: boolean;
  filename?: string;
  sizeBytes?: number;
  sha256?: string;
  contentType?: string;
}

export interface CharacterAsset {
  id: string;
  name: string;
  source?: string;
  sha256?: string;
  status: AssetStatus;
  createdAt?: string;
  files: Partial<Record<FileKind, AssetFile>>;
  metadata: Record<string, unknown>;
}

export interface MotionAsset {
  id: string;
  name: string;
  source?: string;
  sha256?: string;
  status: AssetStatus;
  createdAt?: string;
  frames?: number;
  fps?: number;
  durationSeconds?: number;
  cameraMode?: string;
  files: Partial<Record<FileKind, AssetFile>>;
  metadata: Record<string, unknown>;
}

export interface AnimationAsset {
  id: string;
  name: string;
  status: AssetStatus;
  createdAt?: string;
  characterId?: string;
  motionId?: string;
  sha256?: string;
  files: Partial<Record<FileKind, AssetFile>>;
  metadata: Record<string, unknown>;
}

export interface Job {
  id: string;
  kind?: string;
  status: JobStatus;
  stage?: string;
  createdAt?: string;
  startedAt?: string;
  finishedAt?: string;
  error?: string;
  logAvailable: boolean;
  artifactCount?: number;
  metadata: Record<string, unknown>;
}

export interface JobCounts {
  queued: number;
  running: number;
  succeeded: number;
  failed: number;
  cancelled: number;
}

export interface AssetFileDownload {
  blob: Blob;
  filename?: string;
  contentType?: string;
}

export interface CreateAnimationInput {
  characterId: string;
  motionId: string;
}

export interface UploadMotionOptions {
  cameraMode?: string;
  signal?: AbortSignal;
}

export interface RequestOptions {
  signal?: AbortSignal;
}

export type ConnectionState =
  | "unknown"
  | "checking"
  | "connected"
  | "unauthorized"
  | "offline";
