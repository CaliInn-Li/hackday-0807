# Aholo 调研 & 零 ML 基础的选题建议

面向 README 里的两条赛道（Aholo Creator Track / Spatial Open Track），回答三个问题：
Aholo 是什么、它的 API 能给我什么、没有机器学习基础的人拿到 GPU 该干什么。

---

## 一、Aholo 是什么

Aholo 是群核科技（Manycore Tech，酷家乐 / Coohom 母公司）的**空间智能平台**，
技术底座是 **3D 高斯泼溅（3D Gaussian Splatting, 3DGS）**。

一句话理解 3DGS：它不是传统的"三角面片 + 贴图"模型，而是用几百万个带颜色、
透明度和朝向的"椭球点"来表示一个空间。好处是**重建快、看着像照片、能在浏览器里实时跑**；
代价是它天然没有语义、没有碰撞体、不好直接编辑——**这些"缺口"恰恰是 hackday 最好的切入点**。

平台分三层：

| 层 | 面向 | 入口 |
|---|---|---|
| 空间创作平台 (3D Studio) | 普通创作者，手机扫描建空间 | `aholo3d.cn` / `aholo3d.com` |
| 企业平台 | 多设备采集 → 全终端展示 | 同上 |
| **Spatial Labs** | **开发者：API / SDK / 数据集 / MCP** | **`labs.aholo3d.cn`（国内）** |

比赛只需要关心第三层 Spatial Labs。

---

## 二、API 能力清单（这是你真正能用的东西）

网关：国内 `https://api.aholo3d.cn`，海外 `https://api.aholo3d.com`（路由带 `/global` 前缀）。
鉴权是请求头 `Authorization: <API key>`，**注意没有 `Bearer` 前缀**。
API Key 在 `labs.aholo3d.cn/api-keys` 申请。

### 1. Asset — 文件上传
先拿上传凭证，把图片/视频传到对象存储，拿到公网 URL 再喂给后面的接口。
SDK 已经封装好了（支持分片、断点续传、进度回调），基本不用自己管。

### 2. World — 3DGS 世界（核心）

| 能力 | 输入 | 说明 |
|---|---|---|
| **重建 Reconstruction** | ≥20 张图片 / `.mp4`·`.mov` 视频 / Insta360 全景 `.insv` | 把**真实空间**变成 3DGS |
| **生成 Generation** | 一句 prompt，或 1 张图，或两者结合 | 凭空**生成**一个 3D 世界；**室内效果最好**，非室内还是 beta |

异步任务：创建后拿到 `worldId` → 轮询状态 → 成功后下载 **PLY / SPZ** 产物。
SDK 里 `world.waitFor(worldId)` 一行搞定轮询。

### 3. Lux3D — 单体 3D 物件生成
和 World 互补，World 管"空间"，Lux3D 管"物件"，而且**输出高质量 PBR 材质**：
- 图生 3D、文生 3D（可带参考图）
- **材质迁移**：给已有模型换一套材质
- 输出 glb / usdz / obj / fbx / zip，能直接丢进 Three.js、Blender、Unity

### 4. RenderCloud — 云端离线渲染
OpenUSD 离线渲染任务。适合最后出一段高质量的宣传片/成片。

### 5. Skills & MCP
官方提供 Agent Skills 和 MCP Server，可以直接挂到 Cursor / Claude 里，
**让 AI 帮你写调 Aholo API 的代码**。零 ML 基础的人强烈建议先装上这个，能省掉大量看文档的时间。

---

## 三、开源生态（免费且好用，别浪费）

### `@manycore/aholo-viewer` — MIT 协议的 3DGS 网页渲染器
- 仓库 `manycoretech/aholo-viewer`（默认分支 `master`），文档站 `aholojs.dev`
- Chunked Streaming LOD：**上亿高斯点的场景能在浏览器里流畅漫游**，10 秒内出首屏
- 兼容 PLY / SPZ / SOG / LCC
- 配套工具链 `splat-transform`：格式转换、编辑、**体素碰撞体生成**（做游戏的关键！）、walk mode

这意味着你的作品可以是**一个网页链接**——评委点开就能玩，这是 demo 环节的巨大优势。

