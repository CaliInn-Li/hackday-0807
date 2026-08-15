# Hackday：视频到可用游戏角色

## 如何运行

远程机器仍需保留这些依赖：

- `/home/naqi/SkinTokens`：包含 `.venv` 和模型检查点。
- `/home/naqi/GVHMR`：包含 `.venv310`、GVHMR/HMR2/ViTPose/YOLO/SMPL-X 检查点。
- `/usr/local/bin/blender`：Blender 4.5。

这些大型依赖不包含在本仓库中。使用不同位置时，可以设置 `SKINTOKENS_HOME`、`GVHMR_HOME`、`BLENDER_BIN`。

**由于远程机器不能联网，不能执行`git clone`，因此需要本地复制**

1. 在本机项目目录（`hackday-0807`）下执行：

```powershell
scp -P 30704 -r `
  inputs `
  pipeline `
  run.sh `
  naqi@<replace-with-real-addr>:/home/naqi/<directory>/
```

Linux/macOS 下执行（续行符为反斜杠 `\`）：

```bash
scp -P 30704 -r \
  inputs \
  pipeline \
  run.sh \
  naqi@<replace-with-real-addr>:/home/naqi/<directory>/
```

2. 复制后先检查所有路径：

```bash
cd /home/naqi/<directory>
chmod +x run.sh
bash run.sh --check
```

出现 `Environment check passed.` 即表示复制后的代码和机器级依赖均可用。

## 一键运行

3. 把输入放进 `inputs/`，然后在仓库根目录执行：

```bash
PIPELINE_WORK="$PWD" \
PIPELINE_RUN="$PWD/runs/<名称>" \
PIPELINE_VIDEO="$PWD/inputs/action.mp4" \
PIPELINE_CHARACTER="$PWD/inputs/character.glb" \
SKINTOKENS_HOME=/home/naqi/SkinTokens \
GVHMR_HOME=/home/naqi/GVHMR \
BLENDER_BIN=/usr/local/bin/blender \
bash run.sh
```

- 阶段①A先把固定 `smpl22-mixamo-v1` 骨架拟合并嵌入原始角色；除躯干中轴外，还会从 T/A Pose 网格横截面估计上臂、肘、腕和双脚中心，使四肢关节进入模型体积中心。拟合数值写入 `character_skeleton_fit.json`。
- 阶段①B使用 SkinTokens `--use-skeleton --use-transfer`，只生成蒙皮权重，不允许模型自由生成骨架拓扑。
- 阶段②以①A的语义骨架为参考，验证22骨、完整父子图、左右语义、关节/权重空间关系和每顶点权重，再输出 clean GLB 与压力测试。四肢权重保持严格空间阈值；躯干/头部允许披风、长裙、长发等附件拉远整体权重质心，但超过硬阈值仍会失败。
- 阶段⑤按“SMPL局部旋转 → SMPL全局旋转 → 目标绑定姿态 → 目标局部旋转”烘焙动作。
- 最终动画：`runs/<名称>/motion/character_action_animated.glb`。
- 日志和中间产物全部保存在对应的 `runs/<名称>/` 中。

可选配置：

```bash
SKINTOKENS_SEED=0                 # 蒙皮生成可复现
SKINTOKENS_USE_POSTPROCESS=1      # 开启官方体素蒙皮后处理
PIPELINE_BODY_CENTER_Y=<数值>     # 极端披风/背包模型手工覆盖人体中轴Y
```

Blender 显示的手、头、脚末端细长部分是 leaf bone 的 `tail`，不是额外关节；glTF 只保存 joint 节点、不保存 leaf tail。主管线会在 Blender 处理阶段把它修成短的语义方向显示线，蒙皮位置以骨骼 head/joint 为准。

无需 Blender/GPU 的本地契约测试：

```bash
python3 -m unittest discover -s tests -v
```

完整原理与故障处理见 [完整闭环运行手册](docs/原始Lux3D-GLB到动画GLB-完整闭环运行手册.md)，五阶段独立运行与产物说明见 [pipeline/五阶段独立运行与产物说明.md](pipeline/五阶段独立运行与产物说明.md)。
