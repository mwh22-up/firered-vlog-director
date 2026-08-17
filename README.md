# FireRed Vlog Director

FireRed Vlog Director 是一个本地优先、证据驱动的长 Vlog 导演系统。它负责理解原始素材、生成可比较的剪辑候选、保护关键对白和事件链，并在人工批准后驱动基础剪辑、字幕、逐段画面美化、HyperFrames 动效、Overlay 和发布 QA。

系统的目标不是“一键替代剪辑师”，而是把容易失控的自动化步骤变成可复现、可审查、可撤销的生产闭环：机器负责分析、候选、测量和渲染证据；人负责故事判断、文字听校、审美选择和最终发布。

## 当前状态

截至 2026-08-17，`feature/director-learning-loop` 分支的本地验证基线如下：

| 项目 | 当前状态 |
|---|---|
| Director 单元与集成测试 | 332 项通过，3 项按环境能力跳过 |
| Pipeline 测试 | 49 项通过 |
| 正式 JSON Schema | 40 份；包内使用的 runtime Schema 与仓库正式 Schema 一致性受测试保护 |
| 参考视频学习 | 26/26 支完成正式 Technique Study |
| Technique Aggregate | 26 个独立来源，58 条稳定模式，87 条单来源模式，`minimum_source_support=2` |
| 自动执行策略 | 1 条目标证据驱动的 EDL 执行规则、1 条开场候选规则、1 条变速预览规则；其余保持 guidance |
| 默认音乐策略 | `disabled`；输出无 BGM 母版，用户最后在剪映配乐 |
| 媒体策略 | 原片、代理、ASR、抽帧、MOV、MP4、模型和缓存全部留在 Git 外 |

“测试通过”表示数据契约、门禁和短合成媒体链路可工作，不表示某支真实长片已经获得人工审美批准。

## 系统架构

代码分为两个同级仓库：

- `firered-vlog-director`：导演决策、参考学习、字幕、画面处理、动效、审批、发布门禁与增强渲染。
- `firered-vlog-pipeline`：真实项目入库、代理生成、EDL 基础渲染、候选预览、逐切点 QA，以及与 Director 的跨仓库契约。

生产数据流：

```text
仓库外原始素材
  → Pipeline ingest / target analysis
  → moments + transcript + shot/event/audio evidence
  → Director 三套候选 EDL
  → 候选短代理与逐切点证据
  → 人工选择 + SHA approval
  → Pipeline 从原片重建 directed base
  → 字幕 / 逐段画面美化 / HyperFrames / Overlay
  → enhancement guard + release visual QA
  → 人工发布批准
  → 无 BGM 画面锁定母版
  → 剪映人工选曲与最终混音
```

版本和证据绑定遵循同一原则：edit plan、realized timeline、base media、字幕源、效果计划、渲染产物、QA 与人工 review 都通过 SHA-256 互相绑定。正文、时间、样式、媒体或策略变化后，旧证据自动失效。

## 已具备的能力

### 1. 项目和媒体边界

- 初始化可移植项目目录，不把真实媒体放进代码仓库。
- 校验项目内相对路径，拒绝路径穿越、UNC、盘符相对路径和越界输出。
- 支持显式 FFmpeg executable，也支持固定的便携 FFmpeg。
- 长任务可以作为 detached durable job 运行，写入不可重放的 job spec、状态、结果和 worker log。
- 输出目录必须是允许根目录的严格子目录；已有正式产物默认不覆盖。

### 2. 目标素材分析与内容保护

- 镜头、对白、声音、运动、清晰度和事件分析。
- `locked`、`protected`、`optional` 三层保护。
- `setup → payoff → reaction` 事件组整体保护。
- 用户 `remove/avoid`、`lock`、`restore`、`extend`、`shorten`、`reorder` 反馈结构化保存。
- 检查必留内容覆盖率、对白完整性和事件依赖；缺失时在渲染前阻断。
- VLM 请求和供应商证据使用独立 Schema 与 SHA 绑定，VLM 证据不能直接伪造人工批准。

### 3. 参考视频学习和导演记忆