### `spatialverse/InteriorGS` — 带语义标注的室内 3DGS 数据集
- HuggingFace `spatialverse/InteriorGS`，GitHub `manycore-research/InteriorGS`
- **1000 个室内场景**（752 个住宅 + 248 个公共空间：音乐厅、游乐场、健身房……）
- **554,000+ 物体实例，755 个类别**，每个物体带 3D 有向包围盒 + 语义标签（JSON）
- 每个场景还有 **occupancy map（可通行区域图）**，直接支持导航任务
- 数据是 SuperSplat 压缩过的 PLY，坐标系 XYZ =（右、后、上），单位米
- 许可证是自定义的 `InteriorGS Terms of Use`，**用之前先扫一眼 PDF 条款**

这是**唯一一个能让你在 GPU 上做"真训练"而不用自己采数据**的资源。

---

## 四、没有 ML 基础，GPU 到底该怎么用

先说一个反直觉但很重要的判断：

> **在 hackday 上，"训练一个模型"几乎从来不是加分项，"做出一个能玩的东西"才是。**
> 评委看的是完成度和惊艳感。一个训练了 3 小时、loss 曲线很漂亮但没有 demo 的项目，
> 一定输给一个全用现成模型、但评委能上手玩 30 秒的项目。

所以把 GPU 分成三档来用，**优先级从上往下递减**：

### 第 1 档（强烈推荐）：用 GPU 跑**推理**，把大模型当积木

这一档零门槛、零风险、效果最好。GPU 在这里的作用是"让你不用买 API、不限速、能实时"。

- **本地 VLM**（Qwen3-VL / InternVL 之类）：看一张场景截图，说出里面有什么、
  房间是什么风格、有什么安全隐患 —— 给 3DGS 场景补上它天生缺失的"语义"
- **本地 LLM**：驱动 NPC 对话、把一句话展开成一串世界生成 prompt、做 agent 编排
- **Diffusion（SD / Flux）**：生成贴图、天空盒、把重建场景的渲染图做风格化
- **ASR + TTS**（Whisper / CosyVoice）：语音进、语音出，做"和房间对话"的交互
- **SAM / YOLO / CLIP**：对渲染出的视角图做分割、检测、以文搜物

用 vLLM / Ollama / ComfyUI 起服务，都是一条命令的事，不需要懂任何 ML 理论。

### 第 2 档（推荐，作为"技术亮点"）：跑一个**不需要 ML 理论**的训练任务

这两个都是"跑脚本"级别的，但在答辩时可以理直气壮说"我们自己训练了"：

- **自己训 3DGS**：用开源的 `gsplat` / `nerfstudio (splatfacto)` 跑你自己拍的素材。
  3DGS 本身就是一个 GPU 优化（训练）过程，单场景在 4090 上大概几十分钟。
  **最大价值是可以和 Aholo API 的结果做对比**，做成一张"自建 vs 平台"的评测表——
  这在 Aholo 赛道上是很讨喜的技术单项奖素材。
- **LoRA 微调**：拿 20~50 张图微调 SDXL/Flux 出一个风格 LoRA（比如公司吉祥物、
  某种美术风格），用 kohya / diffusers 的现成脚本，24GB 显存一小时内能出结果。
  然后用它来给 3DGS 场景做风格化。

### 第 3 档（有余力再碰）：基于 InteriorGS 做**真正的监督学习**

有 GPU + 有标注数据，可以做，但这是唯一有"翻车风险"的一档，别把它放在主线上：

- 用 occupancy map 训一个小网络预测可通行区域（本质是图像分割，有大量模板代码）
- 用 3D 包围盒 + 语义标签，做房间类型分类、物体检索
- 用 LLaMA-Factory 把 InteriorGS 的标注转成"空间问答"数据，微调一个小 VLM

**建议：先把第 1 档做出可玩的 demo，再回头加第 2 档当亮点。第 3 档纯属加分。**

---

## 五、六个具体选题

每个都标了赛道匹配、GPU 用在哪、API 用在哪、以及**评委看到什么会"哇"一声**。

### 选题 1：会说话的房间（Talking Space）⭐ 最推荐给单人

