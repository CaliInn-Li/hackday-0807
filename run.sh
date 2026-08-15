#!/usr/bin/env bash
#
# run.sh — 五个阶段一键运行脚本
#
# 阶段划分（对应 pipeline/五阶段独立运行与产物说明.md）：
#   ① bind      : 固定 SMPL-22 模板 + SkinTokens 蒙皮
#   ② rig       : 固定契约验收 + 语义化 + 压力测试
#   ③ motion    : GVHMR 单目动捕                 (GVHMR tools/demo/demo.py)
#   ④ motionnpz : 动作标准化为 SMPL-22 NPZ       (extract_gvhmr_motion.py)
#   ⑤ retarget  : Blender 重定向/烘焙            (apply_gvhmr_motion.py)
#
# 用法：
#   ./run.sh
#
#   # 从某个阶段开始（1-5），常用于断点续跑
#   ./run.sh --stage 3
#
#   # 跳过某几个阶段（逗号分隔，1-5），常用于复用已有产物
#   ./run.sh --skip 3,4
#
# 说明：
#   * 每步执行前会打印提示；任一步失败立即中止整个脚本，不再继续后续阶段。
#   * --stage 与 --skip 可组合使用：先按 --stage 截断起点，再按 --skip 跳过其中若干阶段。
#   * 被跳过的阶段假定其产物已存在，请自行确认（如阶段③跳过后沿用已有 hmr4d_results.pt）。
#   * 第①步使用 SkinTokens --use-skeleton，只生成蒙皮，不自由生成骨架。
#   * 第②步按参考骨架证明骨数、父子图、左右语义和蒙皮均符合固定契约。
#
set -euo pipefail

# ---------------------------------------------------------------------------
# 可配置变量（按需修改为自己机器上的路径）
# ---------------------------------------------------------------------------
WORK="${PIPELINE_WORK:-/home/naqi/hackday-0815-0234}"
RUN="${PIPELINE_RUN:-$WORK/runs/manual_test}"
VIDEO="${PIPELINE_VIDEO:-$WORK/inputs/action.mp4}"
CHARACTER="${PIPELINE_CHARACTER:-$WORK/inputs/character.glb}"

SKINTOKENS_HOME="${SKINTOKENS_HOME:-/home/naqi/SkinTokens}"
GVHMR_HOME="${GVHMR_HOME:-/home/naqi/GVHMR}"
BLENDER="${BLENDER_BIN:-/usr/local/bin/blender}"
SKINTOKENS_SEED="${SKINTOKENS_SEED:-0}"
SKINTOKENS_USE_POSTPROCESS="${SKINTOKENS_USE_POSTPROCESS:-0}"
PIPELINE_BODY_CENTER_Y="${PIPELINE_BODY_CENTER_Y:-}"

START_STAGE="${START_STAGE:-1}"
SKIP_STAGES="${SKIP_STAGES:-}"   # 逗号分隔的阶段号，如 "3,4"

# 资源/剧本路径
VIDEO_BASE="$(basename "$VIDEO")"
VIDEO_STEM="${VIDEO_BASE%.*}"

GVHMR_RESULT="$RUN/motion/gvhmr/$VIDEO_STEM/hmr4d_results.pt"

# 日志
LOG_DIR="$RUN/logs"
LOG1="$LOG_DIR/01_skintokens.log"
LOG2="$LOG_DIR/02_prepare_rig.log"
LOG3="$LOG_DIR/03_gvhmr.log"
LOG4="$LOG_DIR/04_extract_motion.log"
LOG5="$LOG_DIR/05_retarget.log"
DIAG_JSON="$LOG_DIR/02_topology_diagnostic.json"
SKELETON_TEMPLATE="$WORK/pipeline/config/smpl22_skeleton.json"
SKELETON_INPUT="$RUN/rigging/character_skeleton_input.glb"
SKELETON_REPORT="$RUN/rigging/character_skeleton_fit.json"
LOG0="$LOG_DIR/00_fixed_skeleton.log"

# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------
log()   { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
ok()    { printf '\033[1;32m[OK] %s\033[0m\n' "$*"; }
fail()  { printf '\033[1;31m[FAIL] %s\033[0m\n' "$*" >&2; }

check_environment() {
    local failed=0
    local required=(
        "$SKINTOKENS_HOME/.venv/bin/python"
        "$GVHMR_HOME/.venv310/bin/python"
        "$GVHMR_HOME/tools/demo/demo.py"
        "$BLENDER"
        "$WORK/pipeline/config/smpl22_skeleton.json"
        "$WORK/pipeline/scripts/create_fixed_smpl22_skeleton.py"
        "$WORK/pipeline/scripts/run_skintokens_offline.py"
        "$WORK/pipeline/scripts/prepare_and_test_rig.py"
        "$WORK/pipeline/scripts/apply_gvhmr_motion.py"
    )
    for path in "${required[@]}"; do
        if [[ -e "$path" ]]; then
            echo "[OK] $path"
        else
            echo "[MISSING] $path" >&2
            failed=1
        fi
    done
    if [[ "$failed" -ne 0 ]]; then
        fail "Environment check failed"
        return 1
    fi
    echo "Environment check passed."
}

# 阶段是否在 --skip 列表中
#   should_skip <阶段号>  → 命中返回 0(true)，否则 1(false)
should_skip() {
    local n="$1"
    [[ -z "$SKIP_STAGES" ]] && return 1
    local IFS=','
    local s
    for s in $SKIP_STAGES; do
        [[ "$s" == "$n" ]] && return 0
    done
    return 1
}

# run_step <阶段名> <命令...>
#   执行前打印提示，失败立即中止整个脚本。
run_step() {
    local step_name="$1"; shift
    log "$step_name"
    "$@"
}

# 打印第②步「拓扑门禁失败」的明确提示
topology_hint() {
    cat >&2 <<'EOF'

!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
  [固定契约失败] 第②步产出不符合 smpl22-mixamo-v1 !

  请查看诊断报告：
      LOG_DIR/02_topology_diagnostic.json

  常见原因：固定骨架输入没有被保留、关节图被重排后无法匹配，或蒙皮权重不完整。

  处理办法：
    1) 检查 logs/00_fixed_skeleton.log 与 rigging/character_skeleton_fit.json；
    2) 确认 logs/01_skintokens.log 中 use_skeleton/use_transfer 都为 true；
    3) 不要通过修改 bone_N 固定映射或随机重采样绕过契约门禁。

  ⚠️ 不要靠修改骨骼映射来“救回”坏采样——几何不匹配时语义映射不可靠。
!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
EOF
}

# ---------------------------------------------------------------------------
# 参数解析
# ---------------------------------------------------------------------------
show_help() {
    cat <<EOF
用法：$0 [选项]

选项：
  --stage <1-5>        从指定阶段开始运行（默认 1），用于断点续跑
  --skip <a,b,...>     跳过指定阶段（1-5，逗号分隔，如 3,4），用于复用已有产物
  --check              检查固定骨架管线与外部依赖路径
  -h, --help           显示帮助

所有路径均可用环境变量覆盖：PIPELINE_WORK / PIPELINE_RUN / PIPELINE_VIDEO /
PIPELINE_CHARACTER / SKINTOKENS_HOME / GVHMR_HOME / BLENDER_BIN。
可选：SKINTOKENS_SEED、SKINTOKENS_USE_POSTPROCESS=1、PIPELINE_BODY_CENTER_Y。
EOF
}

START_STAGE_ARG=""
SKIP_STAGES_ARG=""
CHECK_ONLY=0
while [[ $# -gt 0 ]]; do
    case "$1" in
        --stage)
            if [[ -z "${2:-}" ]]; then
                echo "错误：--stage 需要一个数值参数" >&2
                exit 2
            fi
            START_STAGE_ARG="$2"
            shift 2
            ;;
        --skip)
            if [[ -z "${2:-}" ]]; then
                echo "错误：--skip 需要一个逗号分隔的数值参数（如 3,4）" >&2
                exit 2
            fi
            SKIP_STAGES_ARG="$2"
            shift 2
            ;;
        --check)
            CHECK_ONLY=1
            shift
            ;;
        -h|--help)
            show_help
            exit 0
            ;;
        *)
            echo "错误：未知参数 $1" >&2
            show_help >&2
            exit 2
            ;;
    esac
done

if [[ -n "$START_STAGE_ARG" ]]; then
    if ! [[ "$START_STAGE_ARG" =~ ^[1-5]$ ]]; then
        echo "错误：--stage 只能取 1-5，收到 '$START_STAGE_ARG'" >&2
        exit 2
    fi
    START_STAGE="$START_STAGE_ARG"
fi

if [[ "$CHECK_ONLY" == "1" ]]; then
    check_environment
    exit 0
