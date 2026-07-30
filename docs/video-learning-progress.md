# 参考视频 Technique Learning 计划进度

更新时间：2026-07-30
执行分支：`feature/director-learning-loop`

## 总体进度

- 计划视频：6 支
- 已完成正式学习：2 支
- 已开始但未完成：1 支
- 未开始正式学习：3 支
- 完成率：2/6（33.3%）

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

### 3. BV19sm2BBEDd — 已暂停，未完成

- 标题：[《一个人的欧洲探险记》瑞士篇完整版](https://www.bilibili.com/video/BV19sm2BBEDd/)
- 时长：约 3 小时 43 分 18 秒
- 已完成：代理视频下载、元数据获取、开场片段与初步镜头分析、少量开场人工复核素材。
- 未完成：完整 ASR、完整视频分析、受限模型上下文、全片人工重点区间复核、正式 technique study。
- 当前检查：未发现仍在运行的 FFmpeg、Whisper 或 ASR 转写进程；此前疑似进程实际属于企业终端管理组件 Tanium。
- 正式产物：尚无 `reference-learning/technique-study.BV19sm2BBEDd.v1.json`。
- 恢复点：从完整 ASR 与全片分析重新启动；完成后再按 `<200,000` 字符门禁构建模型上下文并产出正式 study。

### 4. BV1ETNMzEEWQ — 正式学习未开始

- 标题：[《最伟大的作品》封面取景地 法国一个人旅行VLOG 圣米歇尔山](https://www.bilibili.com/video/BV1ETNMzEEWQ/)
- 时长：约 50 分 39 秒
- 当前情况：本机临时目录存在批量预下载和开场预分析素材，但未执行完整学习流程。
- 缺失：完整分析、ASR、模型上下文、人工重点区间复核、正式 technique study。

### 5. BV1aDHQejEAP — 正式学习未开始

- 标题：[《一个人的东京探险记》完整版](https://www.bilibili.com/video/BV1aDHQejEAP/)
- 时长：约 2 小时 28 分 30 秒
- 当前情况：本机临时目录存在批量预下载和开场预分析素材，但未执行完整学习流程。
- 缺失：完整分析、ASR、模型上下文、人工重点区间复核、正式 technique study。

### 6. BV1TNZUB4EF6 — 正式学习未开始

- 标题：[非常紧绷的旅行..法国一个人旅行Vlog巴黎](https://www.bilibili.com/video/BV1TNZUB4EF6/)
- 时长：约 49 分 47 秒
- 当前情况：本机临时目录存在批量预下载和开场预分析素材，但未执行完整学习流程。
- 缺失：完整分析、ASR、模型上下文、人工重点区间复核、正式 technique study。

## 已沉淀的跨视频结果

前两支已完成视频可聚合出：

- 来源数：2
- 稳定模式：21 条
- 聚合命令：`vlog-director aggregate-techniques`
- 当前限制：只有 2 个完整来源，跨来源模式仍需后续视频增加支持度，不能把开场预分析或未完成视频计入正式证据。

## 后续执行顺序

1. 恢复 `BV19sm2BBEDd`：完整 ASR → 全片分析 → 上下文压缩 → 人工复核 → technique study。
2. 执行 `BV1ETNMzEEWQ` 的完整学习流程。
3. 执行 `BV1aDHQejEAP` 的完整学习流程。
4. 执行 `BV1TNZUB4EF6` 的完整学习流程。
5. 六支全部完成后重新聚合 techniques，并复核每条稳定模式的独立来源支持数。

## Git 与媒体边界

- Git 仅提交进度、代码、Schema、测试和脱敏后的正式学习产物。
- `C:\tmp\bilibili-*` 下的代理视频、音视频流、抽帧、ASR 中间文件与其他临时素材不上传 Git。