- **赛道**：Aholo Creator Track（也符合 OPT 单人奖）
- **做什么**：手机拍一段公司/家里的视频 → Aholo 重建成 3DGS → 用 aholo-viewer 放到网页里
  → 用户第一人称漫游 → **点击场景里任何一个位置，本地 VLM 看着当前视角截图，
  用语音讲出这里是什么、有什么故事**
- **GPU**：VLM 推理 + TTS，全本地，实时
- **API**：`asset.uploadFile` → `world.reconstructions.create` → 下载 PLY
- **哇点**：评委在浏览器里走进一个他认识的真实房间，点一下，房间开口说话了
- **难点**：把屏幕点击映射回 3D 位置；最简单的做法是直接截当前视角的图喂给 VLM，绕过 3D 拾取

### 选题 2：把你的办公室做成一个游戏关卡

- **赛道**：Aholo Creator Track
- **做什么**：重建真实办公室 → 用 `splat-transform` 生成**体素碰撞体** → 加上第一人称移动、
  跳跃、射击/解谜 → 用 Lux3D 图生 3D 把同事的马克杯之类的小物件变成可拾取道具
- **GPU**：Lux3D 是云端的，GPU 可以用来跑 LLM 生成关卡剧情/谜题，或做实时风格化
- **API**：World 重建 + Lux3D 图生 3D
- **哇点**：在自己每天上班的地方里跳来跳去，代入感极强
- **难点**：碰撞体质量决定手感，务必早点跑通这一环

### 选题 3：一句话造世界 —— AI 关卡/密室生成器

- **赛道**：Spatial Open Track
- **做什么**：用户输入一个主题（"废弃的赛博朋克网吧"）→ 本地 LLM 把它展开成
  多个房间的 prompt + 谜题逻辑 + 叙事文本 → 逐个调 `world.generations.create` 生成 3D 空间
  → 串成一个可通关的密室逃脱
- **GPU**：LLM 做 agent 编排（prompt 扩写、谜题生成、一致性校验）
- **API**：World 生成（文生 / 图生），**注意室内场景效果最好，正好和密室题材契合**
- **哇点**：现场让评委说一个主题，几分钟后一个可玩的密室诞生了
- **难点**：生成是异步的、有耗时。**必须预生成一批做兜底，绝不能在台上等 loading**

### 选题 4：空间风格穿越（Style Portal）⭐ 最适合展示"训练"

- **赛道**：Aholo Creator Track / Spatial Open Track 都行
- **做什么**：重建一个真实场景 → 从多个视角渲染出图 → 用 Diffusion + 你自己训的风格 LoRA
  做 img2img 风格化 → **用 gsplat 拿这批风格化的图重新训练一个 3DGS** →
  得到"同一个空间的赛博朋克版 / 水下版 / 乐高版"，可以在两个世界间无缝切换
- **GPU**：LoRA 微调 + Diffusion 推理 + gsplat 训练，**三档全用上了**
- **API**：World 重建拿原始场景
- **哇点**：滑动一个滑块，你的办公室从现实渐变成另一个宇宙
- **难点**：多视角风格化的一致性（不同角度风格会漂移）。缓解办法：固定 seed、
  用 ControlNet 锁深度、或者干脆只做少量关键视角

### 选题 5：室内空间理解 Benchmark（"帮我找到红色沙发"）

- **赛道**：Spatial Open Track
- **做什么**：拿 InteriorGS 的场景 + occupancy map 搭一个简单的导航环境 →
  给本地 VLM 一条自然语言指令（"去客厅找红色的沙发"）→ VLM 看当前视角决定往哪走 →
  **量化统计成功率**，做成一个小 benchmark 网页，对比几个不同模型
- **GPU**：VLM 大量推理（这个很吃 GPU，正好用上资源）
- **API**：可选，主要吃开源数据集
- **哇点**：这是具身智能 / VLN 的前沿方向，学术味最足，容易拿技术类单项奖
- **难点**：搭导航环境有工程量。**这是六个里技术最硬但 demo 观赏性最弱的**，
  单人别选，除非队里有人熟悉这块

### 选题 6：拍一张照片，生成一屋子家具（AI 家装 agent）

- **赛道**：Aholo Creator Track
- **做什么**：重建真实房间 → VLM 识别现状和风格 → LLM 给出改造建议 →
  用 Lux3D 文生 3D 生成对应家具（带 PBR 材质）→ 把 glb 摆回 3DGS 场景里 →
  用 RenderCloud 出一段改造前后对比的成片
