# 资产工作台 API 契约（草案）

这个契约用于解耦未来可独立迁仓的 `backend` 和 `frontend`。原型流水线脚本
不属于 HTTP 契约，后端通过可配置执行器调用它们。

## 资产关系

```text
Character.source_glb -> rig job -> Character.rigged_glb
Motion.source_mp4    -> motion job -> Motion.motion_npz + optional preview
Character.rigged_glb + Motion.motion_npz -> retarget job -> Animation.animated_glb
```

`Character`、`Motion` 和 `Animation` 都使用 UUID。任务和资产分离：一个资产可以
经历失败后重试，不需要更换资产 ID；每次执行仍有独立 job ID、日志和时间记录。

## 通用约定

- API 前缀：`/v1`；
- 鉴权：`Authorization: Bearer <NAQI_API_KEY>`；
- 时间：UTC ISO-8601；
- 列表返回 `{ "items": [...], "total": n }`；
- 异步操作返回 HTTP `202`，响应同时包含 asset 和 job；
- 状态：`pending | queued | running | ready | failed | cancelled`；
- 文件响应默认 `Content-Disposition: inline`，`?download=true` 时为 attachment；
- MP4 文件端点支持 HTTP Range；GLB/NPZ/MP4 返回正确 MIME；
- 每个文件元数据包含 `file_kind`、`filename`、`size_bytes`、`sha256` 和 `mime_type`；
- 客户端不能提交服务器路径，只能提交文件或已有资产 ID。

## 角色资产

### `GET /v1/assets/characters`

返回角色列表。最小字段：

```json
{
  "id": "uuid",
  "name": "雪帽少女",
  "status": "ready",
  "created_at": "2026-08-15T00:00:00Z",
  "source_glb": {"filename": "character.glb", "sha256": "...", "size_bytes": 1},
  "rigged_glb": {"filename": "character_rigged.glb", "sha256": "...", "size_bytes": 1},
  "latest_job_id": "uuid"
}
```

### `POST /v1/assets/characters`

`multipart/form-data`：`file=.glb`、可选 `name`。创建角色并排队 rig job。

## 动作资产

### `GET /v1/assets/motions`

最小字段包含原 MP4、动作 NPZ、可选 `preview_mp4`/`preview_glb`，以及
`frames`、`fps`、`duration_seconds`。

### `POST /v1/assets/motions`

`multipart/form-data`：`file=.mp4`、`camera_mode=static|moving`、可选 `name`。
创建动作并排队 GVHMR motion job。

## 动画组合

### `GET /v1/assets/animations`

返回已经生成的组合资产及其 character/motion 来源。

### `POST /v1/animations`

```json
{
  "character_id": "ready-character-uuid",
  "motion_id": "ready-motion-uuid",
  "render_keyframes": false
}
```

只有 ready 的 rigged GLB 和 ready 的 NPZ 可以组合。该操作只执行 retarget/QA，
不得重新运行 SkinTokens 或 GVHMR。

## 文件访问

### `GET /v1/assets/{kind}/{id}/files/{file_kind}`

允许的 `kind`：`characters | motions | animations`。允许的 `file_kind` 由资产类型
白名单决定，例如：

- character：`source_glb | rigged_glb | topology_report | mapping`；
- motion：`source_mp4 | motion_npz | manifest | preview_mp4 | preview_glb`；
- animation：`animated_glb | retarget_report | qa_report`。

服务端从数据库解析真实路径；`file_kind` 不能被当作任意相对路径拼接。

## 任务

### `GET /v1/jobs`

当前支持 `limit`、`offset` 分页；状态与类型过滤可在独立部署阶段继续扩展。

### `GET /v1/jobs/{id}`

返回 `type`、`status`、`stage`、输入资产、输出资产、`created_at`、`started_at`、
`finished_at`、`error_code`、安全化错误摘要和日志/产物链接。

### `POST /v1/jobs/{id}/cancel`

queued 任务直接取消；running 任务终止整个子进程组。已结束任务返回冲突状态，
不能修改历史结果。

## 缓存与复用

后端先计算上传文件 SHA-256。缓存命中必须同时匹配输入哈希、模型/脚本版本和
影响结果的参数：

- rig：GLB 哈希 + SkinTokens 版本 + rig 参数；
- motion：MP4 哈希 + camera mode + GVHMR 版本 + motion 参数；
- animation：rigged GLB 哈希 + NPZ 哈希 + mapping/retarget 版本。

命中 ready 缓存时直接返回已有资产并标记 `cache_hit=true`，不创建 GPU 任务；
失败或取消的同哈希资产会复用原资产 ID 并创建新的重试 job。
