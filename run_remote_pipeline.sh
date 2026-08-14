#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
PIPELINE_ROOT="$PROJECT_ROOT/pipeline"
SCRIPT_DIR="$PIPELINE_ROOT/scripts"
CONFIG_DIR="$PIPELINE_ROOT/config"

SKINTOKENS_HOME=${SKINTOKENS_HOME:-"$HOME/SkinTokens"}
GVHMR_HOME=${GVHMR_HOME:-"$HOME/GVHMR"}
BLENDER_BIN=${BLENDER_BIN:-/usr/local/bin/blender}
SKIN_PY="$SKINTOKENS_HOME/.venv/bin/python"
GVHMR_PY="$GVHMR_HOME/.venv310/bin/python"
MAPPING="$CONFIG_DIR/skintokens_mixamo_mapping.json"

STATIC_REQUIREMENTS=(
  "$SKIN_PY"
  "$GVHMR_PY"
  "$BLENDER_BIN"
  "$MAPPING"
  "$SCRIPT_DIR/run_skintokens_offline.py"
  "$SCRIPT_DIR/inspect_rig.py"
  "$SCRIPT_DIR/prepare_and_test_rig.py"
  "$SCRIPT_DIR/extract_gvhmr_motion.py"
  "$SCRIPT_DIR/apply_gvhmr_motion.py"
)

check_environment() {
  local failed=0
  echo "Project root: $PROJECT_ROOT"
  for path in "${STATIC_REQUIREMENTS[@]}"; do
    if [[ -e "$path" ]]; then
      echo "[OK] $path"
    else
      echo "[MISSING] $path" >&2
      failed=1
    fi
  done
  if [[ "$failed" -ne 0 ]]; then
    echo "Environment check failed. Set SKINTOKENS_HOME, GVHMR_HOME, or BLENDER_BIN when using non-default locations." >&2
    return 1
  fi
  echo "Environment check passed."
}

if [[ "${1:-}" == "--check" ]]; then
  [[ $# -eq 1 ]] || { echo "Usage: $0 --check" >&2; exit 2; }
  check_environment
  exit 0
fi

if [[ $# -lt 3 || $# -gt 4 ]]; then
  echo "Usage: $0 <video.mp4> <character.glb> <output_dir> [static|moving]" >&2
  echo "       $0 --check" >&2
  exit 2
fi

check_environment
VIDEO=$(realpath "$1")
CHARACTER=$(realpath "$2")
OUTPUT=$(realpath -m "$3")
CAMERA_MODE=${4:-static}

for path in "$VIDEO" "$CHARACTER"; do
  [[ -f "$path" ]] || { echo "Missing input file: $path" >&2; exit 1; }
done
[[ "$CAMERA_MODE" == static || "$CAMERA_MODE" == moving ]] || {
  echo "Camera mode must be 'static' or 'moving'" >&2
  exit 2
}

mkdir -p "$OUTPUT"/{rigging,motion,renders,logs}
RIGGED="$OUTPUT/rigging/character_rigged_raw.glb"
CLEAN="$OUTPUT/rigging/character_rigged_clean.glb"
RIG_TEST="$OUTPUT/rigging/character_rig_test.glb"
GVHMR_ROOT="$OUTPUT/motion/gvhmr"
VIDEO_BASE=$(basename "$VIDEO")
VIDEO_STEM=${VIDEO_BASE%.*}
GVHMR_RESULT="$GVHMR_ROOT/$VIDEO_STEM/hmr4d_results.pt"
MOTION_NPZ="$OUTPUT/motion/${VIDEO_STEM}_smpl22.npz"
FINAL_GLB="$OUTPUT/motion/character_${VIDEO_STEM}_animated.glb"

echo "[1/5] SkinTokens automatic rigging"
(
  cd "$SKINTOKENS_HOME"
  "$SKIN_PY" "$SCRIPT_DIR/run_skintokens_offline.py" \
    --skintokens-home "$SKINTOKENS_HOME" \
    --input "$CHARACTER" \
    --output "$RIGGED" \
    --use-transfer
) 2>&1 | tee "$OUTPUT/logs/01_skintokens.log"

echo "[2/5] Clean rig, assign semantic Mixamo names, and make a stress-test animation"
"$BLENDER_BIN" --background --python "$SCRIPT_DIR/prepare_and_test_rig.py" -- \
  --input "$RIGGED" \
  --mapping "$MAPPING" \
  --clean-output "$CLEAN" \
  --animated-output "$RIG_TEST" \
  --render-dir "$OUTPUT/renders/rig_test" \
  2>&1 | tee "$OUTPUT/logs/02_prepare_rig.log"

echo "[3/5] GVHMR video-to-motion"
GVHMR_ARGS=(--video "$VIDEO" --output_root "$GVHMR_ROOT")
if [[ "$CAMERA_MODE" == static ]]; then GVHMR_ARGS+=(--static_cam); fi
set +e
(
  cd "$GVHMR_HOME"
  env PYTHONPATH="$GVHMR_HOME" TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD=1 \
    "$GVHMR_PY" tools/demo/demo.py "${GVHMR_ARGS[@]}"
) 2>&1 | tee "$OUTPUT/logs/03_gvhmr.log"
GVHMR_STATUS=${PIPESTATUS[0]}
set -e
if [[ ! -f "$GVHMR_RESULT" ]]; then
  echo "GVHMR failed before producing $GVHMR_RESULT (exit $GVHMR_STATUS)" >&2
  if [[ "$GVHMR_STATUS" -eq 0 ]]; then exit 1; else exit "$GVHMR_STATUS"; fi
elif [[ "$GVHMR_STATUS" -ne 0 ]]; then
  echo "Warning: GVHMR core motion succeeded, but an optional render/merge step failed (exit $GVHMR_STATUS). Continuing." >&2
fi

echo "[4/5] Convert GVHMR output to portable SMPL-22 motion"
(
  cd "$GVHMR_HOME"
  env PYTHONPATH="$GVHMR_HOME" TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD=1 \
    "$GVHMR_PY" "$SCRIPT_DIR/extract_gvhmr_motion.py" \
      --input "$GVHMR_RESULT" \
      --output "$MOTION_NPZ" \
      --manifest "$OUTPUT/motion/${VIDEO_STEM}_motion_manifest.json"
) 2>&1 | tee "$OUTPUT/logs/04_extract_motion.log"

echo "[5/5] Retarget and bake animation into game-ready GLB"
"$BLENDER_BIN" --background --python "$SCRIPT_DIR/apply_gvhmr_motion.py" -- \
  --character "$CLEAN" \
  --motion "$MOTION_NPZ" \
  --output "$FINAL_GLB" \
  --report "$OUTPUT/motion/${VIDEO_STEM}_retarget_report.json" \
  --preview-dir "$OUTPUT/renders/retarget" \
  2>&1 | tee "$OUTPUT/logs/05_retarget.log"

echo "Pipeline complete"
echo "Final animated GLB: $FINAL_GLB"
echo "GVHMR output directory: $GVHMR_ROOT/$VIDEO_STEM"
echo "QA renders: $OUTPUT/renders"
