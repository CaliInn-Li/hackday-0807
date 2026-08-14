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
bash run.sh \
  inputs/action.mp4 \
  inputs/character.glb \
  runs/<名称> \
  static
```

- `static`：固定机位，速度快、稳定。
- `moving`：移动机位，额外估计相机运动。
- 最终动画：`runs/action_character/motion/character_action_animated.glb`。
- 日志和中间产物全部保存在对应的 `runs/<名称>/` 中。

完整原理与故障处理见 [完整闭环运行手册](docs/原始Lux3D-GLB到动画GLB-完整闭环运行手册.md)，五阶段独立运行与产物说明见 [pipeline/五阶段独立运行与产物说明.md](pipeline/五阶段独立运行与产物说明.md)。