- 对完整参考视频执行镜头、事件、音频、ASR 和人工重点区间复核。
- 受限 context packet 必须严格小于 180,000 字符。
- 最终 Responses 请求按原始 UTF-8 body 严格小于 200,000 bytes；等于上限也阻断。
- 聚合时按独立来源去重，稳定模式至少需要 2 个来源支持。
- 参考成片只提供正向保留模式；没有原片与成片映射时，不推断作者真实删片偏好。
- 26 支正式 Study、学习进度和聚合结果位于 `reference-learning/` 与 `docs/video-learning-progress.md`。

当前 Technique Aggregate 编译为三类结果：

- `humor-preserve-real-awkward-process`：有目标素材显式趣味证据时，可小幅改变边缘镜头是否入选。
- `opening-phased-hook-not-uniform-fast-cut`：只生成开场候选，不自动发布。
- `playback-rate-fast-forward-travel-compression-visual-estimate`：只生成带水印的倍率候选，必须人工选倍率。
- 其他稳定或单来源模式只进入 guidance，不会因为“学过参考片”就改变目标 EDL。

### 4. 多候选导演与人工批准

- 生成 `concise`、`balanced`、`immersive` 三套内容真实不同的候选时间线。
- 分别偏向趣味密度、故事与景色平衡、景色沉浸。
- 输出候选评分、目标证据、受影响区间、切点清单和推荐理由。
- 新旧时间线不能只改版本号后原样复制。
- 推荐和批准分离；批准凭证绑定候选文件 SHA。
- 候选被修改后不能继续沿用旧 approval。

### 5. 基础剪辑和切点 QA

`firered-vlog-pipeline` 可以：

- 只入库用户明确选择的源文件。
- 按 EDL 从原片逐段渲染并拼接章节和全片。
- 输出每段真实时长、累计 realized timeline 和真实 cut boundary。
- 对候选代理添加 `NON-RELEASE CANDIDATE` 水印。
- 为切点生成前后帧证据并检查黑帧、静音、爆点和时长漂移。
- 使用相同 FFmpeg 完整解码视频流和音频流。

正式 playback-rate 候选目前只开放 `1.25×`、`1.5×`、`2.0×`，使用 `atempo` 保持音高，并绑定 proposal、候选、realized timeline、cut QA、FFmpeg identity 和人工选择。

项目 `nordic-102-144-a-plus` 已另外验证 `正常 0.4 秒 → 6× → 正常 0.4 秒` 的喜剧赶路审看效果，但它目前是 post-render 项目证据，不属于通用 release 契约，不能据此宣称正式系统已开放任意 4×/6× 变速。

### 6. 字幕闭环

正式字幕流程：

```text
project-subtitles
→ audit-subtitles
→ probe-subtitle-layout
→ render-subtitle-preview
→ qa-subtitles
→ approve-subtitles
```

已经支持：

- 把原片 ASR 词级时间投影到 realized timeline。
- 不跨 edit cut 合并字幕。
- 按停顿、语义、字数、时长拆分与合并。
- 双 ASR 交叉验证和机器文字修订审计。
- 稳定 cue ID，不依赖数组下标。
- 中文 CPS、拉丁 WPS/CPS、最短/最长时长、相邻间隔、重叠和剪辑边界门禁。
- 确定性的安全合并或延长建议；机器修复不会自动标记为 verified。
- JSON、SRT、ASS 和 review record 输出。
- top/bottom、两行、安全边距、描边、粗体和半透明背景。
- 使用正式渲染同一 FFmpeg/libass/ASS/字体/画布执行真实排版测量。
- 字幕专属代理，不执行画面 treatment、音乐、ducking、Overlay 或完整 enhancement render。
- `all|risk` 范围，以及按 cue、segment、chapter 输出短代理。
- 每条高风险 cue 的入场、中间、退场帧和多类联系表。
- 正式审批绑定 readability QA、layout QA、visual QA、verified cue 集合和人工听校记录。

能力边界：没有 OCR 时，系统只能证明真实渲染、布局、安全区和帧证据，不能证明字幕文字完全正确。文字准确性仍需人工听校；正文、时间、位置或样式变化会使旧 approval 失效。

详细命令见 `docs/subtitle-production-loop.md`。

### 7. 逐段画面美化

