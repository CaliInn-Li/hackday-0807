# naqi：MP4 到动画 GLB 的可复刻流水线

这个目录是 Hackday 当前角色动作实验的自包含工作包。目标输入是：

```text
一个单人动作 MP4 + 一个没有骨骼的角色 GLB
        │
        ├─ SkinTokens：生成骨架、蒙皮权重，并转回原始网格
        ├─ 拓扑分析：根据父子关系、分叉和链结构识别身体主干
        ├─ GVHMR：从视频提取 SMPL-X 参数
        ├─ SMPL-22：导出便携动作数据
        └─ Blender：按绑定姿态重定向、逐帧烘焙并导出 GLB
        │
        ├─ character_rigged.glb
        └─ character_video_animated.glb
```

## 给其他 AI 的一键复刻入口

这条命令在已经准备好 GVHMR、SkinTokens 和 Blender 的 Linux GPU 服务器上执行。当前验证过的默认目录是：

```bash
export SKINTOKENS_HOME=/home/naqi/SkinTokens
export GVHMR_HOME=/home/naqi/GVHMR
export BLENDER_BIN=/usr/local/bin/blender

cd /home/naqi/hackday-character-pipeline/naqi/scripts
bash run_naqi_pipeline.sh \
  /data/input/action.mp4 \
  /data/input/character.glb \
  /data/output/character_action \
  static
```

最后一个参数是相机模式：

- `static`：固定机位视频，给 GVHMR 传 `--static_cam`；
- `moving`：相机可能移动的视频，不传这个参数。

如果角色 GLB 的 x 正方向对应角色右侧，而不是默认的左侧，使用：

```bash
NAQI_MAPPING_SIDE=right bash run_naqi_pipeline.sh action.mp4 character.glb output moving
```

运行前可先检查远程环境：

```bash
bash run_naqi_pipeline.sh --check
```

脚本位置是 [`scripts/run_naqi_pipeline.sh`](scripts/run_naqi_pipeline.sh)。它不会生成 MP4，而是生成 GLB 内置动画和少量关键帧 PNG 供检查。

## 从本地上传到 GPU 服务器

如果 MP4 和 GLB 在本地 Windows 机器上，可以先上传，再在服务器执行上面的命令：

```bash
scp -P <SSH_PORT> action.mp4 character.glb \
  <REMOTE_USER>@<GPU_HOST>:/data/input/
```

服务器不可达时先检查 SSH/VPN/端口；网络超时不能当成 GVHMR 或 SkinTokens 模型错误。实际服务器地址、账号、端口和代理从管理员/SSH 配置取得，不要写入仓库。

## 输出目录

一次运行会得到类似下面的结构：

```text
output/
├─ inputs/character.glb                 # 输入快照
├─ inputs/action.mp4                    # 输入快照
├─ rigging/character_rigged.glb         # SkinTokens 生成的骨骼+蒙皮 GLB
├─ motion/gvhmr/<video>/hmr4d_results.pt # GVHMR 原始结果
├─ motion/action_smpl22.npz             # 便携 SMPL-22 动作
├─ motion/action_motion_manifest.json   # 帧数、FPS、时长、平移范围
├─ outputs/character_action_animated.glb # 最终动画 GLB
├─ reports/topology.json                # GLB 骨树分析
├─ reports/topology_mapping.json        # 自动生成的 22 关节映射
├─ reports/retarget.json                # 重定向报告
├─ reports/animation.json               # GLB 结构检查
├─ renders/keyframes/*.png              # Blender/Cycles 关键帧检查
└─ logs/                                # 每一步的日志
```

最终动画不是另一个视频文件。播放器、网页 glTF viewer 或 Blender 直接打开 `outputs/*_animated.glb`，选择其中的 Action/Animation，就能播放动画。

## 代码分工

