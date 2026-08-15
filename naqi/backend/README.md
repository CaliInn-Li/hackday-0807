# NAQI Backend

这是一个可独立迁仓的 FastAPI 后端，把以下三类重型能力包装成可缓存、可组合、
可下载的资产任务：

```text
无骨骼 GLB --SkinTokens--> Character（rigged GLB + mapping）
MP4 --------GVHMR--------> Motion（SMPL-22 NPZ）
Character + Motion --Blender--> Animation（animated GLB）
```

后端自身保持轻量：只安装 FastAPI、Uvicorn 和 SQLite 相关 Python 依赖；不会在
自己的虚拟环境里安装或导入 Torch、SkinTokens、GVHMR、Blender、模型权重。
这些重型运行时由环境变量指向，并以 `shell=False` 子进程调用。

## 给 AI / 自动化代理的最短操作说明

如果你接手的是一台已经装好 SkinTokens、GVHMR、Blender 的 Linux GPU 服务器，
按下面顺序执行，不要修改仓库根目录的技术验证脚本：

```bash
git clone https://github.com/CaliInn-Li/hackday-0807.git
cd hackday-0807/naqi/backend

cp .env.example .env
# 编辑 .env，至少填写两个 API Key 和四个 typed-stage 路径。

./bootstrap.sh
./start.sh
```

`./start.sh` 会占用当前终端运行服务。在第二个终端加载同一份环境并验收：

```bash
cd hackday-0807/naqi/backend
set -a
source .env
set +a

curl http://127.0.0.1:18080/health/live

curl -H "Authorization: Bearer $NAQI_ADMIN_API_KEY" \
  http://127.0.0.1:18081/health/ready
```

第一条必须返回 HTTP 200。第二条用于资产工作台时必须同时满足：

```json
{
  "status": "ready",
  "checks": {
    "database": true,
    "asset_database": true,
    "runs_dir": true,
    "asset_execution_backend": true
  }
}
```

`start.sh` 默认自动加载同目录的 `.env`；也可通过
`NAQI_ENV_FILE=/secure/path/naqi.env ./start.sh` 指定其他文件。不要提交真实
`.env` 或把密钥写入 README、GitHub Actions 日志、前端 `VITE_*` 变量。

## 两种执行模式

### 1. Typed asset API（推荐，管理界面使用）

每类输入只计算一次，之后自由组合：

```text
POST /v1/assets/characters -> rig job
POST /v1/assets/motions    -> motion job
POST /v1/animations        -> retarget job
```

必须配置：

```bash
NAQI_PIPELINE_TOOLS_DIR=/path/to/hackday-0807/naqi/scripts
SKINTOKENS_HOME=/opt/SkinTokens
GVHMR_HOME=/opt/GVHMR
BLENDER_BIN=/usr/bin/blender
```

当前仓库中 `NAQI_PIPELINE_TOOLS_DIR` 应直接指向 `naqi/scripts`。未来把 backend
迁到独立仓库时，应把这些 pipeline tools 单独安装或打包，再修改该路径；后端
代码没有硬编码 monorepo 的相对位置。

### 2. Legacy full job（兼容旧的一键脚本）

旧入口 `POST /v1/jobs` 一次接收 MP4 与 GLB，并调用：

```bash
NAQI_PIPELINE_SCRIPT=/opt/naqi/bin/run_naqi_pipeline.sh
```

这不是资产管理界面的推荐路径。只配置 legacy runner 时，整体 readiness 可以为
ready，但 `asset_execution_backend` 仍会是 false。前端资产上传前必须检查 typed
stage 路径完整，而不能只看 `legacy_execution_backend`。

## 服务器配置

复制 `.env.example` 后填写：

```dotenv
NAQI_API_KEY=生成一个长随机公有接口密钥
NAQI_ADMIN_API_KEY=生成另一个不同的管理密钥
NAQI_DEV_MODE=0

NAQI_PIPELINE_SCRIPT=
NAQI_PIPELINE_TOOLS_DIR=/srv/hackday-0807/naqi/scripts
SKINTOKENS_HOME=/srv/SkinTokens
GVHMR_HOME=/srv/GVHMR
BLENDER_BIN=/usr/bin/blender

NAQI_DATA_ROOT=/var/lib/naqi-backend
NAQI_PUBLIC_HOST=127.0.0.1
NAQI_PUBLIC_PORT=18080
NAQI_ADMIN_HOST=127.0.0.1
NAQI_ADMIN_PORT=18081

NAQI_GVHMR_RENDER_PREVIEW=0
NAQI_CORS_ORIGINS=https://naqi.example.com
```

