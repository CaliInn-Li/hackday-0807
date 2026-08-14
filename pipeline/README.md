# 视频到可用游戏角色：已落地流水线

完整原理、逐阶段命令、数据契约、故障处理和验收标准见：`../docs/原始Lux3D-GLB到动画GLB-完整闭环运行手册.md`。

这套脚本已经在远程 RTX 5090 D v2、离线环境中实际跑通以下链路：

`静态 GLB → SkinTokens 自动骨骼/蒙皮 → 22 骨语义化 → GVHMR 视频动作 → SMPL-22 中间格式 → Blender 空间重定向/缩放/烘焙 → 动画 GLB`

SkinTokens 阶段使用 `--use-transfer`，将预测权重转回原 Lux3D 网格，以保留原始尺寸、PBR 材质和紧凑拓扑；不要使用默认的归一化展开网格作为游戏资产。

## 本次实测产物

- `artifacts/冰雪射手_rigged_transfer_reproduced.glb`：本次从原始 GLB 重新执行 SkinTokens `--use-transfer` 的直接输出。
- `artifacts/冰雪射手_rigged_transfer_clean.glb`：上述新结果的清理/语义化 22 骨版本，无动画。
- `artifacts/冰雪射手_rigged_transfer_test.glb`：基于本次新绑定结果的 2 秒骨骼压力测试动画。
- `artifacts/冰雪射手_tennis_full_reproduced.glb`：推荐最终产物；从本次新绑定结果继续生成，含 GVHMR 样例视频的 312 帧动作，30 FPS、10.4 秒。
- `artifacts/tennis_gvhmr_smpl22.npz`：不依赖 GVHMR/Blender 的可移植动作中间文件。
- `artifacts/gvhmr_tennis_incam.mp4` 与 `artifacts/gvhmr_tennis_global.mp4`：GVHMR 官方人体重建可视化。远程系统没有 `ffmpeg` CLI，因此跳过二者的横向拼接，不影响动作数据。
- `artifacts/rig_test_*.png`、`artifacts/gvhmr_frame_*.png`：蒙皮和重定向验收图。

推荐最终 GLB 已通过 Khronos glTF Validator：0 error、0 warning。模型包含 22 根骨骼、完整蒙皮、PBR 材质与一条 `GVHMR_Action` 动画；SHA-256 为 `157F10AE17A0FC7492ABAEF92635525DFCD7F4D2DFBE032CBA854CBB2788AF3B`。

## 在远程机器执行`run_remote_pipeline.sh`

## 输入要求与生产注意项

- 人物视频应尽量全身可见、少遮挡、单人、无快速剪辑；30 FPS 最省事。
- Lux3D 模型最好是单一连续角色、四肢分离清楚、A/T Pose 接近中立姿态。
- SkinTokens 的 22 骨身体链能驱动整体造型，但长发、裙摆、弓箭等配件仍需补辅助骨或改成刚性权重，才能达到正式游戏品质。
- 当前输出保留原模型尺寸。本例角色高度约 0.26（模型单位）；重定向脚本根据 GLB 的真实 POSITION 范围和 SMPL-X 身高自动缩放根位移。
- 如只需演示，直接加载最终 GLB 播放第一条 animation；Three.js、Babylon.js、Unity 和 Unreal 均可接入。

## 关键实现

- `scripts/inspect_rig.py`：骨骼、层级、权重覆盖率验收。
- `scripts/run_skintokens_offline.py`：把原项目 30 秒 Blender 服务超时扩展到默认 600 秒，并持续输出进度、监测子进程退出，适配网络盘冷启动，不修改 SkinTokens 仓库。
- `scripts/prepare_and_test_rig.py`：清理调试网格、语义化骨骼、修复 glTF 根节点警告、生成压力测试动作与四视图。
- `scripts/extract_gvhmr_motion.py`：兼容压平轴角、关节轴角和旋转矩阵，导出统一 SMPL-22 NPZ。
- `scripts/apply_gvhmr_motion.py`：Y-up→Z-up 坐标变换、22 骨映射、静态骨轴共轭、身高比例位移、逐帧烘焙和 QA 渲染。
- `config/skintokens_mixamo_mapping.json`：SkinTokens 通用 22 骨到 Mixamo 风格名称映射。
