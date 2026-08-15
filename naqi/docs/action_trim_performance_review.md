# action_trim 性能复盘

## 直接结论

本次从输入快照到最终动画 GLB/QA 约 30–35 分钟，但不是单次 GVHMR
推理需要半小时，也不是 Blender GLB 导入导出造成的。主要墙钟来自首次环境与
媒体准备、一次完整视频移动机位失败、人工裁剪与重试、多个独立进程冷启动、
SSH 轮询和交付整理。

本次复用了现成的 `雪帽少女_rigged.glb`，没有重新运行 SkinTokens。

## 成功路径中的真实耗时

| 阶段 | 本次耗时 | 判断 |
| --- | ---: | --- |
| GVHMR 输入复制/重编码 | 约 13 秒 | 已确认 |
| YOLO、ViTPose、HMR2 等预处理 | 71.46 秒 | 已确认，是成功路径最大计算阶段 |
| HMR4D `model.predict` | 1.68 秒 | 已确认 |
| GVHMR Incam 预览 | 23 秒 | 已确认，600 帧 |
| GVHMR Global 预览 | 21 秒 | 已确认，600 帧 |
| 预览 MP4 合并 | 未完成 | ffmpeg 不在该进程 PATH，合并失败 |
| Blender 动画 GLB 导出 | 6.16 秒 | 已确认 |
| 三张 Cycles QA 关键帧 | 10.60 秒 | 已确认，RTX 5090 D v2 |

此前 241 帧重定向基准的 Blender import/key/export/total 为
`0.950s / 0.403s / 3.520s / 4.873s`。本次 600 帧实际 GLB 导出为
6.16 秒。即使完全绕过 Blender IO，也只能省几秒，不能解释或解决半小时墙钟。

完整 44.42 秒视频先尝试 moving/SimpleVO，约浪费 4 分钟且没有产出动作；随后
又发生镜头判断、8–28 秒裁剪和一次无效参数启动。这些试错与人工编排才把端到端
时间放大到半小时。

## 无预览入口的远程冷启动基准

在 RTX 5090 D v2 上用全新 output root 重新运行 20 秒、600 帧 static 输入：

| 指标 | 实测 |
| --- | ---: |
| 总墙钟 | 179.921 秒 |
| 进程启动到第一条 GVHMR 业务日志 | 约 96 秒 |
| Preprocess | 74.62 秒 |
| 模型初始化、加载和预测区间 | 约 5 秒 |
| 其中 `model.predict` | 1.67 秒 |

生成的 PT SHA-256 与正式结果一致：
`b42b51bbf3bb99e3105fffea81e6ee5ec5eed3b69567b586d021fddaca47d1bf`。
日志中 `Rendering Incam`、`Rendering Global`、`Merge Videos` 均为 0 次，确认
无预览入口有效。GPU 峰值利用率 100%，峰值显存约 4.85 GB。

这也修正了“冷启动只占几秒”的初步猜测：在当前远程环境里，独立 GVHMR
Python 进程到第一条业务日志实际约 96 秒，模型/依赖常驻是高价值优化；但即使
消除这 96 秒，预处理仍需约 75 秒。

## 官方预览是否必要

GVHMR 官方 `tools/demo/demo.py` 在保存 `hmr4d_results.pt` 后会继续调用
`render_incam`、`render_global` 和 MP4 merge；当前命令行没有跳过这三步的参数。
最终角色动画保存在 GLB 中，所以服务端正常生产不需要官方角色预览视频。

后端现已提供 `naqi_backend/gvhmr_infer_only.py`：复用官方配置、预处理和模型
代码，在 PT 保存成功后立即结束。默认配置为：

```bash
NAQI_GVHMR_RENDER_PREVIEW=0
```

只有诊断时才设为 `1`。按本次日志，仅两套预览就可直接节省约 44 秒，并避免
无意义的 MP4 合并失败。

## 后端优化优先级

1. 三级哈希缓存：视频复用 PT/NPZ，角色复用 rigged GLB，组合复用 animated
   GLB；缓存键应包含模型权重、脚本和配置版本。
2. 默认关闭 GVHMR 官方预览，预览改为低优先级、按需任务。
3. 自动判断 static/moving、先做短抽样；SimpleVO 失败后自动回退或返回建议
   裁剪范围，避免整段失败后人工重跑。
4. 让 YOLO、ViTPose、HMR2/GVHMR 和 SMPL-X 常驻 GPU，并在同一进程直接写
   PT/NPZ，减少 Torch/CUDA/权重的重复冷启动。
5. 将 GPU 推理队列与 Blender/结构 QA/下载 IO 队列拆开：GPU 做下一任务时，
   CPU 可以导出上一任务的 GLB。
6. 由 HTTP Job 一次编排完整 DAG，记录每阶段开始/结束时间，通过 SSE/WebSocket
   推送状态，替代人工 SSH 轮询。
7. 部署镜像预装并在 readiness 检查 ffmpeg/ffprobe；资产常驻服务器，避免每次
   重复 SCP。
8. 同一角色批量套多个动作时复用 Blender 导入；直接手写 GLB accessor 放在
   最后，因为只能省几秒且坐标、骨架和二进制正确性风险高。

## 预期范围

- 当前手工调试：约 30–35 分钟。
- 环境已就绪、自动选对 static、关闭官方预览但仍使用冷启动子进程：单次
  GVHMR PT 实测约 3 分钟，完整 PT→NPZ→GLB 预计约 4–6 分钟。
- 模型常驻并在同一进程导出 NPZ：有机会降到约 1.5–3 分钟，需部署后实测。
- NPZ 与 rigged GLB 都命中缓存，仅重新组合：核心预计约 10–30 秒，主要剩
  Blender 导出与传输。

相关原始证据位于 `output/reports/runs/action_trim/`。
