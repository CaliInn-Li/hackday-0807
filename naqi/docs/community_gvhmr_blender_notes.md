# 社区 GVHMR/HaMeR Blender 工具的适用边界

## 结论

不能把社区工具称为“官方 GVHMR+HaMeR Blender 插件”。GVHMR 官方仓库负责推理和结果文件；社区插件/脚本负责把 SMPL/SMPL-X 参数导入 Blender 并逐帧写关键帧。HaMeR 本身是手部 3D 网格恢复模型，不是 Blender 插件。

## 对本项目的可复用部分

可以参考：

1. `smpl_params_global` 中 `transl`、`global_orient`、`body_pose`、`betas` 的读取；
2. 轴角 reshape、Rodrigues/旋转矩阵到四元数；
3. GVHMR/Blender 坐标系修正；
4. 在每帧给骨骼设置局部旋转并插入关键帧；
5. GVHMR 身体动作和 HaMeR 手部动作的合并方式。

不能直接复用的部分：

- 插件通常假设目标是固定名称和固定拓扑的 SMPL/SMPL-X 骨架；
- 它不会自动理解任意 SkinTokens GLB 的骨骼语义；
- 它不会自动处理长发、手指、弓箭等额外骨骼；
- 它不能替代目标骨架的绑定姿态、骨轴和蒙皮检查。

## 本项目接法

```text
GVHMR SMPL-X/SMPL-22
  -> 复用参数解码和旋转转换
  -> inspect_skin_tokens_topology.py 识别 SkinTokens 身体主干
  -> topology_mapping.json 固化 bone -> SMPL-22 映射
  -> apply_gvhmr_motion.py 写入目标 GLB
```

手指动作需要单独保留 SMPL-X hand pose 和 HaMeR 输出；当前 SMPL-22 动作只驱动到左右手腕，额外手指骨骼保持绑定姿态并随手腕父节点移动。
