# 生产导演与发布闭环

本文是 `firered-vlog-director` 从导演决策到实际剪辑、字幕、HyperFrames 动效、音乐、最终视觉 QA 和人工发布批准的总入口。

系统遵循两条原则：

- 创意表达可以大胆，效果必须稀疏、可解释并受保护区约束。
- 发布判断必须保守，任何正式输入或证据变化都要使旧 approval 失效。

## 当前能力

### 导演与基础剪辑交接

- 分析目标素材并生成多套候选 EDL，保留镜头评分、参考技巧和目标证据 trace。
- 用户的 lock、remove、avoid 和显式反馈优先于参考片经验。
- 候选时间线必须先渲染为带水印的 proxy 预览并独立人工选择，不能把推荐结果直接当作最终剪辑。
- 旅行压缩只会提出无精确倍率的 preview-only proposal；Pipeline 固定生成 1.25x、1.5x、2.0x
  完整时间线候选供人工比较，不会自动选择倍率或直接进入发布计划。
- `directed-base-contract` 绑定 approved edit plan、approval receipt、realized timeline、基础媒体 SHA、生产仓库与提交、FFmpeg identity。
- 基础剪辑仍由外部 `firered-vlog-pipeline` 执行；本仓库负责交接合同和后续门禁。

### 字幕生产

- 支持 ASR 投影、稳定 cue ID、中英文阅读速度、时长、间隔、剪辑边界和 overlap 审计。
- 使用真实 FFmpeg/libass 测量像素布局、bbox、安全区与字体 fallback。
- preview 缺少真实布局时只能产生 warning；release 缺少真实 libass 证据必须 blocker。
- 字幕正文、时间、位置、样式、策略或任一 QA 文件变化都会使 approval 失效。
- 最终 ready source 不可变，并与 readability、policy、layout、visual QA 和 human review 的 SHA 绑定。

完整命令见 [字幕生产闭环](subtitle-production-loop.md)。

### HyperFrames 大胆动效

- 固定 `hyperframes@0.7.90` 和 npm integrity，使用 strict composition check。
- 首发效果包括 `impact_hit`、`kinetic_explain`、`place_reveal` 和 `reaction_burst`。
- 输出透明 ProRes 4444 MOV，并验证 alpha、时长、画布和完整解码。
- 同一时刻最多一个 primary effect，效果覆盖预算和呼吸间隔受正式计划约束。
- 透明 MOV alpha bbox、libass 字幕 bbox、face/main-subject regions 共同参与保护区碰撞审计。
- 三帧证据和联系表只构成机器证据，审美适配与强度仍需独立人工复核。

完整命令见 [HyperFrames 大胆动效生产闭环](effect-production-loop.md)。

### 音乐与增强渲染

- 音乐 audition 会真实解码，计算 BPM、beat grid 和 speech-band masking risk。
- 频谱遮蔽风险不能被表述为已经完成对白可懂度验证。
- enhancement plan 只有在字幕、动效和音乐各自满足证据与审批门禁后才可进入正式渲染。
- renderer 消费已批准的透明动效媒体，不循环静态图片冒充动效。

### 最终发布 QA

- 最终成片 visual QA 检测黑帧、冻结风险并生成首、中、尾证据帧。
- QA 绑定最终媒体、enhancement plan、directed-base contract、realized timeline、基础媒体和 FFmpeg identity。
- release approval 要求 visual QA 零 blocker，并消费独立的人工逐项复核记录。
- 最终媒体、计划、合同、QA 或 human review 任一 SHA 变化都会使 release approval 失效。

## 正式生产顺序

```text
目标素材分析
  -> 候选导演时间线
  -> proxy-only 非发布候选预览 + 真实切点 QA
  -> 多候选 review pack
  -> 人工选择记录
  -> approve-previewed-timeline
  -> 外部基础剪辑与 realized timeline
  -> 逐切点机器 QA 与独立人工复核
  -> bind-directed-base
  -> 字幕 / 动效 / 音乐各自生产、QA 与人工审批
  -> render-enhancement
  -> qa-release-visual
  -> 独立人工复核
  -> approve-release
```

对应 CLI：

```text
analyze-project / analyze-target
direct-timeline
firered-vlog-pipeline: render-candidate-previews.ps1
approve-previewed-timeline
bind-directed-base

project-subtitles
audit-subtitles
probe-subtitle-layout
render-subtitle-preview
qa-subtitles
approve-subtitles

plan-effects
compose-effects
render-effects
qa-effects
approve-effects
apply-effects

audition-music
render-enhancement
qa-release-visual
approve-release
```

耗时操作可以提交为 durable detached job。每个任务使用唯一目录、原子 job/status 写入、独立日志和不可覆盖的终态；排队任务可取消，旧 job 不能重放覆盖正式证据。

候选预览批准必须使用以下目录和证据链：

```text
work/director/v2-proposal/candidates/candidate.<variant>.json
work/director/v2-proposal/previews/<candidate-sha256>/
work/director/v2-proposal/review-pack.json
work/director/v2-proposal/selection.json
```

`selection.json` 必须符合 `schemas/directed-preview-selection.schema.json`，绑定 review pack、
选中 candidate、preview media、realized timeline 和 cut QA 的 SHA，并逐项确认播放、画面连续性、
对白完整性、音频连续性和故事连贯性。随后执行：