- [`scripts/run_skintokens_offline.py`](scripts/run_skintokens_offline.py)：调用 SkinTokens 原始 CLI，`--use-transfer` 把生成的骨架/蒙皮转回输入网格。
- [`scripts/inspect_skin_tokens_topology.py`](scripts/inspect_skin_tokens_topology.py)：不依赖 Blender 读取 GLB，分析根节点、躯干、手臂、腿和手指分支。
- [`scripts/build_topology_mapping.py`](scripts/build_topology_mapping.py)：把拓扑报告中的 `Pelvis/Shoulder/Elbow/...` 语义槽转换为 SMPL-22 索引。
- [`scripts/extract_gvhmr_motion.py`](scripts/extract_gvhmr_motion.py)：从 GVHMR `.pt` 导出 `rotations`、`translations`、`fps` 和 `joint_names`。
- [`scripts/apply_gvhmr_motion.py`](scripts/apply_gvhmr_motion.py)：在 Blender 中读取带蒙皮 GLB，按绑定姿态重定向并逐帧写入关键帧。
- [`scripts/inspect_glb_animation.py`](scripts/inspect_glb_animation.py)：检查 `skins`、`JOINTS_0`、`WEIGHTS_0`、`animations`、动画时长和通道数。
- [`scripts/render_glb_keyframes.py`](scripts/render_glb_keyframes.py)：只渲染关键帧 PNG，不编码 MP4。

旋转处理的核心是：

```text
GVHMR 的 SMPL-22 局部旋转
  -> 按 SMPL 父子树累积成全局旋转
  -> Y-up/Z-up 坐标变换
  -> 乘目标 GLB 绑定姿态
  -> 还原目标骨骼局部旋转
```

这一步是修正“原视频手臂自然下垂，但角色手臂被抬平”的关键。不能把 `bone_0、bone_1、...` 的编号直接当成 SMPL 编号；`build_topology_mapping.py` 使用拓扑和语义槽完成映射。

## 输入约束和自动映射边界

一键脚本适用于 SkinTokens 能生成以下身体主干的角色：

```text
Pelvis -> Spine1 -> Spine2 -> Spine3
                       ├─ Neck -> Head
                       ├─ Collar -> Shoulder -> Elbow -> Wrist
                       ├─ Hip -> Knee -> Ankle -> Foot
                       └─ 另一侧同样的手臂和腿
```

雪帽少女实际有 46 个 joints，其中多出来的是手指骨；冰雪射手当前有 22 个 joints。两者都通过了这套拓扑映射。手指和弓箭等道具骨骼会保留在 rigged GLB 中，但当前 `SMPL-22` 动作不包含手指姿态，也不会自动驱动道具。

如果新角色的骨树没有清晰的左右手臂/腿链，脚本会在拓扑报告或映射步骤失败。此时先查看 `reports/topology.json`，人工修正映射 JSON 后，再把它传给 `apply_gvhmr_motion.py --mapping-json`；不要默认为“编号恰好对应”。

## GPU 使用边界

- GVHMR 推理在远程 `.venv310` 的 CUDA/PyTorch 环境运行，已验证 RTX 5090 D v2。
- SkinTokens 的模型推理由其项目和 bpy 服务配置决定，日志中应确认服务是否使用 GPU。
- Blender 的重定向主要是骨骼矩阵和关键帧写入，通常是 CPU 工作；把数据放进显存不会自动让 Python/bpy 骨骼计算变成 GPU 计算。
- `render_glb_keyframes.py` 会优先尝试 Cycles CUDA/OptiX；如果 Blender 没有可用设备，会明确回退 CPU。

## 当前已生成的实验资产

`assets/outputs/topology_retarget/` 中的四个 `_topology_global_animated.glb` 是当前修正后的候选：

- `snow_girl_video1_topology_global_animated.glb`
- `snow_girl_video2_topology_global_animated.glb`
- `ice_archer_video1_topology_global_animated.glb`
- `ice_archer_video2_topology_global_animated.glb`

它们都通过了当前结构检查：1 个 skin、存在 `JOINTS_0/WEIGHTS_0`、1 条动画；视频 1 为 97 帧、约 4.04 秒，视频 2 为 241 帧、约 10.04 秒。`assets/legacy/` 仅用于和旧版错误编号映射做对照。

## 社区插件说明

GVHMR 官方仓库提供推理和 `.pt` 输出，不提供官方 Blender 插件。PKL-Loader-Blender、CEB HubMocap 等社区工具可以参考它们的轴角转换、坐标修正和逐帧关键帧逻辑，但不会自动识别任意 SkinTokens GLB。本目录的实现把这些思路改成了面向本项目拓扑的脚本；HaMeR 手部动作尚未接入当前 SMPL-22 主流程。
