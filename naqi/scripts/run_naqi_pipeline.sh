#!/usr/bin/env bash
set -Eeuo pipefail

# One-command remote pipeline:
#   unrigged GLB + MP4
#     -> SkinTokens transfer rigging
#     -> topology-derived SMPL-22 mapping
#     -> GVHMR CUDA inference
#     -> Blender retarget/bake
#     -> rigged GLB + animated GLB + structural/keyframe QA

NAQI_ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)

SKINTOKENS_HOME=${SKINTOKENS_HOME:-"$HOME/SkinTokens"}
GVHMR_HOME=${GVHMR_HOME:-"$HOME/GVHMR"}
BLENDER_BIN=${BLENDER_BIN:-/usr/local/bin/blender}
SKINTOKENS_SERVER_TIMEOUT=${SKINTOKENS_SERVER_TIMEOUT:-600}
# Leave empty to probe the video with ffprobe; use NAQI_FPS=24 when ffprobe is
# unavailable or when the source container has an unreliable FPS field.
NAQI_FPS=${NAQI_FPS:-}
NAQI_RENDER_KEYFRAMES=${NAQI_RENDER_KEYFRAMES:-1}
SKIN_PY="$SKINTOKENS_HOME/.venv/bin/python"
GVHMR_PY="$GVHMR_HOME/.venv310/bin/python"

SKINTOKENS_RUNNER="$NAQI_ROOT/scripts/run_skintokens_offline.py"
TOPOLOGY_SCRIPT="$NAQI_ROOT/scripts/inspect_skin_tokens_topology.py"
MAPPING_SCRIPT="$NAQI_ROOT/scripts/build_topology_mapping.py"
EXTRACT_SCRIPT="$NAQI_ROOT/scripts/extract_gvhmr_motion.py"
APPLY_SCRIPT="$NAQI_ROOT/scripts/apply_gvhmr_motion.py"
INSPECT_SCRIPT="$NAQI_ROOT/scripts/inspect_glb_animation.py"
KEYFRAME_SCRIPT="$NAQI_ROOT/scripts/render_glb_keyframes.py"

usage() {
  cat >&2 <<'EOF'
Usage:
  run_naqi_pipeline.sh <video.mp4> <unrigged-character.glb> <output_dir> [static|moving]
  run_naqi_pipeline.sh --check

The default camera mode is static. Set --x-positive-is-right through the
NAQI_MAPPING_SIDE variable when the character's GLB uses the opposite lateral
coordinate convention:
  NAQI_MAPPING_SIDE=right run_naqi_pipeline.sh video.mp4 character.glb out
EOF
}

check_environment() {
  local failed=0
  local required=(
    "$SKIN_PY"
    "$GVHMR_PY"
    "$BLENDER_BIN"
    "$GVHMR_HOME/tools/demo/demo.py"
    "$SKINTOKENS_RUNNER"
    "$TOPOLOGY_SCRIPT"
    "$MAPPING_SCRIPT"
    "$EXTRACT_SCRIPT"
    "$APPLY_SCRIPT"
    "$INSPECT_SCRIPT"
    "$KEYFRAME_SCRIPT"
  )
  echo "naqi root: $NAQI_ROOT"
  for path in "${required[@]}"; do
    if [[ -e "$path" ]]; then
      echo "[OK] $path"
    else
      echo "[MISSING] $path" >&2
      failed=1
    fi
  done
  if [[ "$failed" -ne 0 ]]; then
    echo "Environment check failed. Set SKINTOKENS_HOME, GVHMR_HOME, or BLENDER_BIN as needed." >&2
    return 1
  fi
  echo "Environment check passed."
}

