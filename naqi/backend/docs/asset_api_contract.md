# NAQI asset API contract

The frontend talks only to the backend HTTP API. Every list response uses the
shape `{ "items": [...], "total": N }`; this avoids making the frontend depend
on a pagination implementation.

## Asset lifecycle

`character`, `motion`, and `animation` assets have the states
`pending | queued | running | ready | failed | cancelled`. Their `latest_job_id`
points to a typed job whose `job_type` is `rig`, `motion`, or `retarget`.

Character and motion uploads are deduplicated by source SHA-256 plus their
effective stage parameters. Retarget assets are deduplicated by the ready
character `rigged_glb` SHA-256, ready motion `motion_npz` SHA-256, and the
`render_keyframes` option. A cache response has `cache_hit: true` and does not
enqueue another GPU job.

## Endpoints

All endpoints below, except `GET /health/live`, use the public Bearer key.

```text
GET  /health/live

GET  /v1/assets/characters
POST /v1/assets/characters
     multipart: file=<character.glb>, name=<optional display name>

GET  /v1/assets/motions
POST /v1/assets/motions
     multipart: file=<motion.mp4>, name=<optional display name>, camera_mode=static|moving

GET  /v1/assets/animations
POST /v1/animations
     JSON: {"character_id":"...", "motion_id":"...", "render_keyframes":false}

GET /v1/assets/{kind}/{asset_id}/files/{file_kind}?download=false

GET /v1/jobs
GET /v1/jobs/{id}
POST /v1/jobs/{id}/cancel
```

`GET /v1/jobs` is a unified view. Legacy full-pipeline jobs have
`job_family=full` and `job_type=full`; typed jobs have `job_family=asset` and a
typed job type. Existing `POST /v1/jobs` remains unchanged.

## File kinds

| Asset | Allowed file kinds |
| --- | --- |
| character | `source_glb`, `rigged_glb`, `topology_report`, `mapping` |
| motion | `source_mp4`, `motion_npz`, `manifest`, `preview_mp4`, `preview_glb` |
| animation | `animated_glb`, `retarget_report`, `qa_report` |

Canonical route kinds are the plural forms `characters`, `motions`, and
`animations`; singular forms remain accepted for compatibility.

The server resolves file paths from SQLite records and checks that the resolved
file stays under `NAQI_DATA_ROOT` and the owning asset directory. Clients never
send a filesystem path.
Downloads use `FileResponse`, explicit GLB/MP4/NPZ MIME types, and modern
Starlette range support where available. They are inline by default; append
`download=true` for an attachment.

## Stage isolation

The typed worker and the legacy full-pipeline worker share one queue and one
process-wide GPU lock, so at most one GPU stage runs at a time. The backend
does not import Torch, bpy, SkinTokens, or GVHMR. It launches the local
`naqi_backend.stage_adapter` with argv and `shell=False`; the adapter invokes
external tools configured by `NAQI_PIPELINE_TOOLS_DIR`, `SKINTOKENS_HOME`,
`GVHMR_HOME`, and `BLENDER_BIN`.

For the current monorepo, set `NAQI_PIPELINE_TOOLS_DIR` to the directory that
contains the existing stage scripts. In a standalone deployment, copy or
install those pipeline tools separately and point the variable at that package;
the backend does not copy or modify the repository's prototype scripts.