正式流程：

```text
analyze-visual-segments
→ plan-visual-treatments
→ render-treatment-preview
→ qa-visual-treatments
→ 人工逐段复核
→ approve-visual-treatments
→ apply-visual-treatments
```

已经支持：

- 按 realized segment 抽取 20%/50%/80% 三个真实帧。
- 测量亮度分布、黑白裁切率、对比度、饱和度、RGB 均值、清晰度、运动和时间噪声。
- 只生成 renderer 已真实执行的保守 proposal。
- 自动 planner 可建议 brightness、contrast、saturation。
- 在低运动和测量证据满足条件时，可建议 `hqdn3d` 降噪或 `unsharp` 锐化。
- Renderer 可执行 exposure、gamma、RGB white balance 和等宽高比 crop/reframe，但自动 planner 在缺少可靠中性参照或保护区域时不会猜测这些参数。
- before/after 短代理、完整解码、三帧 QA、独立 human review、SHA approval 和新版 enhancement plan 应用。
- 新计划强制 `music.status=disabled`、空 tracks、ducking disabled。

当前会 fail closed 的处理：逐段防抖、非硬切 continuity、match action、任意 segment speed，以及没有人脸/主体/字幕/关键文字保护区域证据的自动 reframe。

详细命令见 `docs/visual-treatment-production-loop.md`。

### 8. HyperFrames 动效与 Overlay

HyperFrames 生产闭环：

```text
plan-effects
→ compose-effects
→ render-effects
→ qa-effects
→ 人工逐项复核
→ approve-effects
→ apply-effects
```

已经支持：

- 固定 `hyperframes@0.7.90`，离线、无网络资源、可逐帧随机 seek。
- 输出带 alpha 的 ProRes 4444 MOV。
- `firecut-bold-v1` 风格包和覆盖率、相邻间隔、单事件主效果预算。
- 基础 recipe：`impact_hit`、`kinetic_explain`、`place_reveal`、`reaction_burst`。
- 叙事 recipe：`time_jump_card`、`location_card`、`route_map`、`step_card`、`source_card`。
- 叙事卡要求已核验事实、来源和 `owned|licensed|public_domain` 权利状态。
- 真实 alpha bbox 与受保护区域碰撞检测。
- 基础视频合成代理、完整解码以及 entry/peak/exit 三帧证据。
- 独立 human review 和 approval；机器不会伪造“效果合适”。
- Renderer 按 timeline offset 合成透明视频，结束后不冻结尾帧。
- 普通 Overlay 支持安全边距、缩放、fade 和从最近边缘 slide 入退场。

`firecut-bold-v1` 是能力基线，不等于所有片段都应使用大字。真实项目可以使用更紧凑的 callout；文字尺寸、节奏、遮挡和趣味性仍必须人工审看。

详细命令见 `docs/effect-production-loop.md`。

### 9. Enhancement Renderer 和发布门禁

- 增强计划有正式 Schema 和包内 runtime Schema 双门禁。
- 视频 treatment、字幕、Overlay、音乐状态和渲染 stage order 都会在启动 FFmpeg 前校验。
- 未被 renderer 消费的字段或未知模式会 fail closed。
- base media、realized timeline 和所有资源必须匹配路径、大小与 SHA。
- 支持真实 FFmpeg filter graph、H.264/AAC 输出和双流完整解码。
- release visual QA 生成机器证据，但不会宣称 OCR 或人工审美通过。
- 最终 release approval 要求零 blocker 和独立、SHA 绑定的人工 review。

### 10. 音乐策略

音乐自动化不再作为当前生产目标：

- 新的画面处理计划默认音乐关闭。
- `plan-music` 只生成非阻断参考单，包括情绪、节奏、剪映搜索关键词、建议时间段、音量和淡入淡出。
- 系统不自动选曲，不把参考视频曲名/BPM 当作事实，不自动完成最终混音。
- 用户在剪映试听和配乐，优先保护对白与环境声。

仓库保留旧音乐 Schema、audition 和 ducking 代码用于兼容与测试，但它们不是当前默认交付链路。

## 推荐生产顺序

