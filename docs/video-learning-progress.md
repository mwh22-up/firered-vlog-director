# 参考视频 Technique Learning 计划进度

更新时间：2026-08-15
执行分支：`feature/director-learning-loop`

## 总体进度

- 计划视频：26 支
- 已完成正式学习：26 支
- 已开始但未完成：0 支
- 未开始正式学习：0 支
- 完成率：26/26（100%）

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

### 10. BV1Mi536EELv — 已完成

- 标题：[欧洲最混乱的老城和顶级富豪岛，差距能有多大？](https://www.bilibili.com/video/BV1Mi536EELv/)
- 时长：1,911.211 秒（约 31 分 51 秒）。
- 已完成：匿名低清代理下载、HEVC 视频流与 AAC 音频流分别完整解码、small / zh 全片 ASR、完整镜头/事件/音频与语义分析、无 VAD 尾部复核、人工重点区间原图复核、受限 context、完整 Responses body 门禁和正式 technique study。
- 正式产物：`reference-learning/technique-study.BV1Mi536EELv.v1.json`
- 证据规模：649 个镜头、24 个事件、422 个音频段、1,000 个转写片段、6,044 个词、19 条 technique observations；人工复核包含 24 张事件联系表、6 张全片概览、蓝洞与尾部密集表，以及 21 张选定事件原图表。
- ASR 覆盖：ASR 报告处理到 1,911.211 秒；最后可信对白到 1,910.6 秒“咱都用不了”，与媒体末尾相差 0.611 秒，可信对白覆盖率 99.9680%。关闭 VAD 的 45 秒尾检重现结尾完整旁白和最后短句，其后没有新增可信对白。
- 人工复核：检查开场双城对照和颜色任务、300 元酒店与投币电梯、廉价和豪华酒店、那不勒斯街巷与足球身份、卡布里转折、蓝洞连续关闭、餐饮对照、Day 3 重试、换船与入洞、蓝光高潮、船夫记忆、产品/字幕/章节/价格图层和片尾花絮；未执行 OCR，不声明字幕逐字完全正确。
- 模型上下文：86,698 字符、100,528 UTF-8 字节，严格 `<180,000` 字符；包含 model、instructions、input、tools、text JSON Schema 和人工证据的最终 Responses body 为 103,199 字符、117,083 UTF-8 字节，严格 `<200,000`，body SHA-256 为 `e8024b51df858bdea4c5c7223a146ba5c9de9b083bd9954afe22304da6252be0`。
- 证据限制：参考成片只支持正向保留模式；没有原始素材映射，不能推断作者真实删片偏好。未确认 speed ramp、具体倍率、复杂转场机制、独立音效、曲名、BPM、ducking 数值或逐拍因果；价格、蓝洞规则、城市安全、历史人物、群体特征和产品颜色需独立核验。
- 门禁结果：正式 Study 运行时与 Schema、JSON/UTF-8 无 BOM、中文、时间边界、本地绝对路径与敏感信息扫描通过；十来源聚合为 32 条稳定模式和 55 条单来源模式，显式 `minimum_source_support=2`。

### 11. BV11Ao7BYEyv — 已完成

- 标题：[泰拳女王给我当陪练，是种怎样的体验!?](https://www.bilibili.com/video/BV11Ao7BYEyv/)
- 时长：2,213.227 秒（约 36 分 53 秒）。
- 已完成：匿名低清代理下载、视频与音频双流完整解码、small / zh 全片 ASR、完整镜头/事件/音频与语义分析、关闭 VAD 尾部复核、人工重点区间抽帧复核、受限 context、完整 Responses body 门禁和正式 technique study。
- 正式产物：`reference-learning/technique-study.BV11Ao7BYEyv.v1.json`
- 证据规模：787 个镜头、31 个事件、571 个音频段、1,017 个转写片段、5,124 个词、21 条 technique observations；人工复核包含 24 张事件联系表和 8 张全片概览、分段密集与尾部联系表。
- ASR 覆盖：正式 VAD 转写到 2,183.97 秒，为媒体时长的 98.6781%；关闭 VAD 的 2,100–2,213.227 秒独立尾检在拳馆 Easter Egg 中检测到短对话式语音直到 2,212.86 秒，覆盖率 99.9834%，距片尾约 0.367 秒。尾检文字置信度偏低，只用于覆盖核验，不并入正式逐字稿。
- 人工复核：检查三任务式开场、泰拳女王与基础训练、主持人笨拙反应、对打受伤与职业风险反思、CQB 和四对四演练、战术 inset 与游戏结果卡、百年民宿与清晨布施、私人收藏与旧物市场、改装船和高速体验、按摩结算与拳馆 Easter Egg；未执行 OCR，不声明字幕逐字完全正确。
- 模型上下文：87,693 字符、99,297 UTF-8 字节，严格 `<180,000` 字符；包含 model、instructions、input、tools、text JSON Schema 和人工证据的最终 Responses body 为 81,152 字符、93,598 UTF-8 字节，严格 `<200,000`，body SHA-256 为 `74a48254c4d3f7cf664a8ce7586a5722ab80986db83d359ccf5753dc09370ecc`。
- 证据限制：参考成片只支持正向保留模式；没有原始素材映射，不能推断作者真实删片偏好。未确认 speed ramp、具体倍率、复杂转场机制、独立音效、曲名、BPM、ducking 数值或逐拍因果；游戏联动、训练安全、泰拳数字、港口历史、船速、发动机和物件年代需独立核验。

### 12. BV1LS3r6gE7k — 已完成

- 标题：[花了100w装工作室，是梦中情司还是拉完了？](https://www.bilibili.com/video/BV1LS3r6gE7k/)
- 时长：1,190.53 秒（约 19 分 51 秒）。
- 已完成：匿名低清代理下载、HEVC 视频流与 AAC 音频流完整解码、small / zh 全片 ASR、完整镜头/事件/音频与语义分析、尾部画面核验、人工重点区间复核、受限 context、完整 Responses body 门禁和正式 technique study。
- 正式产物：`reference-learning/technique-study.BV1LS3r6gE7k.v1.json`
- 证据规模：408 个镜头、14 个事件、198 个音频段、701 个转写片段、4,132 个词、20 条 technique observations；人工复核包含 14 张事件联系表、6 张全片概览、1 张开场密集表和 1 张尾部密集表。
- ASR 覆盖：ASR 报告处理到 1,190.528 秒；最后可信对白到 1,185.32 秒“拜拜”，可信对白覆盖率 99.5624%，与媒体末尾相差约 5.21 秒。尾部密集抽帧显示回顾照片、结束标题和收束画面，未发现新增对白。
- 人工复核：检查成本问题与改造前后开场、三层空间动线、员工工作流、赞助键盘、露台与隐藏空间、夫妻和同事笑点、个人剪辑室树影记忆、拍摄棚、招牌错误补救、旧牌与照片墙、2021 至 2025 回顾和片尾；未执行 OCR，不声明字幕逐字完全正确。
- 模型上下文：67,405 字符、77,521 UTF-8 字节，严格 `<180,000` 字符；包含 model、instructions、input、tools、text JSON Schema 和人工证据的最终 Responses body 为 60,023 字符、71,379 UTF-8 字节，严格 `<200,000`，body SHA-256 为 `1d7a753cc070e3d2c396a1289c645074b1331eff81aa4b174278d0c4a7371758`。
- 证据限制：参考成片只支持正向保留模式；没有原始素材映射，不能推断作者真实删片偏好。未确认 speed ramp、具体倍率、复杂转场、独立音效、曲名、BPM、ducking 或逐拍因果；装修金额、设备功能、品牌结论、档案来源和聊天截图授权需独立核验。
- 聚合结果：十二来源聚合为 42 条稳定模式和 57 条单来源模式，显式 `minimum_source_support=2`；新增来源使 6 条旧单来源技巧升级为稳定模式，并新增 7 条来源特定技巧。

### 13. BV1xTdwBQEna — 已完成

- 标题：[老婆说，我们云南人就是无敌的！](https://www.bilibili.com/video/BV1xTdwBQEna/)
- 时长：1,852.224 秒（约 30 分 52 秒）。
- 已完成：匿名代理下载、HEVC 视频流与 AAC 音频流完整解码、small / zh 全片 ASR、完整镜头/事件/音频与语义分析、尾部画面核验、人工重点区间复核、受限 context、完整 Responses body 门禁和正式 technique study。
- 正式产物：`reference-learning/technique-study.BV1xTdwBQEna.v1.json`
- 证据规模：674 个镜头、22 个事件、318 个音频段、1,259 个转写片段、6,399 个词、22 条 technique observations；人工复核包含 22 张自动事件联系表和 10 张重点联系表。
- ASR 覆盖：ASR 报告处理到 1,852.224 秒；最后可信旁白到 1,848.56 秒“日子往前”，可信对白覆盖率 99.8024%，与媒体末尾相差约 3.66 秒。尾部抽帧显示行车、花草和节目结束标题，未发现新增对白。
- 人工复核：检查昆明命题与伴侣个人入口、菌子专家和食品风险、斗南鲜花拍卖/质检/物流、普通花市、西南联大历史材料、独立书店和儿童诗、返乡创作者、夫妻及当地人物笑点、城市生命力片尾；未执行 OCR，不声明字幕逐字完全正确。
- 模型上下文：79,328 字符、94,296 UTF-8 字节，严格 `<180,000` 字符；包含 model、instructions、input、tools、text JSON Schema 和人工证据的最终 Responses body 为 69,888 字符、86,192 UTF-8 字节，严格 `<200,000`，body SHA-256 为 `4e2ecc9d0117719ac6494af0beac8ad7bcecb8e21cbf123b5f559b24062e961c`。
- 证据限制：参考成片只支持正向保留模式；没有原始素材映射，不能推断作者真实删片偏好。未确认 speed ramp、具体倍率、复杂转场机制、独立音效、曲名、BPM、ducking 数值或逐拍因果；食用安全、市场规模、历史材料、人物身份和经营数据需独立核验。
- 聚合结果：十三来源聚合为 44 条稳定模式和 62 条单来源模式，显式 `minimum_source_support=2`；新增来源使 2 条旧单来源技巧升级为稳定模式，并新增 7 条来源特定技巧。

### 14. BV146BFBzEfE — 已完成

- 标题：[当热度褪去，山西还值得去吗？](https://www.bilibili.com/video/BV146BFBzEfE/)
- 时长：1,907.472 秒（约 31 分 47 秒）。
- 已完成：匿名代理下载、HEVC 视频流与 AAC 音频流完整解码、small / zh 全片 ASR、关闭 VAD 尾部复核、完整镜头/事件/音频与语义分析、尾部画面核验、人工重点区间复核、受限 context、完整 Responses body 门禁和正式 technique study。
- 正式产物：`reference-learning/technique-study.BV146BFBzEfE.v1.json`
- 证据规模：684 个镜头、22 个事件、302 个音频段、1,282 个转写片段、7,184 个词、22 条 technique observations；人工复核包含 22 张事件联系表和 9 张重点联系表。
- ASR 覆盖：ASR 报告处理到 1,907.456 秒；主 ASR 最后可信旁白到 1,905.42 秒“就是未来”，关闭 VAD 的尾部复核到 1,905.46 秒，可信对白覆盖率 99.8946%，与媒体末尾相差约 2.01 秒。尾部抽帧显示矿井对话、城市/车/古建/云冈石窟、字幕与 credits 收束，未发现新增对白。
- 人工复核：检查开场大同命题与后文承诺、面食趣味与价格图层、悬空寺/云冈石窟景观和导览、应县木塔历史损伤情绪峰值、煤矿地下转折、矿工劳动记忆、城市文化转型、字幕/资料/品牌/credits 图层和片尾收束；未执行 OCR，不声明字幕逐字完全正确。
- 模型上下文：87,170 字符、103,874 UTF-8 字节，严格 `<180,000` 字符；包含 model、instructions、input、tools、text JSON Schema 和人工证据的最终 Responses body 为 83,058 字符、99,820 UTF-8 字节，严格 `<200,000`，body SHA-256 为 `c556c7764eb8283f817c0f585fab79d7c8c04259087043db9aaf31da1c1918c2`。
- 证据限制：参考成片只支持正向保留模式；没有原始素材映射，不能推断作者真实删片偏好。未确认 speed ramp、具体倍率、复杂转场机制、独立音效、曲名、BPM、ducking 数值或逐拍因果；面食价格、景区票价、历史年份、文保数字、煤矿数据、能源比例、城市治理、文创销售和汽车产品信息需独立核验。
- 聚合结果：十四来源聚合为 44 条稳定模式和 63 条单来源模式，显式 `minimum_source_support=2`；新增来源支持 21 条既有稳定模式，并新增 1 条来源特定技巧 `narrative-industrial-memory-to-city-renewal`。

### 15. BV1MgywB8E9m — 已完成

- 标题：[我穿越回了100年前的德国！](https://www.bilibili.com/video/BV1MgywB8E9m/)
- 时长：1,436.821 秒（约 23 分 57 秒）。
- 已完成：匿名代理下载、HEVC 视频流与 AAC 音频流完整解码、`small / zh` 全片 ASR、完整镜头/事件/音频与语义分析、尾部画面核验、人工重点区间复核、受限 context、完整 Responses body 门禁和正式 technique study。
- 正式产物：`reference-learning/technique-study.BV1MgywB8E9m.v1.json`
- 证据规模：488 个镜头、14 个事件、333 个音频段、844 个转写片段、4,705 个词、14 条 technique observations；人工复核包含 14 张事件联系表中的重点抽查，覆盖开场 Leica/Wetzlar 命题、博物馆/档案/历史画面、相机操作与黑白画面、歌德小镇转折、雨中宽银幕测试、Heidelberg 关门与当地人帮助、铜猴/桥/山路趣味事件、山顶美景、字幕图层和尾部黑底收束。
- ASR 覆盖：ASR 报告处理到 1,436.821 秒；最后可信对白到 1,436.35 秒“讨厌，姐夫”，可信对白覆盖率 99.9672%，与媒体末尾相差约 0.47 秒。尾部抽帧显示山顶合影、绿底引用/图卡、雨中街景器材字幕和黑底尾字，未发现新增对白空间。
- 人工复核：检查开场相机历史悬念与地点任务、叙事转折、产品实测、文学/历史资料层、Heidelberg 旅行阻碍、当地人帮助、夫妻关系笑点、山顶情绪峰值、字幕/品牌/尾字层和疑似节奏段；未执行 OCR，不声明字幕、图卡、引用或 credits 逐字准确。
- 模型上下文：86,219 字符、97,291 UTF-8 字节，严格 `<180,000` 字符；包含 model、instructions、input、tools、text JSON Schema 和人工证据的最终 Responses body 为 72,053 字符、83,151 UTF-8 字节，严格 `<200,000`，body SHA-256 为 `bf21b3113755bca869ee52631dc6d21cf733bb2222e2686c24369aaf9b51560e`。
- 证据限制：参考成片只支持正向保留模式；没有原始素材映射，不能推断作者真实删片偏好。未确认 speed ramp、具体播放倍率、复杂转场、独立音效、曲名、BPM、ducking 或逐拍因果；Leica 历史、产品功能、文学引用、地点开放时间、地标传说、人物授权和品牌关系需独立核验。
- 聚合结果：十五来源聚合为 44 条稳定模式和 64 条单来源模式，显式 `minimum_source_support=2`；新增来源支持 11 条既有稳定模式，并新增 1 条来源特定技巧 `narrative-archive-context-before-present-use`。

### 16. BV1JfxYzGE8t — 已完成

- 标题：[用一场动漫巡礼，告别假期！](https://www.bilibili.com/video/BV1JfxYzGE8t/)
- 时长：1,428.096 秒（约 23 分 48 秒）。
- 已完成：匿名代理下载、HEVC 视频流与 AAC 音频流完整解码、`small / zh` 全片 ASR、关闭 VAD 尾部复核、完整镜头/事件/音频与语义分析、尾部画面核验、人工重点区间复核、受限 context、完整 Responses body 门禁和正式 technique study。
- 正式产物：`reference-learning/technique-study.BV1JfxYzGE8t.v1.json`
- 证据规模：635 个镜头、16 个事件、315 个音频段、798 个转写片段、4,589 个词、15 条 technique observations；人工复核包含 16 张事件联系表中的重点抽查，覆盖开场铃芽装扮和九州标题、动漫巡礼路线与由布院语境、Gundam 现实地标和动画/资料层、太宰府天满宫求学笑点、屋台夜景饮食、萤火之森神社、One Piece 惊喜雕像、退潮海路、夕阳情绪峰值、尾部手写字和 credits。
- ASR 覆盖：ASR 主报告到 1,391.88 秒；关闭 VAD 尾检复现可信对白到 1,391.90 秒“我们每个人走的这段路的远方，都是不一样长的”，可信对白覆盖率 97.4654%，与媒体末尾相差约 36.20 秒。关闭 VAD 尾检在 1,414.02–1,426.58 秒只产生 high no_speech 的低可信重复句，按配乐/尾字/ASR 不确定性处理，不并入可信对白；尾部抽帧显示手写字、人物迎风、夕阳海景和 credits 收束。
- 人工复核：检查开场、叙事转折、趣味事件、Gundam/One Piece/作品资料层、美景、字幕层、历史/资料画面、疑似音乐节奏和尾部收束；未执行 OCR，不声明字幕、图卡、地图、作品名、手写字或 credits 逐字准确。
- 模型上下文：78,727 字符、89,667 UTF-8 字节，严格 `<180,000` 字符；包含 model、instructions、input、tools、text JSON Schema 和人工证据的最终 Responses body 为 66,458 字符、77,428 UTF-8 字节，严格 `<200,000`，body SHA-256 为 `ec7a097f4a5e7004c8ee30eff9596a2b73e3010be1886554234658c0eb908ca1`。
- 证据限制：参考成片只支持正向保留模式；没有原始素材映射，不能推断作者真实删片偏好。未确认 speed ramp、具体播放倍率、复杂转场、独立音效、曲名、BPM、ducking 或逐拍因果；作品片段、海报、角色、logo、地图、取景关系、地点开放、潮汐、产品能力和授权关系需独立核验。
- 聚合结果：十六来源聚合为 44 条稳定模式和 65 条单来源模式，显式 `minimum_source_support=2`；新增来源支持 14 条既有稳定模式，并新增 1 条来源特定技巧 `graphic-archive-footage-context-before-present-action`。

## 新增待学习来源（2026-08-14）

下列来源由用户新增；只有在完成完整分析、ASR、人工复核、模型上下文与正式 Study 门禁后，才能改为“已完成”并计入 Aggregate。

### 17. BV1AYwQzzEbV — 已完成

- 标题：《美国超市就能买到枪？比买菜更简单！》
- 地址：[BV1AYwQzzEbV](https://www.bilibili.com/video/BV1AYwQzzEbV/)
- 时长：2,177.344 秒（约 36 分 17 秒）。
- 已完成：匿名代理下载、HEVC/AAC 双流完整解码、`small/zh` 全片 ASR、完整镜头/事件/音频分析、24 张事件联系表与开场/历史转折/球场/野牛/结尾人工复核、受限 context、完整 Responses body 门禁和正式 technique study。
- 正式产物：`reference-learning/technique-study.BV1AYwQzzEbV.v1.json`
- 证据规模：721 个镜头、26 个事件、450 个音频段、1,129 个转写片段、6,569 个词、9 条 technique observations。
- ASR 覆盖：最后可信对白到 2,175.67 秒“我们下期再见”，距媒体末尾约 1.67 秒，可信对白覆盖率 99.9232%。
- 人工复核：确认开场地点问题、枪店与同伴反应、历史资料层、球场与牛仔文化、野牛向导/环境、底部字幕与结尾；未确认 speed ramp、精确倍率、复杂转场或独立音效。
- 模型上下文：90,318 字符、105,024 UTF-8 字节，严格 `<180,000`；最终 Responses body 为 89,512 UTF-8 字节，严格 `<200,000`，body SHA-256 为 `308ebd3f9a4c413bb865e6ce8769d3c41a9b0f4770acc4b579a7c920a3227ef3`。
- 证据限制：参考成片只支持正向保留模式；枪支、历史、政治、野牛与保护数据需独立核验，不能由本 Study 当作事实结论。

### 18. BV1cuFezLEE2 — 已完成

- 标题：《也没人跟我说延吉能这么玩啊！》
- 地址：[BV1cuFezLEE2](https://www.bilibili.com/video/BV1cuFezLEE2/)
- 时长：2,377.280 秒（约 39 分 37 秒）。
- 已完成：匿名代理下载、HEVC/AAC 双流完整解码、`small/zh` 全片 ASR、完整镜头/事件/音频分析、24 张事件联系表与开场/市场/电影村/家庭饭桌/冰河路线人工复核、受限 context、完整 Responses body 门禁和正式 technique study。
- 正式产物：`reference-learning/technique-study.BV1cuFezLEE2.v1.json`
- 证据规模：664 个镜头、27 个事件、595 个音频段、1,242 个转写片段、6,649 个词、9 条 technique observations。
- ASR 覆盖：最后可信对白到 2,373.78 秒“一键三连”，距媒体末尾约 3.50 秒，可信对白覆盖率 99.8528%。
- 人工复核：确认传统文化与雪景开场、市场制作/试吃/人物反应、电影布景与迁徙记忆、本地家庭饭桌、长白山计划受阻后的冰河路线、摔倒与冰瀑到达；未确认 speed ramp、精确倍率、复杂转场或独立音效。
- 模型上下文：88,303 字符、103,755 UTF-8 字节，严格 `<180,000`；最终 Responses body 为 88,813 UTF-8 字节，严格 `<200,000`，body SHA-256 为 `272046548fa1a6e620cdaca2bc6194b2fb930714b87ef2909afacd277db4783e`。
- 证据限制：参考成片只支持正向保留模式；族群、迁徙、电影、食物、植物、景区和户外安全信息需独立核验。

### 19. BV1PbebzdEWm — 已完成

- 标题：《穿越300年逛北京！北京影像巡礼》
- 地址：[BV1PbebzdEWm](https://www.bilibili.com/video/BV1PbebzdEWm/)
- 时长：1,739.882 秒（约 29 分钟）。
- 已完成：匿名代理下载、双流完整解码、`small/zh` 全片 ASR、完整镜头/事件/音频分析、18 张事件联系表人工复核、受限 context、完整 Responses body 门禁和正式 technique study。
- 正式产物：`reference-learning/technique-study.BV1PbebzdEWm.v1.json`
- 证据规模：504 个镜头、18 个事件、355 个音频段、933 个转写片段、4,649 个词、10 条 technique observations。
- ASR 覆盖：最后可信结束语到 1,737.14 秒“再见吧”，距媒体末尾约 2.74 秒，可信对白覆盖率 99.8424%。
- 人工复核：确认清装扮演与景山命题开场、电影/歌曲年代线、北海实景与作品参考画面对照、主持对谈、资料卡、北京家乡价值收束和系列约定；未确认 speed ramp、精确倍率、复杂转场、独立音效或逐拍剪切。
- 模型上下文：87,173 字符、98,277 UTF-8 字节，严格 `<180,000`；最终 Responses body 为 110,848 UTF-8 字节，严格 `<200,000`，body SHA-256 为 `d27ca94676bae7b9c3dd0738726c7150d00aaa1d88f0723d329e4cb286ab770a`。
- 证据限制：参考成片只支持正向保留模式；影视、音乐、海报、访谈、历史和城市观点需独立核验。

### 20. BV13p421y7iv — 已完成

- 标题：《妈妈：我一辈子都很辛苦，但从没委屈过…》
- 地址：[BV13p421y7iv](https://www.bilibili.com/video/BV13p421y7iv/)
- 时长：669.440 秒（约 11 分 9 秒）。
- 已完成：匿名代理下载、双流完整解码、`small/zh` 全片 ASR、完整镜头/事件/音频分析、8 张事件联系表人工复核、受限 context、完整 Responses body 门禁和正式 technique study。
- 正式产物：`reference-learning/technique-study.BV13p421y7iv.v1.json`
- 证据规模：263 个镜头、8 个事件、149 个音频段、397 个转写片段、2,400 个词、9 条 technique observations。
- ASR 覆盖：最后可信旁白到 664.79 秒，距媒体末尾约 4.65 秒，可信对白覆盖率 99.3055%。
- 人工复核：确认旧照片私人问题开场，以花串联童年、恋爱、育儿和疾病背景，重访公园/胡同失败后改去昆明创造新记忆，以新旧照片礼物和母亲原声收束；未确认 speed ramp、精确倍率、复杂转场、独立音效或逐拍剪切。
- 模型上下文：59,408 字符、65,074 UTF-8 字节，严格 `<180,000`；最终 Responses body 为 74,656 UTF-8 字节，严格 `<200,000`，body SHA-256 为 `e8e5a9eeaaed35fee5e2817379de8da7022a3ae7dcc83a6e5b02b0d797d2c668`。
- 证据限制：参考成片只支持正向保留模式；疾病、记忆机制、家庭历史、照片授权和产品性能需独立核验。

### 21. BV1UtsEzVEwF — 已完成

- 标题：《这还是美国吗？给我干哪来了｜新奥尔良》
- 地址：[BV1UtsEzVEwF](https://www.bilibili.com/video/BV1UtsEzVEwF/)
- 时长：1,155.392 秒（约 19 分 15 秒）。
- 已完成：匿名代理下载、双流完整解码、`small/zh` 全片 ASR、完整镜头/事件/音频分析、16 张事件联系表人工复核、受限 context、完整 Responses body 门禁和正式 technique study。
- 正式产物：`reference-learning/technique-study.BV1UtsEzVEwF.v1.json`
- 证据规模：387 个镜头、16 个事件、218 个音频段、535 个转写片段、3,442 个词、9 条 technique observations。
- ASR 覆盖：最后可信对白到 1,155.10 秒，距媒体末尾约 0.29 秒，可信对白覆盖率 99.9748%。
- 人工复核：确认五感结构、殖民/港口背景、法语区、本地美食、沼泽鳄鱼、日落邮轮与爵士街现场，以及文化碰撞的价值收束；未确认 speed ramp、精确倍率、复杂转场、独立音效或逐拍剪切。
- 模型上下文：69,336 字符、77,396 UTF-8 字节，严格 `<180,000`；最终 Responses body 为 87,995 UTF-8 字节，严格 `<200,000`，body SHA-256 为 `a658c21f9bfeb728a24f1f4eab6a7aed87842d5a987b1936d84e0793366bc05d`。
- 证据限制：参考成片只支持正向保留模式；历史、族群、食物、动物、现场演出和产品信息需独立核验。

### 22. BV1uC411E7jU — 已完成

- 标题：《花费15万的，北欧滤镜破碎之旅!》
- 地址：[BV1uC411E7jU](https://www.bilibili.com/video/BV1uC411E7jU/)
- 时长：1,176.789 秒（约 19 分 37 秒）。
- 已完成：匿名代理下载、双流完整解码、`small/zh` 全片 ASR、完整镜头/事件/音频分析、15 张事件联系表人工复核、受限 context、完整 Responses body 门禁和正式 technique study。
- 正式产物：`reference-learning/technique-study.BV1uC411E7jU.v1.json`
- 证据规模：369 个镜头、15 个事件、315 个音频段、660 个转写片段、3,611 个词、7 条 technique observations。
- ASR 覆盖：最后可信花絮对白到 1,176.72 秒，距媒体末尾约 0.07 秒，可信对白覆盖率 99.9942%。
- 人工复核：确认高价/脏雪开场、五次现实落差、动物和严寒行动、无雪与暴雪等待、短暂晴雪 payoff，以及从摄影大片转向夫妻日常记忆的收束；未确认 speed ramp、精确倍率、复杂转场、独立音效或逐拍剪切。
- 模型上下文：76,655 字符、85,341 UTF-8 字节，严格 `<180,000`；最终 Responses body 为 96,819 UTF-8 字节，严格 `<200,000`，body SHA-256 为 `2b7a098519070f3495edf42732008b0b3551c28cf94bdf04651d260f0ab9ff12`。
- 证据限制：参考成片只支持正向保留模式；费用、天气、项目、动物、摄影与安全信息需独立核验。

### 23. BV1zYSvBHE3U — 已完成

- 标题：《用一只帆船也可以环游世界？》
- 地址：[BV1zYSvBHE3U](https://www.bilibili.com/video/BV1zYSvBHE3U/)
- 时长：2,045.802 秒（约 34 分 6 秒）。
- 已完成：匿名代理下载、双流完整解码、`small/zh` 全片 ASR、完整镜头/事件/音频分析、23 张事件联系表人工复核、受限 context、完整 Responses body 门禁和正式 technique study。
- 正式产物：`reference-learning/technique-study.BV1zYSvBHE3U.v1.json`
- 证据规模：593 个镜头、23 个事件、446 个音频段、1,253 个转写片段、6,353 个词、8 条 technique observations。
- ASR 覆盖：最后可信结束语到 2,045.11 秒，距媒体末尾约 0.69 秒，可信对白覆盖率 99.9662%。
- 人工复核：确认中国船队与两天学习任务、安全说明、升帆/掌舵/潜水/钓鱼完整教学、船员技能与人生故事、共同做饭和晚餐，以及海与沙漠交界的登陆 payoff；未确认 speed ramp、精确倍率、复杂转场、独立音效或逐拍剪切。
- 模型上下文：87,982 字符、103,112 UTF-8 字节，严格 `<180,000`；最终 Responses body 为 115,521 UTF-8 字节，严格 `<200,000`，body SHA-256 为 `a81c8961157a273b2c7f3e77704124f69fbda03490f429bc51be4d69a8adc318`。
- 证据限制：参考成片只支持正向保留模式；航海、赛事、签证、潜水、设备、海钓和安全信息需独立核验。

### 24. BV1Gc411z7mu — 已完成

- 标题：《我 求 婚 啦 ！！》
- 地址：[BV1Gc411z7mu](https://www.bilibili.com/video/BV1Gc411z7mu/)
- 时长：1,301.162 秒（约 21 分 41 秒）。
- 已完成：匿名代理下载、双流完整解码、`small/zh` 全片 ASR、完整镜头/事件/音频分析、19 张事件联系表人工复核、受限 context、完整 Responses body 门禁和正式 technique study。
- 正式产物：`reference-learning/technique-study.BV1Gc411z7mu.v1.json`
- 证据规模：405 个镜头、19 个事件、444 个音频段、501 个转写片段、2,316 个词、7 条 technique observations。
- ASR 覆盖：最后可信花絮对白到 1,301.12 秒，距媒体末尾约 0.04 秒，可信对白覆盖率 99.9968%。
- 人工复核：确认结果冷开场、数月原创歌创作与彩排、伴侣参观/现场准备双线倒计时、朋友合唱 MV、现场真唱告白、明确回答、戴戒指及事后复盘；未确认 speed ramp、精确倍率、复杂转场、独立音效、精确 BPM 或逐拍剪切。
- 模型上下文：70,013 字符、75,767 UTF-8 字节，严格 `<180,000`；最终 Responses body 为 86,599 UTF-8 字节，严格 `<200,000`，body SHA-256 为 `2f2017bb224d4139e557ed612ed599f288c65ec04a2a4400b99ae10d1f8995c2`。
- 证据限制：参考成片只支持正向保留模式；私人影像、音乐、人员、场地和关系表达需独立确认授权与语境。

### 25. BV1Sv421k7pS — 已完成

- 标题：《和女朋友一起向已婚UP主学习如何谈恋爱！》
- 地址：[BV1Sv421k7pS](https://www.bilibili.com/video/BV1Sv421k7pS/)
- 时长：1,370.666 秒（约 22 分 51 秒）。
- 已完成：匿名代理下载、双流完整解码、`small/zh` 全片 ASR、完整镜头/事件/音频分析、13 张事件联系表人工复核、受限 context、完整 Responses body 门禁和正式 technique study。
- 正式产物：`reference-learning/technique-study.BV1Sv421k7pS.v1.json`
- 证据规模：116 个镜头、13 个事件、252 个音频段、987 个转写片段、4,424 个词、8 条 technique observations。
- ASR 覆盖：最后可信结束语到 1,363.01 秒“拜拜”，距媒体末尾约 7.656 秒，可信对白覆盖率 99.4414%。
- 人工复核：确认固定四人宽景与自然反应、由轻到重的问题梯度、两对情侣经验对照、中段默契游戏、旅行和共同生活案例、共同成长与个人经验边界收束，以及底部对白字幕和稀疏问题/答案标签；未确认 speed ramp、精确倍率、复杂转场、独立音效、曲名、BPM、ducking 或逐拍剪切。
- 模型上下文：51,872 字符、62,814 UTF-8 字节，严格 `<180,000`；最终 Responses body 为 70,957 UTF-8 字节，严格 `<200,000`，body SHA-256 为 `7586d432f164bef2789ec11a484b738f812ed931e4abc412920e7f6de2e5524b`。
- 证据限制：参考成片只支持正向保留模式；关系、婚姻、旅行、财务、家务和共同成长内容均为片中人物个人经验，不能泛化为普遍或专业建议。

### 26. BV1Gt1FBPEum — 已完成

- 标题：《那些劝你来新疆的人，根本没告诉你……》
- 地址：[BV1Gt1FBPEum](https://www.bilibili.com/video/BV1Gt1FBPEum/)
- 时长：1,471.616 秒（约 24 分 32 秒）。
- 已完成：匿名代理下载、HEVC/AAC 双流完整解码、`small/zh` 全片 ASR、完整镜头/事件/音频分析、16 张事件联系表人工复核、受限 context、完整 Responses body 门禁和正式 technique study。
- 正式产物：`reference-learning/technique-study.BV1Gt1FBPEum.v1.json`
- 证据规模：530 个镜头、16 个事件、337 个音频段、793 个转写片段、4,565 个词、9 条 technique observations。
- ASR 覆盖：最后可信结束语到 1,465.46 秒“我们下期再见”，距媒体末尾约 6.156 秒，可信对白覆盖率 99.5816%；尾部人工联系表显示旅行总结、片尾标题与 credits，未发现新增对白空间。
- 人工复核：确认帕米尔地理和粉色光任务开场、牛羊大巴扎的交易过程、喀什古城人物互动、喀拉昆仑公路与白沙湖、天气风险和摄影等待、粉色雪山/车身同框兑现、旧素材回看与“先出发”收束，以及底部字幕、价格、调色板和年份图层；未确认 speed ramp、精确倍率、复杂转场、独立音效、曲名、BPM、ducking 或逐拍剪切。
- 模型上下文：80,386 字符、91,082 UTF-8 字节，严格 `<180,000`；最终 Responses body 为 102,869 UTF-8 字节，严格 `<200,000`，body SHA-256 为 `5b7ebfb386a52f7dce1e6ba5817c69c0262c5b9fcdc72be8b8e05ac529bdff33`。
- 证据限制：参考成片只支持正向保留模式；新疆地理、民族文化、市场交易、天气、光学、品牌产品和道路安全信息需独立核验，现场人物和旧素材需确认授权。

## 已沉淀的跨视频结果

当前二十六支已完成视频可聚合出：

- 完整来源数：26
- 稳定模式：58 条（显式 `minimum_source_support=2`）
- 单来源模式：87 条
- 正式聚合产物：`reference-learning/reference-techniques.aggregate.v1.json`
- 聚合命令：`vlog-director aggregate-techniques`
- 当前限制：`BV19sm2BBEDd` 的重叠首日不生成新增 observation。单来源模式不能计为稳定跨来源模式，开场预分析或未完成视频也不得进入正式聚合；参考成片只能提供正向保留模式，不能推断作者真实删片偏好。

正式聚合已经接入 `direct-timeline --technique-profile`。当前策略编译出 3 条 eligible patterns：`humor-preserve-real-awkward-process` 具备白名单 EDL 执行器，`opening-phased-hook-not-uniform-fast-cut` 只生成自动候选，`playback-rate-fast-forward-travel-compression-visual-estimate` 只允许带人工选倍率的 preview candidate。趣味执行器需要目标镜头、事件或 optional moment 的显式 `fun_score >= 0.55`，并且只有当该证据让边缘镜头跨过选片阈值且最终通过预算拟合时才写入 `applied_patterns`；它不能重排本来已入选的镜头。用户反馈优先级为 `remove/avoid > lock > protect/dependency > cut_first/score`。`narrative-failure-adaptation-payoff` 在真实目标语义标注入口完成前降级为 guidance；正式档案另有 142 条 guidance patterns，其中 87 条为单来源 guidance。没有目标证据、白名单执行器和门禁时不得改变 EDL。

## 完成状态

1. 二十六支参考视频已完成正式 technique study，并通过各自的完整分析、ASR、人工复核、上下文字符门禁和完整请求 UTF-8 字节门禁。
2. 二十六来源聚合已复核独立来源支持数；后续新增或重生成参考视频时继续显式设置 `minimum_source_support=2`，并重新执行 Schema、测试、聚合与媒体边界门禁。
3. 二十六来源正式 Aggregate 已版本化保存，并以 `eligible_patterns`、`applied_patterns`、`guidance_patterns` 三类可追踪结果接入导演候选报告；仅加载档案不算已应用。
4. 当前二十六来源 Aggregate 门禁：24 项参考学习、Policy 与 Schema 专项 unittest、二十六 Study 与 Aggregate Schema/运行时校验、CLI 聚合 smoke、UTF-8 无 BOM、敏感信息/changed-media 扫描及 `git diff --check` 均通过。
5. CI 在干净 Python 环境显式安装 `test` extra；自动化 Schema 测试覆盖所有正式 reference JSON、moments fixture 与 protection policy，当前本地全量基线为 318 项 unittest。
6. 模型请求门禁已改为校验完整 Responses JSON body 的 UTF-8 字节数：程序内 transport 只消费已经校验的紧凑 body bytes，CLI 则校验待发送文件的原始字节并返回 SHA-256；中文多字节边界、完整 envelope、Responses 最小结构、重复字段与递归凭据字段拒绝、transport 零调用、不可压缩 packet、UTF-8 BOM 和本地 HTTP 413 网关均有回归覆盖。该门禁不替代不同 tool type 的上游 API Schema 校验；仅检查 context 字符数也不能作为已通过外层请求门禁的依据，历史字符记录不追溯标记为字节验证。
7. CI 的 `test` extra 固定便携 FFmpeg 版本，并以 `lavfi` 临时生成 FFV1/PCM 音视频，实际通过基础增强 renderer 的 `loudnorm`、H.264/AAC 编码，再完整解码验证视频流和音频流；测试不依赖真实素材、系统预装 FFmpeg 或已提交媒体，CI job 设有 10 分钟硬超时。

## Git 与媒体边界

- Git 仅提交进度、代码、Schema、测试和脱敏后的正式学习产物。
- 代理视频、音视频流、抽帧、ASR 中间文件、弹幕与其他临时素材只保存在仓库外的 Git 忽略目录，不上传 Git。
