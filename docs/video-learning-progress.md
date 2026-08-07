# 参考视频 Technique Learning 计划进度

更新时间：2026-08-07
执行分支：`feature/director-learning-loop`

## 总体进度

- 计划视频：11 支
- 已完成正式学习：9 支
- 已开始但未完成：0 支
- 未开始正式学习：2 支
- 完成率：9/11（81.82%）

前六支 Study 的完成状态按各条目完成时的证据与门禁成立。2026-08-01 以前的条目只保留了“实际请求字符数”，不能追溯声明已经验证 UTF-8 body 字节数；自完整请求字节门禁落地后，任何新增或重新生成的 Study 必须同时具备完整视频分析、可用 ASR/语义证据、人工重点区间复核、context packet 严格 `<180,000` 字符、包含实际 instructions/input/tools 等字段的最终请求 body 严格 `<200,000` UTF-8 字节及 body SHA-256，以及已提交的正式 `technique-study.<BV>.v1.json`。等于任一上限也必须阻断；仅下载代理视频、提取开场或生成预分析素材不算完成。

## 明细

### 1. BV1C3546DEC6 — 已完成

- 标题：[去邻国打探一下樱花开的如何....一个人旅行VLOG樱花季](https://www.bilibili.com/video/BV1C3546DEC6/)
- 时长：约 49 分 12 秒
- 已完成：完整分析、ASR、弹幕与人工重点区间复核、受限模型上下文、正式 technique study。
- 正式产物：`reference-learning/technique-study.BV1C3546DEC6.v1.json`
- 证据规模：797 个镜头、41 个事件、655 个转写片段、12 条 technique observations。
- 模型上下文：97,623 字符，符合严格 `<200,000` 门禁。

### 2. BV1CrHwzUEJa — 已完成

- 标题：[每一幕都是我的理想人生...瑞士一个人旅行VLOG](https://www.bilibili.com/video/BV1CrHwzUEJa/)
- 时长：约 35 分 59 秒
- 已完成：完整分析、ASR、弹幕与人工重点区间复核、受限模型上下文、正式 technique study。
- 正式产物：`reference-learning/technique-study.BV1CrHwzUEJa.v1.json`
- 证据规模：627 个镜头、31 个事件、632 个转写片段、17 条 technique observations。
- 模型上下文：95,102 字符，符合严格 `<200,000` 门禁。

### 3. BV19sm2BBEDd — 已完成

- 标题：[《一个人的欧洲探险记》瑞士篇完整版](https://www.bilibili.com/video/BV19sm2BBEDd/)
- 时长：13,397.336 秒（约 3 小时 43 分 17 秒）
- 已完成：完整视频分析、完整 ASR、弹幕与人工重点区间复核、受限模型上下文、实际外层模型请求门禁、正式 technique study。
- 正式产物：`reference-learning/technique-study.BV19sm2BBEDd.v1.json`
- 证据规模：3,608 个镜头、187 个事件、2,905 个转写片段、12,934 个词、19 条 technique observations；ASR 最后对白到 13,338.1 秒（99.56%），尾部经人工确认是片尾字幕、credits 与风景 inset。
- 模型上下文：168,801 字符，严格 `<180,000`；加入任务约束后的实际序列化模型请求为 121,655 字符，严格 `<200,000`。
- 独立性限制：0–2,159.44 秒与 `BV1CrHwzUEJa` 存在实质内容重叠；本 study 的正式 observations 全部取自该时间点之后，避免把重叠镜头计为新的跨来源支持。

### 4. BV1ETNMzEEWQ — 已完成

- 标题：[《最伟大的作品》封面取景地 法国一个人旅行VLOG 圣米歇尔山](https://www.bilibili.com/video/BV1ETNMzEEWQ/)
- 时长：3,038.453 秒（约 50 分 38 秒）
- 已完成：重新下载本机代理、完整视频分析、完整 ASR、弹幕与人工重点区间复核、受限模型上下文、实际外层模型请求门禁、正式 technique study。
- 正式产物：`reference-learning/technique-study.BV1ETNMzEEWQ.v1.json`
- 证据规模：720 个镜头、43 个事件、722 个音频段、526 个转写片段、2,841 个词、16 条 technique observations；ASR 最后对白到 3,035.42 秒（99.90%），尾部经人工确认是收束画面与黑底“谢谢观看”结束卡。
- 模型上下文：98,192 字符，严格 `<180,000`；加入任务约束后的实际序列化模型请求为 69,704 字符，严格 `<200,000`。

### 5. BV1aDHQejEAP — 已完成

- 标题：[《一个人的东京探险记》完整版](https://www.bilibili.com/video/BV1aDHQejEAP/)
- 时长：8,909.885 秒（约 2 小时 28 分 30 秒）
- 已完成：完整代理解码验证、串行恢复 `small / zh` 全片 ASR、尾段无 VAD 与低门限核验、完整镜头/事件/音频分析、公开弹幕定位、人工连续画面与短音频声学复核、受限上下文、实际外层模型请求门禁和正式 technique study。
- 正式产物：`reference-learning/technique-study.BV1aDHQejEAP.v1.json`
- 证据规模：4,627 个镜头、130 个事件、1,746 个音频段、1,298 个转写片段、5,173 个词、18 条 technique observations；自动复核包含 24 张事件联系表和 95 张关键帧，另有 24 张人工概览联系表和 13 张密集联系表。
- ASR 覆盖：ASR 报告处理到 8,909.868 秒，为媒体时长的 99.9998%；尾段核验只合并 8,822.13 至 8,832.81 秒内五段有声画支持的对白，最后可信对白到 8,832.81 秒，剩余 77.075 秒为配乐/环境声、credits、步行和收机余韵，无其他可信对白。
- 弹幕边界：共 5,607 条，覆盖到 8,909.104 秒；只用于复核定位和描述观众信号，不作为剪辑、配乐、字幕、VFX、音效或叙事因果证据。
- 模型上下文：149,474 字符，严格 `<180,000`；加入 Schema、任务约束和人工证据后的实际序列化模型请求为 112,991 字符，严格 `<200,000`。
- 门禁结果：Study Schema、JSON/UTF-8 无 BOM、中文与时间边界检查通过；15 项针对性 unittest、48 项 director 全量 unittest 全部通过；五来源聚合为 20 条稳定模式和 26 条单来源模式，显式 `minimum_source_support=2`。

### 6. BV1TNZUB4EF6 — 已完成

- 标题：[非常紧绷的旅行..法国一个人旅行Vlog巴黎](https://www.bilibili.com/video/BV1TNZUB4EF6/)
- 时长：2,986.32 秒（约 49 分 46 秒）
- 已完成：完整代理解码验证、`small / zh` 全片 ASR、尾段无 VAD 与低门限核验、完整镜头/事件/音频分析、公开弹幕定位、人工连续画面与短音频声学复核、受限上下文、实际外层模型请求门禁和正式 technique study。
- 正式产物：`reference-learning/technique-study.BV1TNZUB4EF6.v1.json`
- 证据规模：748 个镜头、40 个事件、512 个音频段、522 个转写片段、2,361 个词、20 条 technique observations；自动复核包含 24 张事件联系表和 96 张关键帧，另有 31 张人工概览联系表、7 张细节表和 14 段短音频声学复核。
- ASR 覆盖：ASR 报告处理到 2,986.295 秒，为媒体时长的 99.9992%；最后可信对白到 2,976.77 秒。无 VAD 与低门限两次尾检均到 2,976.78 秒“拜拜”，剩余约 9.54 秒为无新增对白的 CRT 圣米歇尔山前钩，无需修复正式 transcript。
- 弹幕边界：共 3,247 条，覆盖到 2,986.301 秒；只用于复核定位和描述观众信号，不作为剪辑、配乐、字幕、VFX、音效或叙事因果证据。
- 模型上下文：96,358 字符，严格 `<180,000`；加入 Schema、任务约束和人工证据后的实际序列化模型请求为 73,177 字符，严格 `<200,000`。
- 门禁结果：Study Schema、JSON/UTF-8 无 BOM、中文与时间边界检查通过；15 项针对性 unittest、48 项 director 全量 unittest 全部通过；六来源聚合为 21 条稳定模式和 34 条单来源模式，显式 `minimum_source_support=2`。

### 7. BV15XMC6KETm — 已完成

- 标题：[这里是世界第一城！！纽约！](https://www.bilibili.com/video/BV15XMC6KETm/)
- 时长：1,901.01 秒（约 31 分 41 秒）
- 已完成：代理双流完整解码、完整视频分析、small / zh 全片 ASR、尾部覆盖核验、完整镜头/事件/音频与语义证据、人工重点区间复核、受限上下文、实际外层模型请求门禁和正式 technique study。
- 正式产物：reference-learning/technique-study.BV15XMC6KETm.v1.json
- 证据规模：636 个镜头、23 个事件、316 个音频段、996 个转写片段、5,671 个词、18 条 technique observations。
- ASR 覆盖：ASR 报告处理到 1,901.013 秒；最后可信对白到 1,899.17 秒“再见”，与媒体末尾相差约 1.84 秒，可信对白覆盖率 99.9032%。
- 人工复核：检查开场、雨天计划转折、《老友记》场景揭示和人物反应、中央公园美景、七年前电影记忆回环、球场现场与主题峰值、字幕层级和夜景收束；未使用 OCR，不声明字幕逐字完全正确。
- 模型上下文：79,770 字符、92,764 UTF-8 字节，严格小于 180,000 字符；包含 instructions/input/tools 和人工证据的最终 Responses body 为 78,573 UTF-8 字节，严格小于 200,000，body SHA-256 为 adca819b653cb9986d3a879e2c84ea0ea54778d5bb6b4eb82c9f789f0ea55f18。
- 证据限制：参考成片只支持正向保留模式；没有原始素材映射，不能推断作者真实删片偏好。未确认 speed ramp、具体播放倍率、复杂遮罩转场、独立音效、曲名、BPM 或逐拍因果。
- 门禁结果：45 项参考学习专项 unittest 和 307 项 director 全量 unittest 全部通过（3 项按设计跳过）；正式 JSON/Schema、七来源 aggregate smoke、UTF-8 无 BOM、本地绝对路径与敏感信息扫描、changed-media 扫描及 git diff --check 通过。

### 8. BV1a7Tj6nEe9 — 已完成

- 标题：[外国人严选VS本地人推荐，两种玩法打开最反差的重庆](https://www.bilibili.com/video/BV1a7Tj6nEe9/)
- 时长：1,848.448 秒（约 30 分 48 秒）。
- 已完成：代理双流完整解码、small / zh 全片 ASR、尾部覆盖核验、完整镜头/事件/音频与语义分析、人工重点区间复核、受限上下文、实际外层请求门禁和正式 technique study。
- 正式产物：`reference-learning/technique-study.BV1a7Tj6nEe9.v1.json`
- 证据规模：583 个镜头、22 个事件、361 个音频段、1,134 个转写片段、6,275 个词、18 条 technique observations。
- ASR 覆盖：ASR 报告处理到 1,848.448 秒；最后可信对白到 1,844.6 秒“我们下期再见”，与媒体末尾相差约 3.85 秒，可信对白覆盖率 99.7917%。
- 人工复核：检查开场双视角命题、外国游客热门路线、机车动作与反馈、中段本地路线转折、社交照片与真实地点、山城巷老照片和相册、社区步道与居民互动、防空洞历史、字幕证据层和结尾综合；未使用 OCR，不声明字幕逐字完全正确。
- 模型上下文：81,728 字符、96,508 UTF-8 字节，严格 `<180,000` 字符；包含 instructions/input/tools 和人工证据的最终 Responses body 为 82,000 UTF-8 字节，严格 `<200,000`，body SHA-256 为 `7123a92f39f82496397e5d7f273edd3c197a1505bce2c1265a13e7c8c07a6c53`。
- 证据限制：参考成片只支持正向保留模式；没有原始素材映射，不能推断作者真实删片偏好。未确认 speed ramp、具体倍率、复杂遮罩转场、独立音效、曲名、BPM 或逐拍因果；外部短视频、照片、档案、历史数字与群体观点需独立核验。

### 9. BV1TYVA6sEhm — 已完成

- 标题：[不办婚礼去旅行结婚，我们后悔了吗？](https://www.bilibili.com/video/BV1TYVA6sEhm/)
- 时长：1,603.008 秒（约 26 分 43 秒）。
- 已完成：匿名低清代理下载、HEVC 视频流与 AAC 音频流分别完整解码、small / zh 全片 ASR、完整镜头/事件/音频与语义分析、尾部覆盖核验、人工重点区间复核、受限 context、完整 Responses body 门禁和正式 technique study。
- 正式产物：`reference-learning/technique-study.BV1TYVA6sEhm.v1.json`
- 证据规模：475 个镜头、19 个事件、198 个音频段、1,207 个转写片段、5,909 个词、19 条 technique observations；人工复核包含 19 张事件联系表、5 张全片分段概览、1 张尾部密集联系表和 12 张选定事件表。
- ASR 覆盖：ASR 报告处理到 1,603.008 秒；最后可信主持人对白到 1,578.6 秒“再见”，与媒体末尾相差 24.408 秒，可信对白覆盖率 98.4774%。尾部密集抽帧显示旅行合影、海岸、沙丘、夕阳与 credits；关闭 VAD 的独立尾检只产生低可信重复英文，按配乐或 ASR 不确定性处理，不并入主持人对白。
- 人工复核：检查开场成本选择题和旅行证据、四章结构、传统婚礼对照、目的地推荐与美景、头纱和拍摄工具、夫妻相处笑点、父母沟通转折、《老友记》情绪峰值、赞助/字幕/编号图卡层和片尾收束；未执行 OCR，不声明字幕逐字完全正确。
- 模型上下文：77,113 字符、91,589 UTF-8 字节，严格 `<180,000` 字符；包含 model、instructions、input、tools、text JSON Schema 和人工证据的最终 Responses body 为 91,292 字符、105,806 UTF-8 字节，严格 `<200,000`，body SHA-256 为 `a590a866d24766155f4bdb2125e99b094d2503f51423e97a0a3510025ff17d7b`。
- 证据限制：参考成片只支持正向保留模式；没有原始素材映射，不能推断作者真实删片偏好。未确认 speed ramp、具体倍率、复杂转场机制、独立音效、曲名、BPM、ducking 数值或逐拍因果；婚礼金额、目的地条件、产品功效、家庭建议和外部影视片段需独立核验。
- 门禁结果：正式 Study 运行时与 Schema、JSON/UTF-8 无 BOM、中文、时间边界、本地绝对路径与敏感信息扫描通过；九来源聚合为 26 条稳定模式和 60 条单来源模式，显式 `minimum_source_support=2`。

### 10. BV1Mi536EELv — 未开始

- 标题：[欧洲最混乱的老城和顶级富豪岛，差距能有多大？](https://www.bilibili.com/video/BV1Mi536EELv/)
- 时长：约 1,912 秒。
- 当前状态：未下载媒体、未执行完整分析或 ASR、未生成人工复核与正式 technique study，不计入正式聚合来源。

### 11. BV11Ao7BYEyv — 未开始

- 标题：[泰拳女王给我当陪练，是种怎样的体验!?](https://www.bilibili.com/video/BV11Ao7BYEyv/)
- 时长：约 2,214 秒。
- 当前状态：未下载媒体、未执行完整分析或 ASR、未生成人工复核与正式 technique study，不计入正式聚合来源。

## 已沉淀的跨视频结果

当前九支已完成视频可聚合出：

- 完整来源数：9
- 稳定模式：26 条（显式 `minimum_source_support=2`）
- 单来源模式：60 条
- 正式聚合产物：`reference-learning/reference-techniques.aggregate.v1.json`
- 聚合命令：`vlog-director aggregate-techniques`
- 当前限制：`BV19sm2BBEDd` 的重叠首日不生成新增 observation。单来源模式不能计为稳定跨来源模式，开场预分析或未完成视频也不得进入正式聚合；参考成片只能提供正向保留模式，不能推断作者真实删片偏好。

正式聚合已经接入 `direct-timeline --technique-profile`。当前只有 `humor-preserve-real-awkward-process` 具备白名单执行器：它需要目标镜头、事件或 optional moment 的显式 `fun_score >= 0.55`，并且只有当该证据让边缘镜头跨过选片阈值且最终通过预算拟合时才写入 `applied_patterns`。它不能重排本来已入选的镜头，用户反馈优先级为 `remove/avoid > lock > protect/dependency > cut_first/score`。`narrative-failure-adaptation-payoff` 在真实目标语义标注入口完成前降级为 guidance；正式档案共 1 条 executable pattern、85 条 guidance patterns，其中 60 条为单来源 guidance。没有目标证据时不得改变 EDL。

## 完成状态

1. 九支参考视频均已完成正式 technique study，并通过各自的完整分析、ASR、人工复核、上下文字符门禁和新增来源的完整请求 UTF-8 字节门禁。
2. 九来源聚合已复核独立来源支持数；后续新增参考视频时继续显式设置 `minimum_source_support=2`，并重新执行 Schema、测试、聚合与媒体边界门禁。
3. 九来源正式 Aggregate 已版本化保存，并以 `eligible_patterns`、`applied_patterns`、`guidance_patterns` 三类可追踪结果接入导演候选报告；仅加载档案不算已应用。
4. 当前九来源 Aggregate 门禁：45 项参考学习专项 unittest、307 项 director 全量 unittest、九 Study 与 Aggregate Schema/运行时校验、CLI 聚合 smoke、UTF-8 无 BOM、敏感信息/changed-media 扫描及 `git diff --check` 均通过。
5. CI 在干净 Python 环境显式安装 `test` extra；自动化 Schema 测试覆盖所有正式 reference JSON、moments fixture 与 protection policy，当前本地全量基线为 307 项 unittest。
6. 模型请求门禁已改为校验完整 Responses JSON body 的 UTF-8 字节数：程序内 transport 只消费已经校验的紧凑 body bytes，CLI 则校验待发送文件的原始字节并返回 SHA-256；中文多字节边界、完整 envelope、Responses 最小结构、重复字段与递归凭据字段拒绝、transport 零调用、不可压缩 packet、UTF-8 BOM 和本地 HTTP 413 网关均有回归覆盖。该门禁不替代不同 tool type 的上游 API Schema 校验；仅检查 context 字符数也不能作为已通过外层请求门禁的依据，历史字符记录不追溯标记为字节验证。
7. CI 的 `test` extra 固定便携 FFmpeg 版本，并以 `lavfi` 临时生成 FFV1/PCM 音视频，实际通过基础增强 renderer 的 `loudnorm`、H.264/AAC 编码，再完整解码验证视频流和音频流；测试不依赖真实素材、系统预装 FFmpeg 或已提交媒体，CI job 设有 10 分钟硬超时。

## Git 与媒体边界

- Git 仅提交进度、代码、Schema、测试和脱敏后的正式学习产物。
- 代理视频、音视频流、抽帧、ASR 中间文件、弹幕与其他临时素材只保存在仓库外的 Git 忽略目录，不上传 Git。
