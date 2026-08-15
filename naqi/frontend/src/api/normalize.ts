import type {
  AnimationAsset,
  AssetFile,
  AssetStatus,
  CharacterAsset,
  FileKind,
  Job,
  JobStatus,
  MotionAsset,
} from "./types";

export type JsonRecord = Record<string, unknown>;

export function asRecord(value: unknown): JsonRecord {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as JsonRecord)
    : {};
}

function firstValue(record: JsonRecord, keys: string[]): unknown {
  for (const key of keys) {
    if (record[key] !== undefined && record[key] !== null) {
      return record[key];
    }
  }
  return undefined;
}

function stringValue(value: unknown): string | undefined {
  return typeof value === "string" && value.trim() ? value.trim() : undefined;
}

function numberValue(value: unknown): number | undefined {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim() && Number.isFinite(Number(value))) {
    return Number(value);
  }
  return undefined;
}

function idValue(record: JsonRecord, fallback: string): string {
  return String(firstValue(record, ["id", "asset_id", "assetId", "job_id", "jobId"]) ?? fallback);
}

export function normalizeAssetStatus(value: unknown): AssetStatus {
  const status = String(value ?? "").toLowerCase();
  if (["ready", "succeeded", "success", "completed", "complete"].includes(status)) {
    return "ready";
  }
  if (["queued", "pending", "running", "processing", "started"].includes(status)) {
    return "processing";
  }
  if (["failed", "error", "cancelled", "canceled"].includes(status)) return "failed";
  return "unknown";
}

export function normalizeJobStatus(value: unknown): JobStatus {
  const status = String(value ?? "").toLowerCase();
  if (["queued", "pending"].includes(status)) return "queued";
  if (["running", "processing", "started"].includes(status)) return "running";
  if (["succeeded", "success", "completed", "complete", "ready"].includes(status)) {
    return "succeeded";
  }
  if (["failed", "error"].includes(status)) return "failed";
  if (["cancelled", "canceled"].includes(status)) return "cancelled";
  return "unknown";
}

function fileAliases(kind: FileKind): string[] {
  const dashed = kind.replaceAll("_", "-");
  const compact = kind.replaceAll("_", "");
  return [kind, dashed, compact];
}

function normalizeFileValue(kind: FileKind, value: unknown): AssetFile | undefined {
  if (value === undefined || value === null || value === false) return undefined;
  if (typeof value === "string") {
    return { kind, available: true, filename: value.split(/[\\/]/).pop() };
  }
  if (typeof value === "boolean") return { kind, available: value };
  if (typeof value !== "object" || Array.isArray(value)) return { kind, available: true };

  const record = asRecord(value);
  const available = record.available !== false && record.exists !== false;
  return {
    kind,
    available,
    filename: stringValue(firstValue(record, ["filename", "name", "file_name", "fileName"])),
    sizeBytes: numberValue(firstValue(record, ["size_bytes", "sizeBytes", "size"])),
    sha256: stringValue(firstValue(record, ["sha256", "sha", "hash"])),
    contentType: stringValue(firstValue(record, ["content_type", "contentType", "mime_type", "mimeType", "mime"])),
  };
}

function normalizeFiles(record: JsonRecord, kinds: FileKind[]): Partial<Record<FileKind, AssetFile>> {
  const files = asRecord(record.files);
  const fileList = Array.isArray(record.files) ? record.files.map(asRecord) : [];
  const result: Partial<Record<FileKind, AssetFile>> = {};
  for (const kind of kinds) {
    const aliases = fileAliases(kind);
    const listValue = fileList.find((item) =>
      aliases.includes(String(firstValue(item, ["file_kind", "fileKind", "kind"]) ?? "")),
    );
    const value = firstValue(files, aliases) ?? listValue ?? firstValue(record, aliases);
    const camel = kind.replace(/_([a-z])/g, (_, char: string) => char.toUpperCase());
    const marker = firstValue(record, [`has_${kind}`, `has_${camel}`, `has${camel[0]?.toUpperCase() ?? ""}${camel.slice(1)}`]);
    const normalized = normalizeFileValue(kind, value ?? marker);
    if (normalized) result[kind] = normalized;
  }
  return result;
}

