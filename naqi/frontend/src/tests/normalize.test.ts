import { describe, expect, it } from "vitest";
import { normalizeCharacter, normalizeJob, normalizeList, normalizeMotion } from "../api/normalize";

describe("API response normalization", () => {
  it("accepts both array and items list envelopes", () => {
    expect(normalizeList([{ id: "a" }], (item) => item)).toHaveLength(1);
    expect(normalizeList({ items: [{ id: "b" }] }, (item) => item)).toHaveLength(1);
    expect(normalizeList({ data: [{ id: "c" }] }, (item) => item)).toHaveLength(1);
  });

  it("normalizes file aliases and motion metadata", () => {
    const motion = normalizeMotion({
      asset_id: "motion-1",
      filename: "dance.mp4",
      status: "succeeded",
      frame_count: 241,
      frame_rate: 24,
      duration_seconds: 10.04,
      files: { motion_npz: { exists: true, filename: "dance.npz" }, preview_mp4: true },
    });
    expect(motion.id).toBe("motion-1");
    expect(motion.status).toBe("ready");
    expect(motion.frames).toBe(241);
    expect(motion.files.motion_npz?.filename).toBe("dance.npz");
    expect(motion.files.preview_mp4?.available).toBe(true);
  });

  it("keeps character and job status semantics separate", () => {
    expect(normalizeCharacter({ id: 4, state: "processing", files: { rigged_glb: false } }).status).toBe("processing");
    expect(normalizeJob({ job_id: "j-1", state: "completed", has_log: true }).status).toBe("succeeded");
    expect(normalizeJob({ job_id: "j-2", state: "failed", error_message: "bad input" }).error).toBe("bad input");
  });

  it("accepts the backend file array and source relation fields", () => {
    const character = normalizeCharacter({
      id: "character-1",
      source_sha256: "abc123",
      status: "ready",
      files: [
        {
          file_kind: "rigged_glb",
          filename: "rigged.glb",
          size_bytes: 42,
          sha256: "def456",
          mime_type: "model/gltf-binary",
        },
      ],
    });
    expect(character.sha256).toBe("abc123");
    expect(character.files.rigged_glb?.available).toBe(true);
    expect(character.files.rigged_glb?.sizeBytes).toBe(42);
    expect(character.files.rigged_glb?.contentType).toBe("model/gltf-binary");
  });
});