```text
1. init-project / ingest
2. analyze-project / analyze-target
3. direct-timeline
4. render candidate previews + cut QA
5. approve-previewed-timeline
6. Pipeline 从原片 render directed base
7. project-subtitles → subtitle approval
8. analyze-visual-segments → visual treatment approval
9. plan-effects → effect approval
10. apply subtitles/treatments/effects to a new enhancement plan
11. guard-enhancement --mode release
12. render-enhancement --mode release
13. qa-release-visual → approve-release
14. 导出无 BGM 母版，在剪映人工配乐和最终检查
```

每一步都创建新版本，不覆盖旧计划或旧证据。

## 快速开始

### 安装 Director

```powershell
git clone https://github.com/mwh22-up/firered-vlog-director.git
cd firered-vlog-director
git switch feature/director-learning-loop

py -3.11 -m venv .venv-analysis
.\.venv-analysis\Scripts\python.exe -m pip install -e ".[analysis,test]"
$env:PYTHONPATH = (Resolve-Path '.\src').Path
```

### 初始化仓库外项目

```powershell
.\scripts\init-project.ps1 `
  -ProjectsRoot D:\vlog-projects `
  -ProjectId family-trip
```

推荐结构：

```text
D:\code\
  firered-vlog-director\
  firered-vlog-pipeline\

D:\vlog-projects\
  family-trip\
    raw\
    brief.yaml
    work\analysis\
    work\plans\
    work\qa\
    work\proxy\
    output\
```

### 生成导演候选

```powershell
.\scripts\direct-project.ps1 `
  -ProjectPath ..\firered-vlog-pipeline\projects\family-trip `
  -ParentPlan ..\firered-vlog-pipeline\projects\family-trip\work\plans\edit_plan.v1.json `
  -Profile .\reference-learning\director-profile.aggregate.v5.json `
  -TechniqueProfile .\reference-learning\reference-techniques.aggregate.v1.json `
  -Moments ..\firered-vlog-pipeline\projects\family-trip\work\analysis\moments.json `
  -Version 2 `
  -TargetDurationSec 600