运行时约束：

- Python：`>=3.11,<3.13`，仅用于轻量后端。
- `SKINTOKENS_HOME/.venv/bin/python` 必须存在。
- `GVHMR_HOME/.venv310/bin/python` 与 `GVHMR_HOME/tools/demo/demo.py` 必须存在。
- `BLENDER_BIN` 必须是可执行 Blender 路径，或是 PATH 中可解析的命令。
- `NAQI_PIPELINE_TOOLS_DIR` 必须包含 readiness 所列的 7 个阶段脚本。
- `ffprobe` 应在 PATH 中；否则动作 FPS 回退到 24。可用 `NAQI_FPS` 显式覆盖。
- 当前只支持 `NAQI_WORKERS=1`，避免同一张 GPU 同时加载多个重型任务。
- 生产环境把 `NAQI_DATA_ROOT` 放在仓库外，并给服务账号写权限。

未设置两个 API Key 时，生产模式拒绝启动。只有本机开发可使用
`NAQI_DEV_MODE=1` 关闭鉴权。

## 为什么默认不生成 GVHMR 预览 MP4

官方 GVHMR demo 在保存 `hmr4d_results.pt` 后还会渲染 Incam/Global 两套视频
并合并 MP4。动画交付物已经在 GLB 的 `animations` 中，这些视频对生产任务不是
必需的。

默认配置：

```bash
NAQI_GVHMR_RENDER_PREVIEW=0
```

此时后端使用 `naqi_backend/gvhmr_infer_only.py`，复用 GVHMR 官方预处理和模型
逻辑，在 PT 保存后退出。只有诊断 GVHMR 原始动作时才设为 `1`。该无预览路径
已经在 RTX 5090 D v2 上用 600 帧视频验证：PT 正常生成，未运行 Incam、Global
或 Merge Videos。

## Typed asset API 示例

所有接口除公开的 `/health/live` 外，都需要：

```text
Authorization: Bearer <NAQI_API_KEY>
```

### 1. 上传无骨骼角色 GLB

```bash
curl -X POST http://127.0.0.1:18080/v1/assets/characters \
  -H "Authorization: Bearer $NAQI_API_KEY" \
  -F "file=@character.glb" \
  -F "name=角色名称"
```

`name` 可省略，默认使用文件名。

### 2. 上传动作视频

```bash
curl -X POST http://127.0.0.1:18080/v1/assets/motions \
  -H "Authorization: Bearer $NAQI_API_KEY" \
  -F "file=@action.mp4" \
  -F "camera_mode=static"
```

`camera_mode` 只能是 `static` 或 `moving`。固定镜头优先使用 `static`；当前版本
不会自动判断镜头模式。两个上传响应中的 `job.id` 都用于查询进度。

### 3. 查询任务

```bash
curl -H "Authorization: Bearer $NAQI_API_KEY" \
  http://127.0.0.1:18080/v1/jobs/JOB_UUID
```

等待状态变为 `ready`（typed asset job）或 `succeeded`（legacy full job）。

### 4. 组合已绑骨角色与已识别动作

```bash
curl -X POST http://127.0.0.1:18080/v1/animations \
  -H "Authorization: Bearer $NAQI_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "character_id": "READY_CHARACTER_UUID",
    "motion_id": "READY_MOTION_UUID",
    "render_keyframes": false
  }'
```

该请求只执行 Blender retarget/QA，不会重新运行 SkinTokens 或 GVHMR。

### 5. 预览或下载文件

```bash
# 已绑骨角色 GLB
curl -L -H "Authorization: Bearer $NAQI_API_KEY" \
  -o rigged.glb \
  "http://127.0.0.1:18080/v1/assets/characters/CHARACTER_UUID/files/rigged_glb?download=true"

# 动作 NPZ
curl -L -H "Authorization: Bearer $NAQI_API_KEY" \
  -o motion.npz \
  "http://127.0.0.1:18080/v1/assets/motions/MOTION_UUID/files/motion_npz?download=true"

# 最终动画 GLB
curl -L -H "Authorization: Bearer $NAQI_API_KEY" \
  -o animated.glb \
  "http://127.0.0.1:18080/v1/assets/animations/ANIMATION_UUID/files/animated_glb?download=true"
```