fi

if [[ -n "$SKIP_STAGES_ARG" ]]; then
    # 校验 --skip 中的每个阶段号都合法（1-5）
    SKIP_STAGES_ARG="${SKIP_STAGES_ARG// /}"   # 去掉空格
    cleaned=""
    IFS=','
    set -f
    for s in $SKIP_STAGES_ARG; do
        if ! [[ "$s" =~ ^[1-5]$ ]]; then
            echo "错误：--skip 的值只能取 1-5，收到 '$s'" >&2
            exit 2
        fi
        cleaned="${cleaned:+$cleaned,}$s"
    done
    set +f
    unset IFS
    SKIP_STAGES="$cleaned"
fi

# ---------------------------------------------------------------------------
# 运行前检查
# ---------------------------------------------------------------------------
log "一键运行五阶段管线"
echo "  WORK      = $WORK"
echo "  RUN       = $RUN"
echo "  VIDEO     = $VIDEO"
echo "  CHARACTER = $CHARACTER"
echo "  起始阶段  = $START_STAGE"
[[ -n "$SKIP_STAGES" ]] && echo "  跳过阶段  = $SKIP_STAGES"

mkdir -p "$RUN/rigging" "$RUN/motion" "$RUN/renders" "$LOG_DIR"

# ---------------------------------------------------------------------------
# 阶段 ① 固定 SMPL-22 + SkinTokens 仅蒙皮
# ---------------------------------------------------------------------------
if [[ "$START_STAGE" -le 1 ]] && ! should_skip 1; then
    run_step "阶段 ①A 拟合并嵌入固定 SMPL-22 骨架" \
        bash -c '
            set -o pipefail
            extra=()
            if [[ -n "$7" ]]; then extra+=(--body-center-y "$7"); fi
            "$1" --background --python-exit-code 1 \
                --python "$2/pipeline/scripts/create_fixed_smpl22_skeleton.py" -- \
                --input "$3" \
                --template "$4" \
                --output "$5" \
                --report "$6" \
                "${extra[@]}" \
                2>&1 | tee "$8"
        ' _ "$BLENDER" "$WORK" "$CHARACTER" "$SKELETON_TEMPLATE" \
            "$SKELETON_INPUT" "$SKELETON_REPORT" "$PIPELINE_BODY_CENTER_Y" "$LOG0"
    ok "阶段①A完成：$SKELETON_INPUT"

    run_step "阶段 ①B SkinTokens 固定骨架蒙皮（只生成权重）" \
        bash -c '
            set -o pipefail
            extra=()
            if [[ "$7" == "1" ]]; then extra+=(--use-postprocess); fi
            cd "$1"
            exec "$2/.venv/bin/python" -u "$3/pipeline/scripts/run_skintokens_offline.py" \
                --skintokens-home "$1" \
                --input "$4" \
                --output "$5/rigging/character_rigged_raw.glb" \
                --seed "$6" \
                --use-skeleton \
                --use-transfer \
                "${extra[@]}" \
                2>&1 | tee "$5/logs/01_skintokens.log"
        ' _ "$SKINTOKENS_HOME" "$SKINTOKENS_HOME" "$WORK" "$SKELETON_INPUT" "$RUN" \
            "$SKINTOKENS_SEED" "$SKINTOKENS_USE_POSTPROCESS"
    ok "阶段①完成：$RUN/rigging/character_rigged_raw.glb"
else
    log "跳过阶段①（沿用已有产物）"
fi

# ---------------------------------------------------------------------------
# 阶段 ② 清理/语义化（含压力测试 + 拓扑门禁）
# ---------------------------------------------------------------------------
if [[ "$START_STAGE" -le 2 ]] && ! should_skip 2; then
    if ! run_step "阶段 ② 固定 SMPL-22 契约验收 + 语义化 + 压力测试" \
        bash -c '
            set -o pipefail
            "$1" --background --python-exit-code 1 \
                --python "$2/pipeline/scripts/prepare_and_test_rig.py" -- \
                --input "$3/rigging/character_rigged_raw.glb" \
                --reference-skeleton "$3/rigging/character_skeleton_input.glb" \
                --clean-output "$3/rigging/character_rigged_clean.glb" \
                --animated-output "$3/rigging/character_rig_test.glb" \
                --render-dir "$3/renders/rig_test" \
                --diagnostic "$3/logs/02_topology_diagnostic.json" \
                2>&1 | tee "$3/logs/02_prepare_rig.log"
        ' _ "$BLENDER" "$WORK" "$RUN"; then
        fail "第②步固定 SMPL-22 契约验收失败"
        if grep -qiE "fixed smpl22|Skin weight contract failed|violates fixed" "$LOG2" 2>/dev/null; then
            topology_hint
            echo "诊断报告：$DIAG_JSON" >&2
        else
            echo "日志：$LOG2" >&2
        fi
        exit 1
    fi
    ok "阶段②完成：$RUN/rigging/character_rigged_clean.glb"