detect_fps() {
  if [[ -n "${NAQI_FPS:-}" ]]; then
    printf '%s\n' "$NAQI_FPS"
    return
  fi
  if command -v ffprobe >/dev/null 2>&1; then
    local rate
    rate=$(ffprobe -v error -select_streams v:0 \
      -show_entries stream=avg_frame_rate -of default=nw=1:nk=1 "$VIDEO" 2>/dev/null || true)
    if [[ "$rate" =~ ^[0-9]+/[0-9]+$ ]]; then
      awk -F/ '{ if ($2 != 0) printf "%.6f\n", $1 / $2 }' <<<"$rate"
      return
    fi
    if [[ "$rate" =~ ^[0-9]+([.][0-9]+)?$ ]]; then
      printf '%s\n' "$rate"
      return
    fi
  fi
  printf '24\n'
}

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  usage
  exit 0
fi

if [[ "${1:-}" == "--check" ]]; then
  [[ $# -eq 1 ]] || { usage; exit 2; }
  check_environment
  exit 0
fi

if [[ $# -lt 3 || $# -gt 4 ]]; then
  usage
  exit 2
fi

VIDEO=$(realpath "$1")
CHARACTER=$(realpath "$2")
mkdir -p "$3"
OUTPUT=$(cd "$3" && pwd)
CAMERA_MODE=${4:-static}

[[ -f "$VIDEO" ]] || { echo "Missing video: $VIDEO" >&2; exit 1; }
[[ -f "$CHARACTER" ]] || { echo "Missing character: $CHARACTER" >&2; exit 1; }
[[ "$CAMERA_MODE" == "static" || "$CAMERA_MODE" == "moving" ]] || {
  echo "Camera mode must be 'static' or 'moving'" >&2
  exit 2
}

check_environment

VIDEO_BASE=$(basename "$VIDEO")
VIDEO_STEM=${VIDEO_BASE%.*}
CHARACTER_BASE=$(basename "$CHARACTER")
CHARACTER_STEM=${CHARACTER_BASE%.*}
FPS=$(detect_fps)

mkdir -p "$OUTPUT"/{inputs,rigging,motion/gvhmr,outputs,reports,renders/keyframes,logs}
cp -f "$VIDEO" "$OUTPUT/inputs/$VIDEO_BASE"
cp -f "$CHARACTER" "$OUTPUT/inputs/$CHARACTER_BASE"

RIGGED="$OUTPUT/rigging/${CHARACTER_STEM}_rigged.glb"
TOPOLOGY_REPORT="$OUTPUT/reports/topology.json"
MAPPING_JSON="$OUTPUT/reports/topology_mapping.json"
GVHMR_ROOT="$OUTPUT/motion/gvhmr"
GVHMR_RESULT="$GVHMR_ROOT/$VIDEO_STEM/hmr4d_results.pt"
MOTION_NPZ="$OUTPUT/motion/${VIDEO_STEM}_smpl22.npz"
MOTION_MANIFEST="$OUTPUT/motion/${VIDEO_STEM}_motion_manifest.json"
FINAL_GLB="$OUTPUT/outputs/${CHARACTER_STEM}_${VIDEO_STEM}_animated.glb"
RETARGET_REPORT="$OUTPUT/reports/retarget.json"
STRUCTURE_REPORT="$OUTPUT/reports/animation.json"

echo "[1/7] SkinTokens transfer rigging (GPU-backed service)"
(
  cd "$SKINTOKENS_HOME"
  "$SKIN_PY" "$SKINTOKENS_RUNNER" \
    --skintokens-home "$SKINTOKENS_HOME" \
    --input "$CHARACTER" \
    --output "$RIGGED" \
    --server-timeout "$SKINTOKENS_SERVER_TIMEOUT" \
    --use-transfer
) 2>&1 | tee "$OUTPUT/logs/01_skintokens.log"

echo "[2/7] Analyze the generated SkinTokens joint tree"
"$GVHMR_PY" "$TOPOLOGY_SCRIPT" \
  --input "$RIGGED" \
  --output "$TOPOLOGY_REPORT" \
  2>&1 | tee "$OUTPUT/logs/02_topology.log"

echo "[3/7] Build the SMPL-22 map from topology semantics"
MAPPING_SIDE=${NAQI_MAPPING_SIDE:-left}
case "$MAPPING_SIDE" in
  left)
    MAPPING_SIDE_ARGS=(--x-positive-is-left)
    ;;
  right)
    MAPPING_SIDE_ARGS=(--x-positive-is-right)
    ;;
  *)
    echo "NAQI_MAPPING_SIDE must be 'left' or 'right', got: $MAPPING_SIDE" >&2
    exit 2
    ;;
esac
"$GVHMR_PY" "$MAPPING_SCRIPT" \
  --topology-report "$TOPOLOGY_REPORT" \
  --output "$MAPPING_JSON" \
  "${MAPPING_SIDE_ARGS[@]}" \
  2>&1 | tee "$OUTPUT/logs/03_mapping.log"

echo "[4/7] GVHMR video-to-motion inference"
GVHMR_ARGS=(--video "$VIDEO" --output_root "$GVHMR_ROOT")
if [[ "$CAMERA_MODE" == "static" ]]; then
  GVHMR_ARGS+=(--static_cam)
fi
set +e
(
  cd "$GVHMR_HOME"
  env PYTHONPATH="$GVHMR_HOME" TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD=1 \
    "$GVHMR_PY" tools/demo/demo.py "${GVHMR_ARGS[@]}"
) 2>&1 | tee "$OUTPUT/logs/04_gvhmr.log"
GVHMR_STATUS=${PIPESTATUS[0]}
set -e
if [[ ! -f "$GVHMR_RESULT" ]]; then
  echo "GVHMR did not produce $GVHMR_RESULT (exit $GVHMR_STATUS)" >&2
  if [[ "$GVHMR_STATUS" -eq 0 ]]; then exit 1; else exit "$GVHMR_STATUS"; fi
elif [[ "$GVHMR_STATUS" -ne 0 ]]; then
  echo "GVHMR produced motion but returned $GVHMR_STATUS; continuing for downstream extraction." >&2
fi

echo "[5/7] Export a portable SMPL-22 motion NPZ"
(
  cd "$GVHMR_HOME"
  env PYTHONPATH="$GVHMR_HOME" TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD=1 \
    "$GVHMR_PY" "$EXTRACT_SCRIPT" \
      --input "$GVHMR_RESULT" \
      --output "$MOTION_NPZ" \
      --manifest "$MOTION_MANIFEST" \
      --fps "$FPS"
) 2>&1 | tee "$OUTPUT/logs/05_extract_motion.log"

echo "[6/7] Blender retarget and bake into animated GLB"
"$BLENDER_BIN" --background --python "$APPLY_SCRIPT" -- \
  --character "$RIGGED" \
  --motion "$MOTION_NPZ" \
  --mapping-json "$MAPPING_JSON" \
  --output "$FINAL_GLB" \
  --report "$RETARGET_REPORT" \
  2>&1 | tee "$OUTPUT/logs/06_retarget.log"

echo "[7/7] Structural QA and optional CUDA keyframe renders"
"$GVHMR_PY" "$INSPECT_SCRIPT" "$FINAL_GLB" \
  2>&1 | tee "$STRUCTURE_REPORT"
if [[ "$NAQI_RENDER_KEYFRAMES" == "1" ]]; then
  "$BLENDER_BIN" --background --python "$KEYFRAME_SCRIPT" -- \
    --input "$FINAL_GLB" \
    --output-dir "$OUTPUT/renders/keyframes" \
    --frames "1,80,160" \
    2>&1 | tee "$OUTPUT/logs/07_keyframes.log"
fi

echo
echo "Pipeline complete."
echo "Rigged GLB:    $RIGGED"
echo "Animated GLB:  $FINAL_GLB"
echo "Motion NPZ:    $MOTION_NPZ"
echo "Topology map:  $MAPPING_JSON"
echo "Animation QA:  $STRUCTURE_REPORT"
echo "Keyframe QA:   $OUTPUT/renders/keyframes"
