# 本地 DevBox 备份落点

这里保存从远程 `/home/naqi/backups` 下载的加密边界内备份，不提交二进制归档到 Git。

首次已验证备份：

```text
远程目录：/home/naqi/backups/naqi-live-20260815T123003Z
远程归档：/home/naqi/backups/naqi-live-20260815T123003Z.tar.gz
本地归档：naqi/backups/naqi-live-20260815T123003Z.tar.gz
大小：256138941 bytes
SHA-256：80379f33e02b2f871432826753441397e4abac9b5459ea7c24d5335c86bb49c2
```

该归档包含服务数据库、资产、配置、Git bundle、Python 包清单和模型哈希清单；约 41GB 的
GVHMR/SkinTokens 模型与 venv 仍由远程 `/home` 持久盘保存，不在本归档中重复存储。

备份和恢复方法见 [`../ops/devbox-recovery/README.md`](../ops/devbox-recovery/README.md)。
