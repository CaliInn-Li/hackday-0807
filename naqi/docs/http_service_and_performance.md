# HTTP 服务与性能规划

## 技术选择

服务层使用 Python/FastAPI，不使用 Rust。一次任务的主要耗时来自
SkinTokens、GVHMR 和 Blender 子进程，HTTP 框架的开销可以忽略；Python
能够直接复用现有脚本、数据契约和运维环境。服务进程本身不导入 Torch、
Blender、SkinTokens 或 GVHMR，只负责上传、持久化、排队、状态查询和产物下载。

默认暴露两个端口：

- `18080`：任务 API；
- `18081`：存活、就绪和管理状态，默认只监听 `127.0.0.1`。

GPU worker 默认并发为 1。RTX 5090 D 是否适合同时运行多个模型任务，应以
峰值显存和端到端吞吐实测为准，不能根据空闲时的 `nvidia-smi` 推断。

## 当前任务执行模型

```text
HTTP upload
  -> SQLite job (queued)
  -> single GPU worker
  -> run_naqi_pipeline.sh
  -> per-job logs and artifacts
  -> succeeded / failed / cancelled
```

每个任务只能访问自己的运行目录。客户端不能提交服务器文件路径；上传仅允许
MP4 和 GLB，并受大小上限、Bearer API key 和路径穿越检查保护。

## CPU/GPU 边界

| 阶段 | 当前设备 | 说明 |
|---|---|---|
| SkinTokens 骨架与蒙皮 | GPU + Blender CPU | 模型推理使用 GPU，Blender/GLB 处理仍包含 CPU 工作 |
| 骨树分析与拓扑映射 | CPU | 数据量只有几十个关节，GPU 调度不划算 |
| GVHMR 视频动作推理 | GPU，另有 CPU 解码/预处理 | 主要计算热点，应重点记录端到端时间和峰值显存 |
| SMPL-22 导出 | GPU + CPU | 当前用 SMPL-X 计算源身高，但存在只需一帧却计算全部帧的优化空间 |
| Blender 重定向/烘焙 | CPU | 逐帧骨骼矩阵和关键帧写入规模小，GPU 不适用 |
| GLB 导入/导出 | CPU/IO | Blender glTF 序列化不能由 CUDA 加速 |
| 关键帧 QA 渲染 | GPU | RTX 优先评估 OptiX，失败后再回退 CUDA/CPU |

## 优化优先级

### P0：先建立可测量的服务基线

记录任务输入 SHA-256、排队时间、开始时间、结束时间、退出码和阶段日志。
没有这些数据时，“GPU 空闲”或单次 Blender 计时都不足以定位整体瓶颈。

### P1：按阶段复用产物

这是当前最有价值的优化：

- 动作缓存键：视频 SHA-256、camera mode、GVHMR 版本和推理参数；
- 蒙皮缓存键：角色 GLB SHA-256、SkinTokens 版本和参数；
- 重定向缓存键：rigged GLB 哈希、motion NPZ 哈希、映射和脚本版本。

同一视频套两个角色时只跑一次 GVHMR；同一角色套两个视频时只跑一次
SkinTokens。当前完整流水线脚本仍按单任务运行，缓存应在下一阶段把流水线拆成
`rig`、`motion`、`retarget` 三个可复用任务后实现。

### P2：修复局部明确浪费

- `extract_gvhmr_motion.py` 计算身高时只向 SMPL-X 传一帧参数；
- QA 渲染优先尝试 OptiX，再回退 CUDA；
- 为七个阶段分别记录 wall time 和 GPU 显存峰值。

### P3：模型常驻与流水调度

确认 GVHMR/SkinTokens 模型加载时间占比后，再把模型改为常驻 GPU worker。
这需要改造上游项目的模型生命周期，不是给 Shell 脚本外包一层 HTTP 就能获得。
后续还可让下一任务的 CPU 视频预处理与当前任务的 GPU 推理重叠，但 GPU 推理
并发应继续由显存实测决定。

## 不优先做的优化

直接用 `pygltflib` 或 `trimesh` 替换 Blender glTF 导出器风险较高：需要正确维护
buffer、accessor、skin、animation、材质和二进制对齐。即使能节省数秒，相比
模型推理和重复计算通常不是首要瓶颈。只有阶段计时证明 GLB 导出占端到端显著
比例后，才值得单独立项。
