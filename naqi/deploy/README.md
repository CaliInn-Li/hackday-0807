# Naqi 全栈部署与 AI 交接入口

本目录把 `frontend + backend + GPU pipeline` 组合成一个可体验的 HTTP 服务。给同事或 AI
接手时，先读本文件，再按改动类型进入对应目录；不要从历史日志反推当前实现。

## 30 秒理解系统

```text
浏览器 :18000
  ├─ /              -> frontend/dist 静态管理界面
  └─ /api/*         -> backend public API :18080
                           ├─ GLB -> SkinTokens -> rigged GLB
                           ├─ MP4 -> GVHMR -> SMPL-22 NPZ
                           └─ rigged GLB + NPZ -> Blender -> animated GLB

backend admin API :18081 仅绑定 127.0.0.1，不经过公网网关
```

三类资产可以独立缓存和自由组合：Character 是已绑骨 GLB，Motion 是动作 NPZ，Animation
是两者重定向后的动画 GLB。同一视频不应为不同角色重复跑 GVHMR，同一角色也不应为不同
视频重复跑 SkinTokens。

## AI 应该修改哪里

| 需求 | 首选位置 | 不要误改 |
|---|---|---|
| API、缓存、任务队列、下载 | `../backend/naqi_backend/` | `../scripts/` 技术验证脚本 |
| 管理界面、预览、交互 | `../frontend/src/` | 已生成的 `frontend/dist/` |
| SMPL-22 重定向算法 | `../scripts/apply_gvhmr_motion.py` | 不要按 bone 编号盲映射 |
| SkinTokens/GVHMR/Blender 调用参数 | `../backend/naqi_backend/stage_adapter.py` | 不要把模型推理搬到网关 |
| 端口、静态站点、同源 `/api` | 本目录 | 不要公开 18081 |
| 数据格式和接口契约 | `../backend/docs/asset_api_contract.md` | 不要只看前端 TypeScript 类型猜接口 |

`../scripts/` 是已跑通算法的技术验证层，后端通过 adapter 调用它。除非改算法本身，否则服务
功能优先改 `backend/` 或 `frontend/`，避免把两套职责重新耦合。

## 首次部署：一键构建并启动

要求：Linux、Python 3.11、Node.js 20+、npm，以及已经准备好的 SkinTokens、GVHMR、
Blender。GPU 模型目录不会随本仓库下载。

```bash
cd naqi/backend
cp .env.example .env
# 编辑 .env：至少设置 SKINTOKENS_HOME、GVHMR_HOME、BLENDER_BIN、
# NAQI_PIPELINE_TOOLS_DIR 和仓库外的 NAQI_DATA_ROOT。

cd ../deploy
./bootstrap_and_start.sh
```

脚本会：

1. 缺少 backend venv 时执行 `backend/bootstrap.sh`；
2. 执行 `npm ci`；
3. 以 `VITE_NAQI_API_BASE=/api` 构建前端；
4. 启动 backend `127.0.0.1:18080/18081`；
5. 启动零依赖 Node 网关 `0.0.0.0:18000`；
6. 验证 public health 后返回 PID。

如远程下载慢，可以在有代理的电脑执行前端构建，把 `frontend/dist/` 上传后只运行
`./start.sh`。不要提交 `node_modules/`、`dist/`、`.venv/`、`.env` 或真实密钥。

## 日常操作

```bash
cd naqi/deploy
./start.sh
./status.sh
./stop.sh

tail -f .runtime/logs/backend.log
tail -f .runtime/logs/gateway.log
```

可通过环境变量覆盖部署位置：

```bash
NAQI_GATEWAY_PORT=18000 \
NAQI_GATEWAY_STATIC_ROOT=/srv/naqi/frontend-dist \
NAQI_SERVICE_STATE_DIR=/var/lib/naqi-service \
./start.sh
```

## 导入仓库自带示例（可选）

这一步只登记和复制已有产物，不重新运行 GPU 推理：

```bash
cd naqi
set -a
source backend/.env
set +a
backend/.venv/bin/python deploy/seed_demo_assets.py
```

成功后会看到 2 个角色、3 份动作和 5 个动画。该脚本使用确定性 ID，可幂等重跑。

## 验收

```bash
curl http://127.0.0.1:18000/
curl http://127.0.0.1:18000/api/health/live
curl http://127.0.0.1:18000/api/v1/assets/characters
curl http://127.0.0.1:18081/health/ready
```

`health/ready` 应确认 `pipeline_tools_dir`、`skintokens_home`、`gvhmr_home`、
`blender_bin` 和 `asset_execution_backend` 均为 `true`。下载还应验证 GLB、NPZ、MP4 的
Range 请求返回 `206 Partial Content`。

后端会在 `runs/` 中保留 `.naqi-root` 哨兵文件，因为 SeaweedFS 等对象存储挂载不会保留
空目录；它不是任务产物，不要当作垃圾文件清理。

## 安全和生产边界

- `NAQI_DEV_MODE=1` 只用于临时内网体验，此模式 public 写接口没有 API key。
- 生产必须配置不同的 `NAQI_API_KEY` 与 `NAQI_ADMIN_API_KEY`，并使用 HTTPS。
- `18081` 永远只绑定 `127.0.0.1`；不要把 admin API 接入本公网网关。
- 本网关是零依赖演示入口，不负责 TLS、限流、身份系统或多实例负载均衡；生产请换成
  Nginx/Caddy/Ingress，但保持 `/api -> 18080` 的同源契约。
- 当前 backend 是单 GPU worker。不要用多个 Uvicorn worker 同时抢同一张 GPU。
- `NAQI_GVHMR_RENDER_PREVIEW=0` 是默认推荐值；官方角色 MP4/关键帧渲染应由用户显式选择。
- 不要在 GPU 任务运行期间执行 `stop.sh`。服务器重启自动拉起请另配 systemd/容器编排。

## 修改后的最小验证

```bash
cd naqi/backend
.venv/bin/python -m pytest -q

cd ../frontend
npm run typecheck
npm run lint
npm test
npm run build

cd ../deploy
node --check http_gateway.mjs
bash -n bootstrap_and_start.sh start.sh status.sh stop.sh
```

更详细的 API、数据目录和缓存语义见 [`../backend/README.md`](../backend/README.md)；算法
阶段和单文件输入输出见 [`../README.md`](../README.md)。
