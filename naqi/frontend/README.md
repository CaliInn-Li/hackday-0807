# Naqi Frontend

这是 Naqi 角色动作工作台的独立前端版本。它只依赖后端 HTTP API，不导入 GVHMR、SkinTokens 或 Blender 运行时；未来可以直接迁移到独立仓库。

## 本地启动

目标环境是 Node 20。不要把 API Key 写进 `.env` 或 `VITE_*` 变量，因为 Vite 会把这些变量编译进浏览器静态资源。

```bash
cd naqi/frontend
cp .env.example .env.local
# 按需修改 VITE_NAQI_API_BASE
npm install
npm run dev
```

当前工作区没有提交 `node_modules`；在无网络机器上需要提前准备依赖缓存或离线镜像。常用命令：

```bash
npm run dev        # Vite 开发服务器，默认 5173
npm run build      # typecheck 后构建 dist/
npm run typecheck  # TypeScript 静态检查
npm run test       # Vitest 纯函数与 API client 单测
npm run lint       # 轻量 ESLint
```

## 部署

`npm run build` 生成的 `dist/` 是普通静态目录，可以交给 Nginx、对象存储或任意静态站点服务。部署时设置真实的 `VITE_NAQI_API_BASE` 后重新构建；它必须是浏览器可以访问的公开 API 基址，例如 `https://naqi-api.example.com`。

后端需要允许前端来源的 CORS：至少 `GET,POST,OPTIONS`，允许 `Authorization,Content-Type` 请求头，并允许上传的响应头按需暴露 `Content-Disposition`。如果前后端不同域，预检请求不能被鉴权中间件拦截。

建议生产环境由反向代理终止 HTTPS，并让后端的 API Key 或上游鉴权策略限制来源和权限。前端只在当前标签页的 `sessionStorage` 保存用户粘贴的 Bearer Key；关闭标签页后自动清除。界面、错误提示和下载逻辑都不会打印 API Key。

## 工作台功能

- 概览：显示 queued、running、succeeded、failed 数量和最近任务。
- 角色：上传原始 GLB，查看原始/已绑骨 GLB、SHA-256、来源、状态，鉴权后预览或下载。
- 动作：上传 MP4 和 camera mode，查看帧数、FPS、时长、SHA-256，播放原始/预览 MP4，下载 NPZ。
- 动画组合：选择 ready 的已绑骨角色和 ready 的动作，提交重定向，预览或下载动画 GLB。
- 任务：查看状态、阶段、时间和错误；详情入口会调用单任务接口并下载一个不含凭据的 JSON 快照。

当后端返回 404 时，界面会显示“后端版本暂不支持”，不会把未实现的接口当成空成功，也不会白屏。

## API 契约

前端当前按下列接口工作。列表响应既支持直接数组，也支持 `{ "items": [...] }`、`{ "data": [...] }` 或 `{ "results": [...] }`。

```text
GET  /health/live
GET  /v1/assets/characters
POST /v1/assets/characters                  multipart: file
GET  /v1/assets/motions
POST /v1/assets/motions                     multipart: file, camera_mode
GET  /v1/assets/animations
POST /v1/animations                          JSON: { character_id, motion_id }
GET  /v1/jobs
GET  /v1/jobs/{id}
GET  /v1/assets/{kind}/{id}/files/{file_kind}?download=false
```

资源下载的 `kind` 是 `characters`、`motions` 或 `animations`。常用 `file_kind`：

```text
characters: source_glb, rigged_glb
motions:    source_mp4, motion_npz, preview_mp4, preview_glb
animations: animated_glb
```

列表对象可提供 `id/name/status/source/sha256/created_at`，动作对象还可提供 `frames/fps/duration_seconds/camera_mode`。文件可放在 `files` 字段中，例如 `files.rigged_glb = { exists: true, filename: "character_rigged.glb" }`；前端仍使用上面的规范化文件接口，不信任服务器直接返回的文件路径。

## 鉴权预览机制

`model-viewer` 依赖通过 npm 打包，不使用 CDN。由于 `<video>` 和 `<model-viewer>` 的 `src` 不能自动附带 Bearer Header，前端先用 API client 发起带 `Authorization: Bearer ...` 的 `fetch`，把响应读成 Blob，再创建 `URL.createObjectURL(blob)` 交给媒体组件。组件卸载或资源切换时会 `revokeObjectURL`；下载也走同一条鉴权 Blob 路径。

因此后端文件接口必须支持鉴权的二进制响应，并返回正确的 `Content-Type`。`Content-Disposition` 可选，用于提供下载文件名。
