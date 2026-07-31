# 参考视频 Technique Learning 计划进度

更新时间：2026-07-31
执行分支：`feature/director-learning-loop`

## 总体进度

- 计划视频：6 支
- 已完成正式学习：5 支
- 已开始但未完成：0 支
- 未开始正式学习：1 支
- 完成率：5/6（83.3%）

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

### 6. BV1TNZUB4EF6 — 正式学习未开始

- 标题：[非常紧绷的旅行..法国一个人旅行Vlog巴黎](https://www.bilibili.com/video/BV1TNZUB4EF6/)
- 时长：约 49 分 47 秒
- 当前情况：未执行完整学习流程；开始时须重新检查本机媒体，缺失则按安全下载流程获取，不能依赖其他电脑的临时目录。
- 缺失：完整分析、ASR、模型上下文、人工重点区间复核、正式 technique study。

## 已沉淀的跨视频结果

前五支已完成视频可聚合出：

- 完整来源数：5
- 稳定模式：20 条（显式 `minimum_source_support=2`）
- 单来源模式：26 条
- 聚合命令：`vlog-director aggregate-techniques`
- 当前限制：只统计 5 份完整 study；`BV19sm2BBEDd` 的重叠首日不生成新增 observation。单来源模式不能计为稳定跨来源模式，开场预分析或未完成视频也不得进入正式聚合。

## 后续执行顺序

1. 执行 `BV1TNZUB4EF6` 的完整学习流程。
2. 六支全部完成后重新聚合 techniques，并复核每条稳定模式的独立来源支持数。

## Git 与媒体边界

- Git 仅提交进度、代码、Schema、测试和脱敏后的正式学习产物。
- 代理视频、音视频流、抽帧、ASR 中间文件、弹幕与其他临时素材只保存在仓库外的 Git 忽略目录，不上传 Git。
