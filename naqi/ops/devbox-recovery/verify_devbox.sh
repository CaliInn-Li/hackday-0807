#!/usr/bin/env bash
set -Eeuo pipefail

NAQI_HOME=${NAQI_HOME:-/home/naqi}
SERVICE_ROOT=${NAQI_SERVICE_ROOT:-"$NAQI_HOME/demo-services/naqi-backend-25f55c9"}

required=(
  "$NAQI_HOME/GVHMR/.venv310/bin/python"
  "$NAQI_HOME/GVHMR/inputs/checkpoints/gvhmr/gvhmr_siga24_release.ckpt"
  "$NAQI_HOME/GVHMR/inputs/checkpoints/hmr2/epoch=10-step=25000.ckpt"
  "$NAQI_HOME/GVHMR/inputs/checkpoints/vitpose/vitpose-h-multi-coco.pth"
  "$NAQI_HOME/SkinTokens/.venv/bin/python"
  "$NAQI_HOME/SkinTokens/experiments/articulation_xl_quantization_256_token_4/grpo_1400.ckpt"
  "$NAQI_HOME/SkinTokens/experiments/skin_vae_2_10_32768/last.ckpt"
  "$SERVICE_ROOT/repo/naqi/backend/.env"
)
for path in "${required[@]}"; do
  [[ -e "$path" ]] || { echo "MISSING $path" >&2; exit 1; }
done

"$NAQI_HOME/GVHMR/.venv310/bin/python" - <<'PY'
import torch
from pytorch3d.ops import knn_points
assert torch.cuda.is_available()
x = torch.rand(1, 16, 3, device="cuda")
knn_points(x, x, K=1)
print("GVHMR CUDA OK", torch.__version__, torch.cuda.get_device_name(0))
PY

"$NAQI_HOME/SkinTokens/.venv/bin/python" - <<'PY'
import bpy
import torch
assert torch.cuda.is_available()
torch.ones(16, device="cuda").sum().item()
print("SkinTokens CUDA OK", torch.__version__, bpy.app.version_string)
PY

if [[ -x /opt/blender-4.5.12/blender ]]; then
  /opt/blender-4.5.12/blender --version | head -n 1
elif [[ -x /usr/local/bin/blender ]]; then
  /usr/local/bin/blender --version | head -n 1
else
  echo "Blender must be restored from $NAQI_HOME/toolchains/blender-4.5.12-linux-x64.tar.gz" >&2
  exit 1
fi

if curl -fsS http://127.0.0.1:18080/health/live >/dev/null 2>&1; then
  "$SERVICE_ROOT/repo/naqi/deploy/status.sh"
else
  echo "Service is not running; runtime and model verification still passed."
fi