```

输出位于 `work/director/v2-proposal/`，状态必须是 `review_required`。

### 运行测试

Director：

```powershell
$env:PYTHONPATH = (Resolve-Path '.\src').Path
.\.venv-analysis\Scripts\python.exe -m unittest discover -s tests -p 'test_*.py' -v
```

Pipeline：

```powershell
$env:VLOG_FFMPEG_HOME = 'D:\tools\ffmpeg\bin'
..\firered-vlog-pipeline\.venv\Scripts\python.exe -m pytest -q
```

## 主要 CLI

| 范围 | CLI |
|---|---|
| 项目与门禁 | `init-project`, `validate-protection`, `guard-render`, `init-enhancement`, `guard-enhancement` |
| 目标分析与导演 | `analyze-target`, `analyze-project`, `direct-timeline`, `approve-timeline`, `approve-previewed-timeline` |
| VLM 与反馈 | `prepare-vlm-request`, `validate-vlm-evidence`, `compare-revision`, `derive-feedback`, `compile-revision` |
| 字幕 | `project-subtitles`, `audit-subtitles`, `probe-subtitle-layout`, `render-subtitle-preview`, `qa-subtitles`, `approve-subtitles` |
| 画面处理 | `analyze-visual-segments`, `plan-visual-treatments`, `render-treatment-preview`, `qa-visual-treatments`, `approve-visual-treatments`, `apply-visual-treatments` |
| 动效 | `plan-effects`, `compose-effects`, `render-effects`, `qa-effects`, `approve-effects`, `apply-effects` |
| 增强与发布 | `bind-directed-base`, `render-enhancement`, `qa-release-visual`, `approve-release` |
| 参考学习 | `analyze-reference`, `pack-reference-context`, `preflight-model-request`, `aggregate-reference`, `aggregate-techniques` |
| 音乐参考 | `plan-music`；旧 `qa-music`/`audition-music` 仅保留兼容 |

各命令的完整参数以 `python -m vlog_director.cli <command> --help` 和对应 `docs/` 文档为准。

## 数据契约与安全原则

- 未知字段默认拒绝，数值拒绝 bool、NaN、Infinity 和越界值。
- 正式 JSON 使用 UTF-8 无 BOM。
- 仓库正式 Schema 与 runtime Schema 一致性由测试保护。
- approval 不能靠手改 `status=ready` 或 `status=approved` 获得。
- 所有真实媒体、抽帧、联系表、原始 ASR、字幕中间文件、HyperFrames MOV、日志、模型、虚拟环境、Cookie、Token 和凭据都不得提交。
- 不在 Git 中保存本地绝对媒体路径。
- 只终止能够通过完整命令行和父进程树确认属于当前任务的 FFmpeg/Python/Whisper 进程。

## 仍需完成的工作

### P0：把 4×/6× 喜剧赶路快进变成正式能力

当前 Nordic 项目已证明效果方向可行，但正式系统还需要：

- 独立 `comedic_fast_forward` preview-only 契约，而不是放宽普通 playback-rate。
- 只允许低对白、连续移动、具有 motion 证据的区间。
- 固定正常入场/退场 bookend、受控 4×/6× 候选和安全音频策略。
- 轻量速度线参数进入计划和 SHA，而不是一次性 filter。
- 人工选择绑定 proposal、候选媒体、realized timeline、cut QA 和 FFmpeg identity。
- 选定后从 edit plan 重建全片，重新投影字幕并使旧动效/审批失效。
- 单元测试、真实 FFmpeg 集成测试和跨仓库契约测试。

### P0：完成当前真实项目的正式重建

`nordic-102-144-a-plus` 现有 6× 版本是效果审看稿。正式版本还要：

- 把新增机场赶路段写入新版本 EDL。
- 从原片重建 realized timeline，不在旧 MP4 上做最终二次拼接。
- 重新投影字幕。
- 重算全部动效时间并重新生成视觉 QA。
- 全片人工观看、对白听校、逐切点批准和 release approval。

### P1：逐段画面处理扩展

- 实现真实防抖，而不是仅保留 `off` 契约。
- 实现可验证的 continuity transition、match action 与边界 QA。
- 接入可靠的人脸、主体、字幕和关键文字保护区域检测。
- 有保护区域后再开放自动 reframe/crop planner。
- 改进白平衡证据，避免仅从 RGB 均值猜测中性参照。

### P1：字幕和动效完善

- 完成真实项目全部字幕人工听校，不把视觉 QA 当作文字正确性。
- 根据主体/关键文字证据实现动态 top/bottom 避让。
- 扩展紧凑 VOX/信息动效模板，避免每个笑点都使用大字卡。
- 为速度、动效和字幕叠加建立统一的 protected-region 冲突预算。
- 增加效果密度、章节呼吸和重复视觉语言的全片级 QA。

### P2：个人偏好学习和交付

- 用多个真实项目的恢复、删除、延长、缩短和重排事实校准排序。
- 评估何时需要学习排序模型；数据不足时继续使用可解释规则。
- 实现当前 Pipeline 占位的 `export-jianying`，但不自动选歌。
- Director 和本地 Worker 稳定后再建设 Web/Vercel 控制面。

音乐自动选曲与自动最终混音不在当前路线中；最终配乐继续由用户在剪映完成。

## 文档索引

- `docs/production-director-release-loop.md`：端到端导演、预览、批准与发布顺序。
- `docs/enhancement-pipeline.md`：增强计划、renderer 和 release guard。
- `docs/subtitle-production-loop.md`：字幕完整生产闭环。
- `docs/visual-treatment-production-loop.md`：逐段画面美化闭环。
- `docs/effect-production-loop.md`：HyperFrames 与 Overlay 动效闭环。
- `docs/video-learning-progress.md`：26 支参考视频的唯一学习进度来源。
- `docs/reference-learning-home-guide.md`：新电脑继续参考学习的操作指南。
- `docs/roadmap.md`：长期路线。

## GitHub 同步

仓库使用 Git Credential Manager，不需要把用户名、密码或 Personal Access Token 写入文件：

```powershell
git fetch origin
git pull --ff-only
git push origin feature/director-learning-loop
```

推送前必须执行测试、Schema/JSON 校验、`git diff --check`、敏感信息扫描和媒体扩展名扫描。
