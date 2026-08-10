# 潮汐档案馆：失落的星图

面向 Aholo 专题赛道制作的第一人称 3D 解谜原型。玩家在被月海淹没的天文档案馆中移动、回收三枚信号密钥、破译轨道常量并开启星门。

## 运行

```powershell
cd demo/game
npm install
npm run dev
```

打开终端输出的本地地址，点击「进入档案馆」。使用 `WASD`/方向键移动、鼠标观察、`E` 交互、`J` 查看日志、`H` 获取提示、`Esc` 释放鼠标。若嵌入式预览不支持鼠标锁定，可按住左键拖动观察，移动仍然可用。

路演时可打开 `http://127.0.0.1:5173/?demo=1`：三枚密钥会预先写入日志，并在开场直接展示核心密码盘；默认地址始终是完整探索流程。

## 同步 Aholo 世界

API key 只在本地同步脚本中使用，不会进入浏览器包：

```powershell
$env:AHOLO_API_KEY='your-key'
$env:AHOLO_WORLD_ID='3FO4K4WYFVXB'
npm run sync-world
```

任务成功后，脚本会把 Aholo 生成的全景空间下载到 `public/generated/aholo-pano.jpg`，游戏启动时自动将它用作沉浸式世界背景。若任务仍在队列中，程序化 3D 档案馆仍可完整游玩。

需要持续等待并自动同步时运行 `npm run wait-world`；默认每 30 秒查询一次，最多等待 20 分钟。

## 交付构建

```powershell
npm run build
npm run preview
```

构建产物在 `dist/`。生成任务 ID 与状态保存在 `public/generated/world.json`，API key 从不写入静态文件。
