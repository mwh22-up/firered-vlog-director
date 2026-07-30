# 参考视频 Technique Learning 计划进度

更新时间：2026-07-30
执行分支：`feature/director-learning-loop`

## 总体进度

- 计划视频：6 支
- 已完成正式学习：4 支
- 已开始但未完成：1 支
- 未开始正式学习：1 支
- 完成率：4/6（66.7%）

“已完成”要求同时具备：完整视频分析、可用 ASR/语义证据、人工重点区间复核、严格 `<200,000` 字符的模型输入门禁，以及已提交的正式 `technique-study.<BV>.v1.json`。仅下载代理视频、提取开场或生成预分析素材不算完成。

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

### 5. BV1aDHQejEAP — 已开始，正式学习未完成

- 标题：[《一个人的东京探险记》完整版](https://www.bilibili.com/video/BV1aDHQejEAP/)
- 时长：8,909.885 秒（约 2 小时 28 分 30 秒）
- 本机已完成：使用公开匿名接口重新下载并校验 640×360 代理；执行 `faster-whisper small / zh` 全片 ASR；生成完整镜头、事件与音频分析，以及 24 组自动事件联系表。所有媒体、中间 JSON 和复核图片只保存在仓库同级的 Git 忽略目录 `.local-media/bilibili-BV1aDHQejEAP`，不会随 Git 同步。
- 证据规模：4,627 个镜头、129 个事件、1,749 个音频段、1,194 个转写片段、5,231 个词；自动事件复核包包含 24 张联系表和 95 张事件关键帧。
- ASR 覆盖：ASR 报告处理到 8,909.868 秒，为媒体时长的 99.9998%；最后识别对白到 8,672.93 秒（97.34%），尾差 236.955 秒。尾段抽帧确认仍有地铁换乘、餐食和步行画面，并非纯结束卡；恢复工作时必须追加尾段音频/无 VAD 转写核验，不能仅凭 `status=ready` 判定语义覆盖完整。
- 当前断点：本地 `learning/analysis.full.json` 与 `learning/transcript.json` 均已成功写入，分析/ASR/FFmpeg 进程均已退出；尚未获取弹幕、完成人工重点区间复核、构建受限上下文、验证实际外层模型请求或生成正式 technique study。
- 恢复顺序：先验证本地完整 analysis 与 transcript，核验 ASR 尾段，再完成人工抽帧复核和上下文门禁；全部通过前保持“未完成”，不得计入正式聚合来源。

### 6. BV1TNZUB4EF6 — 正式学习未开始

- 标题：[非常紧绷的旅行..法国一个人旅行Vlog巴黎](https://www.bilibili.com/video/BV1TNZUB4EF6/)
- 时长：约 49 分 47 秒
- 当前情况：未执行完整学习流程；开始时须重新检查本机媒体，缺失则按安全下载流程获取，不能依赖其他电脑的临时目录。
- 缺失：完整分析、ASR、模型上下文、人工重点区间复核、正式 technique study。

## 已沉淀的跨视频结果

前四支已完成视频可聚合出：

- 完整来源数：4
- 稳定模式：14 条（显式 `minimum_source_support=2`）
- 聚合命令：`vlog-director aggregate-techniques`
- 当前限制：只统计 4 份完整 study；`BV19sm2BBEDd` 的重叠首日不生成新增 observation。另有 25 条模式仍为单来源，不能把开场预分析或未完成视频计入正式证据。

## 后续执行顺序

1. 执行 `BV1aDHQejEAP` 的完整学习流程。
2. 执行 `BV1TNZUB4EF6` 的完整学习流程。
3. 六支全部完成后重新聚合 techniques，并复核每条稳定模式的独立来源支持数。

## Git 与媒体边界

- Git 仅提交进度、代码、Schema、测试和脱敏后的正式学习产物。
- `C:\tmp\bilibili-*` 下的代理视频、音视频流、抽帧、ASR 中间文件与其他临时素材不上传 Git。
