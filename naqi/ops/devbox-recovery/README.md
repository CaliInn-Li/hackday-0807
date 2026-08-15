# DevBox 不停机备份与从零恢复

本目录针对 DevBox 的实际持久化规则：`/home` 会保留，`/root`、`/data`、`/opt`、`/usr`
和 `/etc` 可能在机器重建后恢复初始状态。不要因为当前命令还能运行，就假设系统盘安装永久存在。

## 当前风险结论

| 内容 | 当前真实位置 | DevBox 重建后 |
|---|---|---|
| GVHMR 源码、Python 3.10、venv、权重、wheelhouse | `/home/naqi/GVHMR` | 保留 |
| SkinTokens 源码、Python 3.11、venv、权重、wheelhouse | `/home/naqi/SkinTokens` | 保留 |
| Backend venv、前后端代码、服务脚本 | `/home/naqi/demo-services` + GitHub | 保留/可重拉 |
| SQLite、上传资产、动画结果 | `/home/naqi/demo-data` | 保留，但仍需一致性备份 |
| Node 22 | mise 安装到 `/home/naqi/.local/share/mise` | 保留 |
| 系统 Node 24 | `/usr/bin/node` | 会丢，不应依赖 |
| Blender 4.5.12 | 原本在 `/opt/blender-4.5.12` | 会丢；必须使用 `/home` 归档恢复 |
| mise 可执行文件 | 原本在 `/usr/bin/mise` | 可能会丢；持久副本在 `/home/naqi/toolchains/mise/mise` |

三个 Python venv 的解释器和 `site-packages` 都在 `/home`。因此 DevBox 重建不会直接删掉
这些 Python 依赖。更重要的是，GVHMR 与 SkinTokens 的离线 wheelhouse 也在 `/home`，即使
venv 损坏仍有重建材料。

## 不停机备份

先确认没有 `queued/running` GPU 任务，然后运行：

```bash
cd /path/to/repo/naqi/ops/devbox-recovery
./backup_live.sh --hash-models
```

脚本不会停服务，并执行：

1. 检查 SQLite 中是否有运行或排队任务；有则拒绝复制，不会制造半成品备份；
2. 使用 SQLite online backup API 创建一致数据库副本；
3. 复制资产和运行记录，但排除瞬时上传目录与 WAL/SHM；
4. 创建完整 Git bundle；
5. 导出三套 Python 环境的包版本、解释器路径和 `pyvenv.cfg`；
6. 记录模型大小，可选计算 SHA-256；
7. 对备份内所有文件生成 SHA-256 manifest。

输出默认位于：

```text
/home/naqi/backups/naqi-live-YYYYmmddTHHMMSSZ/
```

验证并生成便于下载的单文件归档：

```bash
./verify_backup.py /home/naqi/backups/naqi-live-YYYYmmddTHHMMSSZ
./archive_backup.sh /home/naqi/backups/naqi-live-YYYYmmddTHHMMSSZ
```

它保护的是“系统盘重建”和误操作恢复。它仍和源数据位于同一块 `/home` 持久盘，不能替代
异地容灾。应把最终压缩包再复制到本机、NAS 或对象存储。

## 从 DevBox 重建恢复

适用于系统盘重建但 `/home/naqi` 仍存在：

```bash
cd /path/to/repo/naqi/ops/devbox-recovery
./restore_after_recreate.sh /home/naqi/backups/naqi-live-YYYYmmddTHHMMSSZ
./verify_devbox.sh
```

恢复脚本会：恢复持久 mise/Node 22、通过 Ubuntu 镜像安装 `ffmpeg` 与 Blender 最小运行库、
从 `/home` 单文件归档解出 Blender 到 `/opt`、重建 `/usr/local/bin/blender` 链接、必要时从
Git bundle 恢复代码、在持久数据缺失时恢复 `.env` 和在线数据库备份、重建前端，再启动
18000 网关与后端。`/home` 中已有数据库时会直接复用，不会覆盖。

Blender 保持为 `/home` 中的单文件压缩归档，只在 DevBox 重建后解到 `/opt`。不要把 Blender
的数千个小文件直接解压到 SeaweedFS 挂载的 `/home`，这会给网络文件系统造成不必要压力。

## `/home` 也损坏时

Git 仓库不能保存约 41GB 的 GVHMR/SkinTokens 环境和受许可约束的 SMPL/SMPL-X 模型。
要防范持久盘本身损坏，必须另做异地大文件备份：

```bash
tar -C /home/naqi -czf /path/on/NAS/naqi-ml-runtime.tar.gz \
  GVHMR SkinTokens toolchains
```

这份归档预计很大，不要放进 Git，也不要在本机空间不足时贸然生成。优先保存到 NAS/对象
存储，并在目标端运行 `gzip -t` 和 `sha256sum`。SMPL/SMPL-X 文件受许可约束，不应上传到
公开仓库。

## 快照边界

本流程不会调用 DevBox 快照，因为快照会立即重启并中断服务。只有确实修改了必须保留的
`/etc`、`/opt` 或 apt 系统包，且所有任务与数据均已保存后，才由管理员安排维护窗口拍快照。
本项目优先把可执行文件、模型、Python 和 Node 都放在 `/home`，尽量消除拍快照的必要性。

## SeaweedFS 挂载故障识别

如果看到以下组合，不要误判为代码、API key 或 Python 依赖损坏：

- 文件操作报 `Transport endpoint is not connected`；
- SSH 突然报 `Permission denied`，因为它无法读取 `/home/naqi/.ssh/authorized_keys`；
- `/health/live` 仍是 200，但前端静态文件为 503、资产 API 为 500。

这表示现有进程仍活着，但 `/home` 网络挂载不可用。不要反复重启服务或删除数据；从 DevBox
控制台检查/恢复 `/home` 挂载，恢复后先执行 `verify_devbox.sh`。大量小文件解压应放在系统盘，
不要直接对 SeaweedFS 展开 Blender、Node 或大型 Python wheel。

如果平台运维确认该 DevBox 由 Kubernetes Deployment 管理，可用 `sudo kill 1` 终止容器内
的 `supervisord`，由 Deployment 创建新 Pod 并重新挂载同一个 `/home` PVC。执行前必须先把
一致性备份下载到异地；不要在不清楚编排方式时把 `kill 1` 当作通用 Linux 重启命令。新 Pod
恢复后，先确认 `mountpoint /home`，再运行 `restore_after_recreate.sh`。
