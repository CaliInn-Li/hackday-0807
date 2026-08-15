# naqi：MP4 到动画 GLB

`naqi/` 是本项目的干净复现包。它只保留当前有效的代码、数据契约、最终资产和必要 QA 结果；旧版映射、压力测试、临时预览和中间 GLB 已移除。

## 流程总览

```text
MP4 + 无骨骼 GLB
  1. SkinTokens --use-transfer：生成骨架、蒙皮权重，并保留原始网格/PBR
  2. 拓扑分析：识别 Pelvis、Spine、手臂、腿和额外手指骨
  3. 拓扑映射：生成 SkinTokens bone -> SMPL-22 映射
  4. GVHMR：在 CUDA GPU 上从视频推理 SMPL-X 动作
  5. 动作契约：导出 SMPL-22 rotations/translations 的 NPZ
  6. Blender：全局旋转转换、绑定姿态修正、根位移缩放、逐帧烘焙
  7. QA：检查 GLB skin/蒙皮属性/动画，并渲染少量关键帧 PNG
  ↓
 骨骼+蒙皮 GLB + 带动画 GLB
```

当前重定向不是按 `bone_0、bone_1...` 猜编号，而是使用父子关系、分叉数量、链长度和空间侧别。SMPL-22 的局部旋转会先累积为全局旋转，再转换到目标 GLB 的绑定姿态，最后还原为目标骨骼局部旋转。

## 目录

```text
naqi/
├─ README.md
├─ input/                         # 原始、无骨骼的角色 GLB
│  ├─ 雪帽少女.glb
│  └─ 冰雪射手.glb
├─ output/
│  ├─ rigged/                     # SkinTokens 生成的骨骼+蒙皮 GLB
│  ├─ animated/                   # 当前四个最终动画 GLB
│  ├─ reports/topology/           # 骨树分析报告
│  ├─ reports/retarget/           # 四个动画的重定向报告
│  └─ preview/                    # video2 的最终关键帧 PNG
├─ motion/                        # 可复用的 SMPL-22 动作契约和 manifest
├─ config/                        # SMPL-22 契约和示例拓扑映射
├─ scripts/                       # 唯一运行入口及必要阶段脚本
└─ docs/                          # 社区插件/参数解码参考
```

视频没有复制进这个目录；运行时直接把 MP4 路径传给脚本。`motion/video1_smpl22.npz` 和 `motion/video2_smpl22.npz` 是已经提取好的动作数据契约，不是临时日志。

## 运行环境

脚本假设远程 GPU 机器已经准备好：

```text
SKINTOKENS_HOME=/home/naqi/SkinTokens
GVHMR_HOME=/home/naqi/GVHMR
BLENDER_BIN=/usr/local/bin/blender
```

也可以通过环境变量改成其他路径。GVHMR 使用 `.venv310` 的 CUDA/PyTorch；Blender 的骨骼矩阵和关键帧写入主要是 CPU，关键帧渲染脚本会优先尝试 Cycles CUDA/OptiX。

## 一键运行

先检查环境：

```bash
cd /path/to/hackday-0807/naqi/scripts
bash run_naqi_pipeline.sh --check
```

然后传入一个 MP4、一个无骨骼 GLB 和输出目录：

```bash
bash run_naqi_pipeline.sh \
  /data/input/action.mp4 \
  /data/input/character.glb \
  /data/run/character_action \
  static
```

最后一个参数可选：

- `static`：固定机位，传给 GVHMR `--static_cam`；
- `moving`：移动机位，不传 `--static_cam`。

角色 GLB 的 x 正方向如果对应角色右侧，设置：

```bash
NAQI_MAPPING_SIDE=right bash run_naqi_pipeline.sh action.mp4 character.glb output moving
```

可选变量：

```bash
NAQI_FPS=24                 # 不设置时优先用 ffprobe，失败后默认 24
NAQI_RENDER_KEYFRAMES=0    # 只要 GLB/报告、不渲染 PNG 时关闭
SKINTOKENS_SERVER_TIMEOUT=600
```

## 一键脚本生成的文件

假设输出目录是 `output/character_action/`：

```text
output/character_action/
├─ inputs/character.glb                    # 输入快照
├─ inputs/action.mp4                       # 输入快照
├─ rigging/character_rigged.glb            # 阶段 1：SkinTokens 输出
├─ reports/topology.json                   # 阶段 2：骨树报告
├─ reports/topology_mapping.json           # 阶段 3：22 骨映射
├─ motion/gvhmr/<video>/hmr4d_results.pt   # 阶段 4：GVHMR 原始结果
├─ motion/action_smpl22.npz                # 阶段 5：便携动作
├─ motion/action_motion_manifest.json      # 帧数/FPS/时长/平移范围
├─ outputs/character_action_animated.glb   # 阶段 6：最终动画 GLB
├─ reports/retarget.json                   # 重定向参数和帧数
├─ reports/animation.json                  # 阶段 7：GLB 结构检查
├─ renders/keyframes/frame_*.png           # 阶段 7：关键帧变形检查
└─ logs/                                   # 每个阶段的日志
```