完整接口和允许的 `file_kind` 见
[`docs/asset_api_contract.md`](docs/asset_api_contract.md)。客户端永远不能提交服务端
文件路径，只能提交上传文件、资产 UUID 和白名单 file kind。

## 缓存与任务语义

- Character：输入 GLB SHA-256 + rig 参数形成缓存键。
- Motion：输入 MP4 SHA-256 + camera mode 形成缓存键。
- Animation：rigged GLB SHA-256 + NPZ SHA-256 + render 选项形成缓存键。
- ready 缓存命中返回 `cache_hit=true`，不会占用 GPU 队列。
- failed/cancelled 的相同输入复用原资产 ID，并创建新的重试 job。
- queued job 在服务重启后恢复；running job 被标记为 failed，错误为
  `interrupted by service restart`。
- legacy full jobs 与 typed jobs 共享一个队列和进程级 GPU 锁。

当前后端是“常驻调度器 + 外部短生命周期模型进程”，模型尚未常驻显存。性能
优化路线见 [`../docs/action_trim_performance_review.md`](../docs/action_trim_performance_review.md)。

## 数据目录

后端只在 `NAQI_DATA_ROOT` 下写入数据：

```text
NAQI_DATA_ROOT/
├─ naqi.sqlite3
├─ assets/
│  ├─ character/<uuid>/source.glb, rigged.glb, topology.json, mapping.json
│  ├─ motion/<uuid>/source.mp4, motion.npz, manifest.json
│  └─ animation/<uuid>/animated.glb, retarget.json, qa.json
├─ asset_jobs/<job-uuid>/stdout.log, stderr.log
└─ runs/                         # legacy full jobs
```

数据库和文件必须一起备份。不要单独移动某个资产目录，因为 SQLite 中保存的是
后端控制的绝对路径。

## 端口与安全

- `18080`：public API；生产建议绑定 `127.0.0.1`，由反向代理转发。
- `18081`：admin/health；必须绑定回环地址，禁止公网暴露。
- 公网只开放 `443`，由 Nginx/Caddy 终止 TLS、提供前端静态文件并代理 API。
- CORS 使用 `NAQI_CORS_ORIGINS` 显式白名单；不允许 `*`。
- API Key 使用长随机值，public/admin 两把密钥必须不同。

前端 README 位于 [`../frontend/README.md`](../frontend/README.md)。浏览器只在
`sessionStorage` 保存 public Bearer Key，不应接触 admin key。

## 测试与验收

测试不需要 GPU、Blender 或模型文件，使用 fake runner：

```bash
cd naqi/backend
./bootstrap.sh
./.venv/bin/python -m pip install -r requirements-dev.txt
./.venv/bin/python -m pytest -q
./.venv/bin/python -m compileall -q naqi_backend
```

部署后的最小验收清单：

1. `/health/live` 返回 200。
2. `/health/ready` 的 `asset_execution_backend=true`。
3. 上传一个小 GLB，最终 Character 状态为 ready，能下载 `rigged_glb`。
4. 上传一个短 MP4，最终 Motion 状态为 ready，manifest FPS/时长合理。
5. 组合两者，Animation 状态为 ready。
6. 下载的 GLB 有 skin、`JOINTS_0/WEIGHTS_0` 和至少一条 animation。
7. 同文件再次上传返回 `cache_hit=true`，且没有新的重型 GPU 任务。

## 已知限制

- static/moving 由调用方选择；SimpleVO 失败尚未自动回退。
- 单 GPU worker 优先保证显存稳定，不提供同卡并发推理。
- GVHMR/SMPL-X 手指动作不在当前 SMPL-22 合同中。
- Blender 导出仍是 CPU/IO 路径；GPU 主要用于 SkinTokens、GVHMR 和可选 QA
  渲染。
- Backend API 仍是 `0.1.0`，拆分独立仓库前应固定模型、脚本和缓存键版本。