- **GPU**：VLM + LLM 推理
- **API**：World 重建 + Lux3D 文生 3D + 材质迁移 + RenderCloud
- **哇点**：API 覆盖面最全，"改造前 / 改造后"对比视频天然有说服力
- **难点**：把 glb 和 3DGS 对齐到同一坐标系、尺度、光照，比想象中麻烦

---

## 六、如果只让我推荐一个

**单人参赛（冲 OPT 奖）：选题 1「会说话的房间」，有余力就加选题 4 的风格切换。**

理由：
1. 技术栈全是现成积木，没有任何一环需要 ML 理论
2. 输出是一个网页链接，评委随时能玩，demo 零成本
3. "真实空间 + AI 语义"正好命中赛道关键词，不会被判偏题
4. 完成度可以分层：先做能走的 3D 场景（保底），再加点击问答（合格），
   再加语音（出彩），再加风格切换（惊艳）。**任何一层断了都还有能交付的东西**

---

## 七、踩坑清单（这部分比选题更值钱）

### 关于拍摄和重建
- **重建质量 90% 取决于拍摄质量**，不是取决于算法。慢速、匀速、绕圈走，
  保证相邻帧有大量重叠，最后回到起点形成闭环
- **杀手场景**：镜子、玻璃、纯白墙面、强反光地板、纯色无纹理区域 —— 这些地方一定会烂，
  选场景时主动避开
- 光照要均匀且**全程不变**，别中途开关灯，别在有强烈阴影移动的时间段拍
- 手机拍的话关掉自动对焦呼吸，尽量用广角，走慢一点避免运动模糊
- 图片输入要 **≥20 张**，文件后缀必须和 `type` 字段对得上，否则接口直接拒

### 关于 API
- 重建/生成都是**异步任务，耗时以分钟计**。整个开发流程要围绕这个设计
- **绝对不要在答辩现场发起一个新任务然后等它跑完**。
  提前跑好几个场景，PLY 存本地，demo 走本地文件，API 调用只在录屏里展示
- 国内用 `region: 'cn'`，鉴权头没有 `Bearer` 前缀（很容易踩）
- API Key 走环境变量 `AHOLO_API_KEY`，别硬编码提交进仓库
- 留意配额和限流，`RateLimitError` 要有重试
- 时间戳 `createTime` / `updateTime` 是 **Unix 毫秒**

### 关于工程
- **第一件事就是把 Aholo 的 MCP / Agent Skill 挂到 Cursor 里**，让 AI 替你读文档写调用代码
- 先跑通"上传 → 重建 → 下载 PLY → 在 aholo-viewer 里显示"这条**最小闭环**，
  这一步跑通之前不要写任何业务逻辑
- 3DGS 文件很大，本地开发注意别提交进 git，加 `.gitignore`
- 提前准备好**录屏**。现场网络、显卡、投影都可能出问题，视频是你的保险

### 关于节奏
按这个顺序推进，每一步都保证有个能跑的版本：

1. 申请 API Key，装 SDK，跑通官方 quickstart 的 hello world
2. 拍素材（**最先做，因为重建要排队，而且拍砸了要重拍**）
3. 跑通最小闭环：重建 → PLY → 网页里能看能走
4. 接上 GPU 上的模型，做出第一个交互
5. 加亮点功能（语音 / 风格化 / 自训模型对比）
6. 打磨 UI、写 PPT、**录屏兜底**

---

## 参考链接

- Spatial Labs（申请 Key、API 文档、MCP）：https://labs.aholo3d.cn · https://labs.aholo3d.com
- API 文档：https://labs.aholo3d.com/api-docs/en
- 官方 SDK（TS / Python / Java）：https://github.com/manycoretech/aholo-spatial-sdk
- 开源渲染器 aholo-viewer：https://github.com/manycoretech/aholo-viewer · https://aholojs.dev
- InteriorGS 数据集：https://huggingface.co/datasets/spatialverse/InteriorGS · https://github.com/manycore-research/InteriorGS
- 相关论文（InteriorGS + 具身导航）：https://arxiv.org/abs/2510.21307
- 开源 3DGS 训练：https://github.com/nerfstudio-project/gsplat
