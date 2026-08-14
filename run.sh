#!/usr/bin/env bash
#
# run.sh — 五个阶段一键运行脚本
#
# 阶段划分（对应 pipeline/五阶段独立运行与产物说明.md）：
#   ① bind      : SkinTokens 绑骨/蒙皮           (run_skintokens_offline.py)
#   ② rig       : Blender 清理 + 语义化骨骼      (prepare_and_test_rig.py)
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
# 说明：
#   * 每步执行前会打印提示；任一步失败立即中止整个脚本，不再继续后续阶段。
#   * 第②步含「拓扑门禁」：若产出 skeletons 为非标准 22 骨 humanoid，
#     脚本会识别报错关键词并给出明确提示，指向 "logs/02_topology_diagnostic.json"，
#     必须回第①步重新采样（--use-transfer），不能靠改映射救回。
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

START_STAGE="${START_STAGE:-1}"

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

# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------
log()   { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
ok()    { printf '\033[1;32m[OK] %s\033[0m\n' "$*"; }
fail()  { printf '\033[1;31m[FAIL] %s\033[0m\n' "$*" >&2; }

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
  [拓扑门禁失败] 第②步产出 skeletons 不是标准的 22 骨 humanoid !

  请查看诊断报告：
      LOG_DIR/02_topology_diagnostic.json

  常见原因：SkinTokens 采样出了非标准骨架（骨数 != 22、单根、肢体段数 > 4）。

  处理办法：
    1) 回第①步重新运行 SkinTokens 采样（务必带 --use-transfer 保留原网格尺寸），
       直到得到 22 骨 humanoid；
    2) 或先修复网格拓扑，再进行语义化骨骼重命名。

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
  -h, --help           显示帮助

所有路径均可用环境变量覆盖：PIPELINE_WORK / PIPELINE_RUN / PIPELINE_VIDEO /
PIPELINE_CHARACTER / SKINTOKENS_HOME / GVHMR_HOME / BLENDER_BIN。
EOF
}

START_STAGE_ARG=""
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

# ---------------------------------------------------------------------------
# 运行前检查
# ---------------------------------------------------------------------------
log "一键运行五阶段管线"
echo "  WORK      = $WORK"
echo "  RUN       = $RUN"
echo "  VIDEO     = $VIDEO"
echo "  CHARACTER = $CHARACTER"
echo "  起始阶段  = $START_STAGE"

mkdir -p "$RUN/rigging" "$RUN/motion" "$RUN/renders" "$LOG_DIR"

# ---------------------------------------------------------------------------
# 阶段 ① SkinTokens 绑骨/蒙皮
# ---------------------------------------------------------------------------
if [[ "$START_STAGE" -le 1 ]]; then
    run_step "阶段 ① SkinTokens 绑骨/蒙皮（内含拓扑门禁前采样）" \
        bash -c '
            cd "$1"
            exec "$2/.venv/bin/python" -u "$3/pipeline/scripts/run_skintokens_offline.py" \
                --skintokens-home "$1" \
                --input "$4" \
                --output "$5/rigging/character_rigged_raw.glb" \
                --use-transfer \
                2>&1 | tee "$5/logs/01_skintokens.log"
        ' _ "$SKINTOKENS_HOME" "$SKINTOKENS_HOME" "$WORK" "$CHARACTER" "$RUN"
    ok "阶段①完成：$RUN/rigging/character_rigged_raw.glb"
else
    log "跳过阶段①（--stage $START_STAGE）"
fi

# ---------------------------------------------------------------------------
# 阶段 ② 清理/语义化（含压力测试 + 拓扑门禁）
# ---------------------------------------------------------------------------
if [[ "$START_STAGE" -le 2 ]]; then
    run_step "阶段 ② Blender 清理 + 语义化骨骼（含拓扑门禁，非标准 22 骨会中止）" \
        bash -c '
            "$1" --background \
                --python "$2/pipeline/scripts/prepare_and_test_rig.py" -- \
                --input "$3/rigging/character_rigged_raw.glb" \
                --mapping "$2/pipeline/config/skintokens_mixamo_mapping.json" \
                --clean-output "$3/rigging/character_rigged_clean.glb" \
                --animated-output "$3/rigging/character_rig_test.glb" \
                --render-dir "$3/renders/rig_test" \
                --diagnostic "$3/logs/02_topology_diagnostic.json" \
                2>&1 | tee "$3/logs/02_prepare_rig.log"
        ' _ "$BLENDER" "$WORK" "$RUN"

    # 拓扑门禁：即使 prepare_and_test_rig.py 因 RuntimeError 异常退出，
    # 也会经由上面的 set -e 触发失败；此处再对日志做关键词兜底，给出明确提示。
    if grep -qiE "not a standard 22-bone humanoid|refusing to apply semantic mapping|non-standard skeleton" "$LOG2" 2>/dev/null; then
        fail "第②步拓扑门禁失败：skeletons 不是标准的 22 骨 humanoid"
        topology_hint
        echo "诊断报告：$DIAG_JSON" >&2
        exit 1
    fi
    ok "阶段②完成：$RUN/rigging/character_rigged_clean.glb"
else
    log "跳过阶段②（--stage $START_STAGE）"
fi

# ---------------------------------------------------------------------------
# 阶段 ③ GVHMR 动作提取
# ---------------------------------------------------------------------------
if [[ "$START_STAGE" -le 3 ]]; then
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
    log "跳过阶段③（--stage $START_STAGE）：沿用已有 $GVHMR_RESULT"
fi

# ---------------------------------------------------------------------------
# 阶段 ④ 动作标准化为 SMPL-22 NPZ
# ---------------------------------------------------------------------------
if [[ "$START_STAGE" -le 4 ]]; then
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
    log "跳过阶段④（--stage $START_STAGE）"
fi

# ---------------------------------------------------------------------------
# 阶段 ⑤ 重定向/烘焙
# ---------------------------------------------------------------------------
if [[ "$START_STAGE" -le 5 ]]; then
    run_step "阶段 ⑤ Blender 重定向/烘焙（产出最终动画 GLB）" \
        bash -c '
            "$1" --background \
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
    log "跳过阶段⑤（--stage $START_STAGE）"
fi

# ---------------------------------------------------------------------------
# 完成
# ---------------------------------------------------------------------------
ok "全部阶段执行完毕"
echo "最终产物：$RUN/motion/character_${VIDEO_STEM}_animated.glb"
echo "日志目录：$LOG_DIR"