```powershell
.\scripts\approve-previewed-timeline.ps1 `
  -ProjectPath <project> `
  -Version 2 `
  -Candidate <project>\work\director\v2-proposal\candidates\candidate.balanced.json `
  -ReviewPack <project>\work\director\v2-proposal\review-pack.json `
  -Selection <project>\work\director\v2-proposal\selection.json `
  -ApprovedBy <operator>
```

旧 `approve-timeline` 仅为兼容入口；正式生产应使用绑定预览证据的新入口。候选、review pack、
selection 或任一预览证据的 SHA 变化都会阻止批准。

### 变速候选预览与审批

当 `director_report.json` 包含合格的 playback-rate proposal 时，将它显式传给 Pipeline：

```powershell
.\scripts\render-candidate-previews.ps1 `
  -ProjectPath <project> `
  -DirectorReport <project>\work\director\v2-proposal\candidates\director_report.json `
  -Candidates @(
    'balanced=<project>\work\director\v2-proposal\candidates\candidate.balanced.json',
    'immersive=<project>\work\director\v2-proposal\candidates\candidate.immersive.json'
  )
```

变速只适用于 `speech_ratio <= 0.1`、持续至少 8 秒、有足够 motion 证据，并且不含关键对白、
protected overlap 或 user lock 的单一素材区间。每个倍率候选都是带
`NON-RELEASE CANDIDATE` 水印的完整时间线预览，并绑定 proposal、derived candidate、预览媒体、
realized timeline、cut QA、FFmpeg identity 和 A/V sync。

人工选择使用 v2 `selection.json`，必须对选中 candidate 的每个 proposal 作出决定：至多选择一个
已预览倍率，其余写为 `rejected`；也可以拒绝全部。拒绝全部时正式 edit plan 保持基础 candidate
不变。选择倍率后，批准入口会确定性复算 derived candidate；proposal、Director report、预览媒体、
timeline、cut QA 或任一 SHA 变化都会使批准失效。参考学习只支持“可能适合旅行压缩”的模式，
不支持推断作者的真实精确倍率。

基础剪辑完成后，人工复核记录必须符合 `schemas/directed-base-human-review.schema.json`，并绑定当前 edit plan、realized timeline、基础媒体和 cut QA 的 SHA。四项检查都真实完成后才可写为 `approved`。随后执行：

```powershell
vlog-director bind-directed-base `
  --project <project> `
  --edit-plan <project>\work\plans\edit_plan.v2.json `
  --approval <project>\work\qa\edit_plan.v2.approval.json `
  --realized-timeline <project>\work\qa\render.v2.json `
  --cut-qa <project>\work\qa\cut-review.v2\cut-review.json `
  --human-review <project>\work\qa\directed-base-human-review.v2.json `
  --base-video <project>\output\directed.v2.mp4 `
  --producer-repository https://github.com/mwh22-up/firered-vlog-pipeline.git `
  --producer-commit <40-character-commit-sha> `
  --producer-contract render-directed-v2 `
  --output <project>\work\qa\directed-base.v2.json
```

## 机器结论边界

没有 OCR 时只能写：

> 已生成视觉帧和布局证据，文字准确性仍需人工听校。

不得宣称：

- 机器已经验证字幕文字准确性；
- 机器视觉帧等同于人工审美审批；
- VLM candidate moments 已批准删除镜头或发布成片；
- 音频频谱风险等同于对白可懂度已通过；
- 手工修改 `review_required`、`verified` 或 `ready` 可以替代正式审批合同。

当前 VLM 层只提供 fail-closed provider contract：绑定媒体、模型、provider version、prompt 和 shot SHA，并只允许输出 candidate moments。实际 FireRed/VLM 模型、运行时和授权需要由部署环境另外提供。

## Schema 与依赖

- 正式 Schema 位于 `schemas/`。
- 随包发布的 runtime Schema 位于 `src/vlog_director/schemas/`。
- 测试要求两套 Schema 内容一致并使用 fail-closed 字段约束。
- Python 依赖通过 `constraints/` 固定。
- HyperFrames 和 `ffprobe-static` 通过 `package.json`、`package-lock.json` 固定到公共 npm registry。
- `node_modules`、虚拟环境、媒体、抽帧、联系表、日志、缓存和凭据不得提交。

## CI 与验证基线

GitHub Actions 覆盖：

- Python 3.11 和 3.12；
- Ruff；
- bundled FFmpeg smoke；
- Linux 真实 libass；
- Node 22 HyperFrames strict alpha smoke。

本地最近一次完整验证结果：

- `Ran 318 tests`
- `OK (skipped=3)`；变速真实 FFmpeg 短媒体集成由 Pipeline 全量测试执行并通过；
- Ruff 通过；
- `compileall` 通过；
- 正式/runtime Schema 字节一致；
- `git diff --check`、UTF-8 无 BOM、依赖锁和提交污染审计通过；
- 真实 HyperFrames strict check、透明 ProRes alpha 和 FFmpeg 短媒体完整解码已通过。

这些结果不代表已经运行真实 FireRed/VLM 推理，也不代表任何未经人工签署的视觉或发布审批。

## 项目安全边界

- 真实视频项目、模型、工作目录和最终媒体必须保存在代码仓库之外。
- cleanup path 必须是项目 `work/proxy` 或 `work/qa` 下的严格子目录，不能等于根目录。
- release 布局探针必须重新执行真实测量，不能信任磁盘 cache。
- 正式证据与 approval 只能新增版本，不能覆盖旧产物继续沿用旧 SHA。