else
    log "跳过阶段②（沿用已有产物）"
fi

# ---------------------------------------------------------------------------
# 阶段 ③ GVHMR 动作提取
# ---------------------------------------------------------------------------
if [[ "$START_STAGE" -le 3 ]] && ! should_skip 3; then
    run_step "阶段 ③ GVHMR 单目动捕（产出 hmr4d_results.pt）" \
        bash -c '
            cd "$1"
            env PYTHONPATH="$1" \
                TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD=1 \
                "$1/.venv310/bin/python" tools/demo/demo.py \
                    --video "$2" \
                    --output_root "$3/motion/gvhmr" \
                    --static_cam \
                    2>&1 | tee "$3/logs/03_gvhmr.log"
        ' _ "$GVHMR_HOME" "$VIDEO" "$RUN"

    # 核心产物判定：即使最后只因 ffmpeg 拼接可视化 mp4 失败，
    # 只要 hmr4d_results.pt 存在即视为动作提取成功。
    if [[ ! -f "$GVHMR_RESULT" ]]; then
        fail "阶段③核心产物缺失：$GVHMR_RESULT"
        exit 1
    fi
    ls -lh "$GVHMR_RESULT"
    ok "阶段③完成：$GVHMR_RESULT"
else
    log "跳过阶段③：沿用已有 $GVHMR_RESULT"
fi

# ---------------------------------------------------------------------------
# 阶段 ④ 动作标准化为 SMPL-22 NPZ
# ---------------------------------------------------------------------------
if [[ "$START_STAGE" -le 4 ]] && ! should_skip 4; then
    run_step "阶段 ④ 动作标准化（产出 ${VIDEO_STEM}_smpl22.npz）" \
        bash -c '
            cd "$1"
            env PYTHONPATH="$1" \
                TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD=1 \
                "$1/.venv310/bin/python" "$2/pipeline/scripts/extract_gvhmr_motion.py" \
                    --input "$3" \
                    --output "$4/motion/"$5"_smpl22.npz" \
                    --manifest "$4/motion/"$5"_motion_manifest.json" \
                    2>&1 | tee "$4/logs/04_extract_motion.log"
        ' _ "$GVHMR_HOME" "$WORK" "$GVHMR_RESULT" "$RUN" "$VIDEO_STEM"
    ok "阶段④完成：$RUN/motion/${VIDEO_STEM}_smpl22.npz"
else
    log "跳过阶段④（沿用已有产物）"
fi

# ---------------------------------------------------------------------------
# 阶段 ⑤ 重定向/烘焙
# ---------------------------------------------------------------------------
if [[ "$START_STAGE" -le 5 ]] && ! should_skip 5; then
    run_step "阶段 ⑤ Blender 重定向/烘焙（产出最终动画 GLB）" \
        bash -c '
            "$1" --background --python-exit-code 1 \
                --python "$2/pipeline/scripts/apply_gvhmr_motion.py" -- \
                --character "$3/rigging/character_rigged_clean.glb" \
                --motion "$3/motion/"$4"_smpl22.npz" \
                --output "$3/motion/character_"$4"_animated.glb" \
                --report "$3/motion/"$4"_retarget_report.json" \
                --preview-dir "$3/renders/retarget" \
                2>&1 | tee "$3/logs/05_retarget.log"
        ' _ "$BLENDER" "$WORK" "$RUN" "$VIDEO_STEM"
    ok "阶段⑤完成：$RUN/motion/character_${VIDEO_STEM}_animated.glb"
else
    log "跳过阶段⑤（沿用已有产物）"
fi

# ---------------------------------------------------------------------------
# 完成
# ---------------------------------------------------------------------------
ok "全部阶段执行完毕"
echo "最终产物：$RUN/motion/character_${VIDEO_STEM}_animated.glb"
echo "日志目录：$LOG_DIR"