动画直接保存在 GLB 的 `animations` 中，不需要生成 MP4；用 Blender、Three.js、Babylon.js 或其他 glTF viewer 打开 `outputs/*_animated.glb` 即可播放。

## 分阶段运行

一键脚本已经按下面顺序执行。需要定位问题时，可以复用这些命令。

### 1. SkinTokens 生成骨骼和蒙皮

输入必须是无骨骼 GLB。`--use-transfer` 会把预测的骨骼/权重转回原始网格，避免把归一化白模误当作最终角色：

```bash
SKIN_PY="$SKINTOKENS_HOME/.venv/bin/python"
"$SKIN_PY" scripts/run_skintokens_offline.py \
  --skintokens-home "$SKINTOKENS_HOME" \
  --input input/雪帽少女.glb \
  --output output/rigged/雪帽少女_rigged.glb \
  --server-timeout 600 \
  --use-transfer
```

### 2. 分析 SkinTokens 骨树

```bash
"$GVHMR_HOME/.venv310/bin/python" scripts/inspect_skin_tokens_topology.py \
  --input output/rigged/雪帽少女_rigged.glb \
  --output output/reports/topology/snow_girl_topology.json
```

### 3. 生成 SMPL-22 拓扑映射

```bash
"$GVHMR_HOME/.venv310/bin/python" scripts/build_topology_mapping.py \
  --topology-report output/reports/topology/snow_girl_topology.json \
  --output output/reports/topology/snow_girl_mapping.json \
  --x-positive-is-left
```

### 4. GVHMR 视频动作推理

```bash
GVHMR_PY="$GVHMR_HOME/.venv310/bin/python"
env PYTHONPATH="$GVHMR_HOME" TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD=1 \
  "$GVHMR_PY" "$GVHMR_HOME/tools/demo/demo.py" \
  --video /data/input/action.mp4 \
  --output_root /data/run/character_action/motion/gvhmr \
  --static_cam
```

原始结果通常在 `<output_root>/<video-stem>/hmr4d_results.pt`。固定机位不确定时，去掉 `--static_cam`。

### 5. 导出 SMPL-22 NPZ

```bash
"$GVHMR_PY" scripts/extract_gvhmr_motion.py \
  --input /data/run/character_action/motion/gvhmr/action/hmr4d_results.pt \
  --output /data/run/character_action/motion/action_smpl22.npz \
  --manifest /data/run/character_action/motion/action_motion_manifest.json \
  --fps 24
```

此步骤需要 CUDA，因为会用 GVHMR 的 SMPL-X 模型计算源角色高度并进行动作数据检查。

### 6. Blender 重定向并导出动画 GLB

```bash
"$BLENDER_BIN" --background --python scripts/apply_gvhmr_motion.py -- \
  --character output/rigged/雪帽少女_rigged.glb \
  --motion /data/run/character_action/motion/action_smpl22.npz \
  --mapping-json /data/run/character_action/reports/topology_mapping.json \
  --output /data/run/character_action/outputs/雪帽少女_action_animated.glb \
  --report /data/run/character_action/reports/retarget.json
```

### 7. 结构和变形 QA

```bash
"$GVHMR_PY" scripts/inspect_glb_animation.py \
  /data/run/character_action/outputs/雪帽少女_action_animated.glb \
  > /data/run/character_action/reports/animation.json

"$BLENDER_BIN" --background --python scripts/render_glb_keyframes.py -- \
  --input /data/run/character_action/outputs/雪帽少女_action_animated.glb \
  --output-dir /data/run/character_action/renders/keyframes \
  --frames 1,80,160
```

验收至少应看到：`skins=1`、有 `JOINTS_0/WEIGHTS_0`、`animations=1`、动画时长和视频一致；关键帧再检查脚底滑动、手臂扭曲、根节点漂移和身体比例。

## 本目录保留的最终资产

- `output/rigged/雪帽少女_rigged.glb`：SkinTokens 生成的 46-joint 骨骼+蒙皮 GLB。
- `output/rigged/冰雪射手_rigged.glb`：SkinTokens 生成的 22-joint 骨骼+蒙皮 GLB。
- `output/animated/雪帽少女_video2_animated.glb`：当前修正后最满意的 video2 结果。
- `output/animated/雪帽少女_video1_animated.glb`、`冰雪射手_video1_animated.glb`、`冰雪射手_video2_animated.glb`：其余三组最终候选。
- `output/preview/`：雪帽少女和冰雪射手 video2 的关键帧 PNG。

雪帽少女的额外手指骨会保留在 GLB 中，但当前 GVHMR 输出是 SMPL-22，不包含手指姿态；弓箭等道具也不会自动获得独立动作。新角色如果没有清晰的躯干、双臂和双腿链，自动映射应停在报告阶段，人工确认映射后再重定向。

## 依赖边界

GVHMR 官方仓库提供推理和 `.pt` 输出，没有官方 Blender 插件。社区 GVHMR/HaMeR Blender 工具只作为轴角解码、坐标修正和逐帧关键帧的参考；本目录的实际入口是 `scripts/run_naqi_pipeline.sh`，而不是社区插件。