export function normalizeList<T>(payload: unknown, mapper: (item: unknown, index: number) => T): T[] {
  if (Array.isArray(payload)) return payload.map(mapper);
  const record = asRecord(payload);
  const items = record.items ?? record.data ?? record.results;
  return Array.isArray(items) ? items.map(mapper) : [];
}

export function normalizeCharacter(value: unknown, index = 0): CharacterAsset {
  const record = asRecord(value);
  const name = stringValue(firstValue(record, ["name", "filename", "file_name"])) ?? `角色 ${index + 1}`;
  return {
    id: idValue(record, `character-${index + 1}`),
    name,
    source: stringValue(firstValue(record, ["source", "source_file", "sourceFile", "original"])),
    sha256: stringValue(firstValue(record, ["sha256", "source_sha256", "sourceSha256", "hash"])),
    status: normalizeAssetStatus(firstValue(record, ["status", "state"])),
    createdAt: stringValue(firstValue(record, ["created_at", "createdAt", "created"])),
    files: normalizeFiles(record, ["source_glb", "rigged_glb"]),
    metadata: record,
  };
}

export function normalizeMotion(value: unknown, index = 0): MotionAsset {
  const record = asRecord(value);
  const name = stringValue(firstValue(record, ["name", "filename", "file_name"])) ?? `动作 ${index + 1}`;
  return {
    id: idValue(record, `motion-${index + 1}`),
    name,
    source: stringValue(firstValue(record, ["source", "source_file", "sourceFile", "video"])),
    sha256: stringValue(firstValue(record, ["sha256", "source_sha256", "sourceSha256", "hash"])),
    status: normalizeAssetStatus(firstValue(record, ["status", "state"])),
    createdAt: stringValue(firstValue(record, ["created_at", "createdAt", "created"])),
    frames: numberValue(firstValue(record, ["frames", "frame_count", "frameCount"])),
    fps: numberValue(firstValue(record, ["fps", "frame_rate", "frameRate"])),
    durationSeconds: numberValue(firstValue(record, ["duration_seconds", "durationSeconds", "duration"])),
    cameraMode: stringValue(firstValue(record, ["camera_mode", "cameraMode"])),
    files: normalizeFiles(record, ["source_mp4", "motion_npz", "preview_mp4", "preview_glb"]),
    metadata: record,
  };
}

export function normalizeAnimation(value: unknown, index = 0): AnimationAsset {
  const record = asRecord(value);
  return {
    id: idValue(record, `animation-${index + 1}`),
    name: stringValue(firstValue(record, ["name", "filename", "file_name"])) ?? `动画 ${index + 1}`,
    status: normalizeAssetStatus(firstValue(record, ["status", "state"])),
    createdAt: stringValue(firstValue(record, ["created_at", "createdAt", "created"])),
    characterId: stringValue(firstValue(record, ["character_id", "characterId", "source_character_id", "sourceCharacterId"])),
    motionId: stringValue(firstValue(record, ["motion_id", "motionId", "source_motion_id", "sourceMotionId"])),
    sha256: stringValue(firstValue(record, ["sha256", "source_sha256", "sourceSha256", "hash"])),
    files: normalizeFiles(record, ["animated_glb"]),
    metadata: record,
  };
}

export function normalizeJob(value: unknown, index = 0): Job {
  const record = asRecord(value);
  const error = stringValue(firstValue(record, ["error", "error_message", "errorMessage", "message"]));
  return {
    id: idValue(record, `job-${index + 1}`),
    kind: stringValue(firstValue(record, ["kind", "type", "job_type", "jobType"])),
    status: normalizeJobStatus(firstValue(record, ["status", "state"])),
    stage: stringValue(firstValue(record, ["stage", "phase", "current_stage", "currentStage"])),
    createdAt: stringValue(firstValue(record, ["created_at", "createdAt", "created"])),
    startedAt: stringValue(firstValue(record, ["started_at", "startedAt"])),
    finishedAt: stringValue(firstValue(record, ["finished_at", "finishedAt", "completed_at", "completedAt"])),
    error,
    logAvailable: Boolean(firstValue(record, ["log_available", "logAvailable", "has_log", "hasLog"])),
    artifactCount: numberValue(firstValue(record, ["artifact_count", "artifactCount"])),
    metadata: record,
  };
}
