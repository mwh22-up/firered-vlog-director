# 字幕生产闭环

本文说明如何只使用正式 CLI 完成字幕投影、可读性审计、真实排版测量、字幕专属代理、视觉 QA、人工审校、SHA 绑定审批，以及最终 release 门禁。字幕代理不会进入完整增强渲染，也不会执行画面 treatment、音乐、ducking 或 overlay。

## 能力边界

整条生产链为：

```text
ASR 词级时间 + 已批准 edit plan + realized timeline
→ subtitle draft / review record / SRT
→ readability audit + safe repair proposal
→ real libass layout probe
→ subtitle-only proxy
→ subtitle visual QA
→ human review
→ approval + immutable ready source + ready evidence
→ release guard
→ final enhancement render
```

机器产物与人工结论必须分开：

- `audit-subtitles` 会计算时长、gap、overlap、中文 CPS、拉丁 WPS/CPS、行数和切点邻近风险；它只提出确定性的合并或延长建议，不会静默修改正文，也不会把修复结果标记为 `verified`。
- `probe-subtitle-layout` 使用指定 FFmpeg 的真实 `subtitles` filter/libass 和正式 ASS 渲染合同测量像素 bbox。draft 快速启发式可以用于 preview，但 release 必须有 `real_libass` 结果。
- `render-subtitle-preview` 只烧录字幕并保留原音轨；不会执行逐段画面处理、音乐、ducking、overlay 或完整 enhancement render。
- `qa-subtitles` 会验证 cue 渲染证据、真实 libass 解析、代理双流完整解码、布局绑定并生成视觉帧和联系表；它不执行 OCR，也不会把人工状态改为通过。
- `approve-subtitles` 只消费已经独立完成的人工审校记录。手改 `status=ready`、`review_status=verified` 或 QA 状态不能建立有效审批。

视觉 QA 的固定表述是：

> 已生成视觉帧和布局证据，文字准确性仍需人工听校。

没有可靠 OCR 时，不得把“画面中出现了字幕”解释为“字幕文字完全正确”，也不得伪造 OCR、视觉识别或人工通过状态。

## 项目目录和路径约束

真实视频项目应位于代码仓库之外。以下目录是正式字幕流程使用的边界：

```text
D:\vlog-projects\family-trip\
  assets\fonts\                         # 明确提供给 libass 的字体
  output\directed.v5.mp4                # 用户明确指定的基础/预览视频
  work\analysis\*.json                  # 完整 ASR/目标分析
  work\plans\edit_plan.v5.json
  work\enhancement\enhancement_plan.v5.json
  work\subtitles\
    subtitles.review.v5.json
    subtitles.review-record.v5.json
    subtitles.ready.v5.json
  work\qa\
    render.v5.json                       # realized timeline
    subtitle-readability.*.v5.json
    subtitle-layout.*.v5.json
    subtitle-visual-qa.v5.json
    subtitle-human-review.v5.json
    subtitle-approval.v5.json
    subtitle-ready-evidence.v5.json
  work\proxy\subtitle-preview\...       # ASS、短代理、manifest、FFmpeg 日志和进度
  work\jobs\...                         # detached job spec、status 和 worker log
```

带 `--project` 的 CLI 会限制正式产物所在目录：

| 参数/产物 | 允许目录 |
| --- | --- |
| edit plan | `work/plans/` |
| target analysis | `work/analysis/` |
| 字幕 source、ready source | `work/subtitles/` |
| enhancement plan | `work/enhancement/` |
| realized timeline、readability policy、readability/layout/visual/human review/approval/evidence | `work/qa/` |
| preview manifest、ASS 和代理媒体 | `work/proxy/` |
| 字体目录 | `assets/fonts/` |
| detached job 状态 | `work/jobs/`（CLI 内部参数，不应手工传入） |

`--base-video` 必须由用户显式指定，不存在隐藏视频回退。字幕代理要求它同时包含视频流和音频流，且时长与 realized timeline 一致。显式 preview 输出目录必须是新目录或空目录；省略时会在 `work/proxy/subtitle-preview/` 下创建带时间和随机 ID 的唯一目录。审批和 ready 输出不能覆盖既有输入或既有输出。

`project-subtitles`、`audit-subtitles`、显式 preview manifest copy、`qa-subtitles` 报告和 `approve-subtitles` 的正式输出必须是尚不存在、彼此不同且不与输入重合的路径；visual evidence 和显式 preview 输出目录也必须是新目录或空目录。修订后重跑时应使用新的版本或 revision 文件名，例如从 `.v5.json` 改为 `.v5.r2.json`；不要覆盖旧证据后继续沿用其 SHA 绑定。

项目中的媒体、ASS、PNG 联系表、日志、缓存、ASR 中间文件和人工审校材料可能包含隐私信息，不应提交到代码仓库。正式 JSON 也应留在仓库外的视频项目中；仓库只保存 Schema、代码、文档和不含私有素材的测试 fixture。

## PowerShell 准备

以下示例假设仓库已经安装到 `.venv-test`，项目版本为 5。先按本机实际位置修改变量：

```powershell
$repo = 'D:\vlog-studio\firered-vlog-director'
$project = 'D:\vlog-projects\family-trip'
$version = 5

Set-Location $repo
$python = (Resolve-Path '.\.venv-test\Scripts\python.exe').Path
$cli = (Resolve-Path '.\.venv-test\Scripts\vlog-director.exe').Path
$ffmpeg = & $python -c "from imageio_ffmpeg import get_ffmpeg_exe; print(get_ffmpeg_exe())"

$editPlan = Join-Path $project "work\plans\edit_plan.v$version.json"
$timeline = Join-Path $project "work\qa\render.v$version.json"
$plan = Join-Path $project "work\enhancement\enhancement_plan.v$version.json"
$baseVideo = Join-Path $project "output\directed.v$version.mp4"
$subtitleReview = Join-Path $project "work\subtitles\subtitles.review.v$version.json"
$reviewRecord = Join-Path $project "work\subtitles\subtitles.review-record.v$version.json"
$readabilityPreview = Join-Path $project "work\qa\subtitle-readability.preview.v$version.json"
$readabilityRelease = Join-Path $project "work\qa\subtitle-readability.release.v$version.json"
$layoutPreview = Join-Path $project "work\qa\subtitle-layout.preview.v$version.json"
$layoutRelease = Join-Path $project "work\qa\subtitle-layout.release.v$version.json"
$fonts = Join-Path $project 'assets\fonts'
```

每个命令都提供独立帮助：

```powershell
& $cli project-subtitles --help
& $cli audit-subtitles --help
& $cli probe-subtitle-layout --help
& $cli render-subtitle-preview --help
& $cli qa-subtitles --help
& $cli approve-subtitles --help
```

## 1. 投影 ASR 到实际剪辑时间线

每个源视频提供一份完整 target analysis；`--analysis` 可重复。输出是待审校 source、投影审校清单和可选 SRT，不是 ready 字幕。这里的 `subtitle_review_record` 用于逐 cue 听校工作，不是第 6 步符合 `subtitle-human-review` Schema 的最终批准记录：

```powershell
$analysisA = Join-Path $project 'work\analysis\GX010130.analysis.json'
$analysisB = Join-Path $project 'work\analysis\GX010131.analysis.json'
$srtDraft = Join-Path $project "work\subtitles\subtitles.review.v$version.srt"

& $cli project-subtitles `
  --project $project `
  --edit-plan $editPlan `
  --realized-timeline $timeline `
  --analysis $analysisA `
  --analysis $analysisB `
  --subtitle-version $version `
  --draft-output $subtitleReview `
  --review-output $reviewRecord `
  --srt-output $srtDraft
if ($LASTEXITCODE -ne 0) { throw "project-subtitles failed: $LASTEXITCODE" }
```

cue ID 来自稳定来源证据，不使用数组下标。字幕不能跨 edit cut 合并；改变输入排序不应改变同一 cue 的身份。

## 2. 可读性审计和安全修复建议

先用 preview 模式生成风险队列。默认策略版本为 `1.0`，包括 `min_duration_sec=0.8`、`max_duration_sec=5.5`、`min_gap_sec=0.08`、中文不超过 8 个可见字符/秒、拉丁文本不超过 3 词/秒和 15 字符/秒、最多两行、每行最多 18 个可见字符，以及 0.3 秒切点邻近容差：

```powershell
& $cli audit-subtitles `
  --project $project `
  --subtitle-source $subtitleReview `
  --realized-timeline $timeline `
  --output $readabilityPreview `
  --mode preview
if ($LASTEXITCODE -ne 0) { throw "preview readability audit failed: $LASTEXITCODE" }

$readability = Get-Content -Raw -Encoding UTF8 $readabilityPreview | ConvertFrom-Json
$readability | Select-Object status, cue_count, blocker_count, warning_count, repair_count
$readability.high_risk_cue_ids
```

可选 `--policy <policy.json>` 可以只覆盖已知策略字段，省略字段沿用版本 `1.0` 的默认值；序列化到 readability QA 时会输出完整 policy。未知字段、把 bool 当数值、NaN、Infinity、负数和冲突范围都会 fail closed。策略还显式控制 0.65 秒最大合并 gap、是否允许自动合并和是否允许安全延长。

`proposed_repair` 只是建议。人工需要结合音频、语义和切点决定是否应用；应用后仍保持 `review_required`，重新听校，并重新生成所有下游 QA。不能跨 cut 合并，不能改变对白顺序，不能制造 overlap，不能越过 segment 边界延长。

人工修订并逐条听校后，只有确实检查过的 cue 才能设为 `review_status=verified`；只有全部 segment 覆盖完成后才能设 `coverage.status=verified`。随后重新执行 release 审计：

```powershell
& $cli audit-subtitles `
  --project $project `
  --subtitle-source $subtitleReview `
  --realized-timeline $timeline `
  --output $readabilityRelease `
  --mode release
if ($LASTEXITCODE -ne 0) { throw "release readability audit blocked: $LASTEXITCODE" }
```

release 只有在所有硬门禁通过时返回 0；短 cue、阅读速度超限、overlap、越界、未解决切点风险等都会阻断。进入审批还必须检查 JSON 本身为 `status=passed` 且 `release_ready=true`；不能只看进程退出码。

## 3. 使用真实 FFmpeg/libass 测量布局

preview 探针允许明确降级为 heuristic，并在 QA 中记录 warning；release 探针缺少 `subtitles` filter、libass、确定字体或真实像素测量时会阻断，不能静默退回字符估算。

```powershell
$layoutCache = Join-Path $project 'work\qa\subtitle-layout-cache'

& $cli probe-subtitle-layout `
  --project $project `
  --base-video $baseVideo `
  --subtitle-source $subtitleReview `
  --plan $plan `
  --realized-timeline $timeline `
  --readability-qa $readabilityPreview `
  --output $layoutPreview `
  --cache-directory $layoutCache `
  --fonts-directory $fonts `
  --ffmpeg-executable $ffmpeg `
  --mode preview
if ($LASTEXITCODE -ne 0) { throw "preview layout probe blocked: $LASTEXITCODE" }
```

每个 cue 的结果绑定正文 hash、样式 hash、ASS hash、FFmpeg 身份、字体目录身份、实际画布、真实 bbox、安全区、行数、字号、位置、裁切和 fallback 状态。540p、1080p、横屏和竖屏必须分别以对应 base video 的实际画布测量；缓存键会隔离不同文本、换行、样式、画布、字体目录、FFmpeg 和 probe 版本。

人工修订完成后，使用 release readability QA 重跑 release 探针：

```powershell
& $cli probe-subtitle-layout `
  --project $project `
  --base-video $baseVideo `
  --subtitle-source $subtitleReview `
  --plan $plan `
  --realized-timeline $timeline `
  --readability-qa $readabilityRelease `
  --output $layoutRelease `
  --cache-directory $layoutCache `
  --fonts-directory $fonts `
  --ffmpeg-executable $ffmpeg `
  --mode release
if ($LASTEXITCODE -ne 0) { throw "release layout probe blocked: $LASTEXITCODE" }
```

FFmpeg 退出 0 只表示滤镜命令执行成功，不等于没有 glyph、背景框裁切或安全区越界；应检查 layout QA 的 `status`、`probe_mode`、`summary`、每 cue 的 `measured_bbox`、`clipped`、`inside_safe_area` 和 blocker。

## 4. 生成字幕专属代理

### 高风险短代理

`scope=risk` 必须提供 readability QA，且不能与 `proxy-unit=timeline` 组合。按 cue 输出时，`--padding-sec` 会在高风险 cue 前后保留上下文：

```powershell
$riskProxy = Join-Path $project "work\proxy\subtitle-preview\v$version-risk"
$riskManifest = Join-Path $project "work\proxy\subtitle-preview.v$version.risk.manifest.json"

$queued = & $cli render-subtitle-preview `
  --project $project `
  --base-video $baseVideo `
  --subtitle-source $subtitleReview `
  --realized-timeline $timeline `
  --plan $plan `
  --readability-qa $readabilityPreview `
  --layout-qa $layoutPreview `
  --scope risk `
  --proxy-unit cue `
  --padding-sec 0.75 `
  --output-directory $riskProxy `
  --manifest-output $riskManifest `
  --ffmpeg-executable $ffmpeg | ConvertFrom-Json

$queued | Format-List status, pid, job_status, worker_log
```

### 审批前的 all-scope 代理

最终视觉 QA 必须覆盖全部 cue。`proxy-unit=cue` 生成短代理而不是完整 enhancement render：

```powershell
$allProxy = Join-Path $project "work\proxy\subtitle-preview\v$version-all"
$allManifest = Join-Path $project "work\proxy\subtitle-preview.v$version.all.manifest.json"

$queued = & $cli render-subtitle-preview `
  --project $project `
  --base-video $baseVideo `
  --subtitle-source $subtitleReview `
  --realized-timeline $timeline `
  --plan $plan `
  --readability-qa $readabilityRelease `
  --layout-qa $layoutRelease `
  --scope all `
  --proxy-unit cue `
  --padding-sec 0.75 `
  --output-directory $allProxy `
  --manifest-output $allManifest `
  --ffmpeg-executable $ffmpeg | ConvertFrom-Json
```

`--proxy-unit` 也支持 `segment` 和 `chapter`；对应 cue 必须带有效 `segment_id` 或 `chapter_id`，选中的单位会包含该单位内全部字幕。`scope=all` 额外支持 `timeline`。每个 manifest 都绑定字幕 source path/SHA、可选 enhancement plan SHA、realized timeline SHA、base media 身份、FFmpeg 身份、readability policy 版本、layout probe 版本，以及 ASS 和输出媒体 SHA。

默认不加 `--foreground`，CLI 只提交 detached worker，并立即返回 `status=queued`。这时 `$LASTEXITCODE=0` 只表示提交成功，不表示渲染完成。返回 JSON 中包含：

- `job_status`：指向包含 `queued`、`running`、`completed`、`blocked` 或 `failed` 的结构化状态文件；
- `worker_log`：后台 Python worker 的独立日志；
- `job_spec`：可审计参数；
- `pid`：仅供诊断，进程存在不是成功证据。

代理输出目录包含 `manifest.json`、`progress.jsonl`、`ffmpeg.log`、ASS 和 MKV 短代理。可用以下命令检查，但必须以最终 status、退出信息、manifest、输出文件和 SHA 为准：

```powershell
Get-Content -Raw -Encoding UTF8 $queued.job_status | ConvertFrom-Json
Get-Content -Tail 80 -Encoding UTF8 $queued.worker_log
Get-Content -Tail 20 -Encoding UTF8 (Join-Path $allProxy 'progress.jsonl')
Get-Content -Raw -Encoding UTF8 (Join-Path $allProxy 'manifest.json') | ConvertFrom-Json
```

短素材调试时可显式传 `--foreground` 同步等待。长任务应保持默认 detached；不能依附单个 Codex 前台工具回合存活。

完成复核后，只能依据 manifest 的 `cleanup_paths` 清理这一次的唯一代理目录；不要对整个 `work/proxy/` 或项目根目录执行递归清理。

## 5. 生成视觉 QA

只对与 manifest 完全相同的 readability/layout QA 运行；任何 SHA 不一致都会阻断。审批使用 all-scope manifest：

```powershell
$visualQa = Join-Path $project "work\qa\subtitle-visual-qa.v$version.json"
$visualEvidence = Join-Path $project "work\qa\subtitle-visual\v$version-all"

$queued = & $cli qa-subtitles `
  --project $project `
  --preview-manifest $allManifest `
  --readability-qa $readabilityRelease `
  --layout-qa $layoutRelease `
  --output $visualQa `
  --evidence-directory $visualEvidence `
  --ffmpeg-executable $ffmpeg | ConvertFrom-Json

$queued | Format-List status, pid, job_status, worker_log
```

`qa-subtitles` 默认也是 detached job。成功完成后，正式报告至少包含 cue 总数、实际渲染数、cue ID、缺失 cue、readability/layout 汇总、blocker/warning、高风险队列和人工状态；证据目录包含：

- 每条 cue 的中间帧；
- 每条高风险 cue 的入场帧、中间帧和退场帧；
- 两行字幕、字幕密集段、top/bottom 位置变化、剪辑边界风险和超短字幕联系表；
- 独立 FFmpeg 日志。

机器通过后的 visual QA 仍应是 `status=review_required`、`human_review.status=pending`、`release_ready=false`。这是正确状态，不应手改。

## 6. 人工听校、审批和 ready evidence

人工审校必须同时检查：

1. 音频与字幕正文准确性；
2. 时间、入退场和剪辑边界；
3. 可读性；
4. 字体、背景框、安全区和 top/bottom 位置；
5. visual QA 的逐 cue 帧和风险联系表。

人工审校记录必须符合 `schemas/subtitle-human-review.schema.json`，并由实际审校工具或审校人写入 `work/qa/`。它要绑定当前 subtitle source、payload、style、verified cue 集合，以及 readability、layout、visual QA 的 SHA。所有五项 `checks` 只有在真实检查完成后才能为 `approved`；未完成时保持 `pending`，拒绝时写 `rejected`。不要猜测 canonical digest，也不要复制旧版本记录。

示意结构如下；尖括号字段必须由当前文件和正式 canonical digest 生成器填入真实值：

```json
{
  "schema_version": "1.0",
  "document_type": "subtitle_human_review",
  "status": "approved",
  "project_id": "family-trip",
  "subtitle_source_sha256": "<64 lowercase hex>",
  "subtitle_payload_sha256": "<64 lowercase hex>",
  "subtitle_style_sha256": "<64 lowercase hex>",
  "verified_cue_set_sha256": "<64 lowercase hex>",
  "readability_qa_sha256": "<64 lowercase hex>",
  "layout_qa_sha256": "<64 lowercase hex>",
  "visual_qa_sha256": "<64 lowercase hex>",
  "cue_ids": ["<every verified cue_id>"],
  "checks": {
    "audio_text_accuracy": "approved",
    "timing_and_cut_boundaries": "approved",
    "readability": "approved",
    "layout_and_safe_area": "approved",
    "visual_evidence_review": "approved"
  },
  "approved_by": "Subtitle Reviewer",
  "approved_at": "2026-08-03T20:00:00+08:00",
  "notes": []
}
```

完成真实人工审校后运行审批。approval 和 enhancement evidence 写入 `work/qa/`，不可变 ready source 写入 `work/subtitles/`：

```powershell
$humanReview = Join-Path $project "work\qa\subtitle-human-review.v$version.json"
$approval = Join-Path $project "work\qa\subtitle-approval.v$version.json"
$readySource = Join-Path $project "work\subtitles\subtitles.ready.v$version.json"
$readyEvidence = Join-Path $project "work\qa\subtitle-ready-evidence.v$version.json"

& $cli approve-subtitles `
  --project $project `
  --subtitle-source $subtitleReview `
  --plan $plan `
  --readability-qa $readabilityRelease `
  --layout-qa $layoutRelease `
  --visual-qa $visualQa `
  --human-review $humanReview `
  --approved-by 'Subtitle Reviewer' `
  --approval-output $approval `
  --ready-source-output $readySource `
  --evidence-output $readyEvidence
if ($LASTEXITCODE -ne 0) { throw "subtitle approval blocked: $LASTEXITCODE" }
```

`approved_by` 必须与 human review 完全一致。ready evidence 使用 `subtitle-ready-evidence-v1`，可直接放入 enhancement plan 的 `subtitles.evidence`；同时将 `subtitles.source` 指向 ready source、更新 `source_sha256`，并让 plan cues 和 style 与 ready source/审批合同严格一致。不要手工拼 SHA 或从旧计划复制 evidence。

enhancement plan 中的目标结构如下。`evidence` 必须逐字段复制本次 CLI 生成的 `$readyEvidence` 内容，`cues` 必须是 ready source 的精确渲染投影，`style` 必须与探针和审批使用的 plan style 完全一致：

```json
{
  "subtitles": {
    "status": "ready",
    "language": "zh-CN",
    "source": "work/subtitles/subtitles.ready.v5.json",
    "source_sha256": "<ready source file SHA-256>",
    "coverage": { "status": "verified" },
    "cues": [
      {
        "cue_id": "<stable cue ID>",
        "segment_id": "<segment ID>",
        "chapter_id": "<chapter ID>",
        "start_sec": 1.0,
        "end_sec": 2.2,
        "text": "已人工听校的字幕",
        "review_status": "verified",
        "position": "bottom_center"
      }
    ],
    "style": { "<exact approved style>": "<value>" },
    "evidence": {
      "contract_version": "subtitle-ready-evidence-v1",
      "subtitle_payload_sha256": "<generated digest>",
      "subtitle_style_sha256": "<generated digest>",
      "verified_cue_set_sha256": "<generated digest>",
      "readability": { "path": "work/qa/<file>.json", "sha256": "<sha256>" },
      "layout": { "path": "work/qa/<file>.json", "sha256": "<sha256>" },
      "visual": { "path": "work/qa/<file>.json", "sha256": "<sha256>" },
      "human_review": { "path": "work/qa/<file>.json", "sha256": "<sha256>" },
      "approval": { "path": "work/qa/<file>.json", "sha256": "<sha256>" }
    }
  }
}
```

正文、时间、位置、样式、cue 集合、realized timeline、readability/layout/visual/human review/approval 任一变化，都会使旧 QA 或 approval 失效。修改后从 readability audit 开始重跑；不能只改文件名或状态复用旧证据。

## 7. Release 门禁和最终增强渲染

enhancement plan 接入 ready source 和 ready evidence 后，先执行 release guard：

```powershell
& $cli guard-enhancement `
  --project $project `
  --version $version `
  --realized-timeline $timeline `
  --mode release
if ($LASTEXITCODE -ne 0) { throw "release enhancement guard blocked: $LASTEXITCODE" }
```

门禁通过后才能进入完整增强渲染：

```powershell
$finalVideo = Join-Path $project "output\final.v$version.mp4"
$renderQa = Join-Path $project "work\qa\enhancement-render.v$version.json"

& $cli render-enhancement `
  --project $project `
  --base-video $baseVideo `
  --plan $plan `
  --realized-timeline $timeline `
  --output $finalVideo `
  --qa-output $renderQa `
  --ffmpeg-executable $ffmpeg `
  --mode release
if ($LASTEXITCODE -ne 0) { throw "release render failed: $LASTEXITCODE" }
```

字幕专属代理和最终增强渲染职责不同：前者只用于快速字幕复核；后者才会执行 plan 中已批准的画面、音乐、ducking 和 overlay。代理成功不能代替 release guard 或最终媒体 QA。

## Schema 和失效规则

本轮字幕产物使用六份正式 Schema，并在包内保留完全一致的 runtime 副本：

| 产物 | 正式 Schema |
| --- | --- |
| 可读性审计 | `schemas/subtitle-readability-qa.schema.json` |
| 真实排版结果 | `schemas/subtitle-layout-qa.schema.json` |
| 字幕代理 manifest | `schemas/subtitle-preview-manifest.schema.json` |
| 视觉 QA | `schemas/subtitle-visual-qa.schema.json` |
| 人工审校记录 | `schemas/subtitle-human-review.schema.json` |
| 审批凭证 | `schemas/subtitle-approval.schema.json` |

ready evidence 的结构属于 `schemas/enhancement-plan.schema.json` 中的 `subtitle-ready-evidence-v1`。所有新 Schema 默认 `additionalProperties=false`，未知字段 fail closed。旧产物即使有 `status=ready`，缺少新版 readability、真实 layout、visual、human review 和 approval 绑定时仍按 legacy 阻断 release。

## 完成判定

不要只看进程名、PID、长时间无输出或 FFmpeg 返回成功。detached 提交命令返回 0 只代表成功入队；应读取最终 `status.json`、worker log 和对应 manifest/report，确认 worker 的最终退出结果。一次完整闭环至少要确认：

- detached `status.json` 为 `completed`，`exit_code=0`，且对应 worker log 没有失败；`blocked`/`failed` 或非零退出码都不能宣称成功；
- preview manifest 可解析，ASS/媒体文件存在且 SHA 与 manifest 一致；
- visual QA 可解析，`machine_status=passed`、无 blocker、无 missing cue；
- release readability 为 `passed` 且 `release_ready=true`；
- release layout 为 `passed`、`probe_mode=real_libass`，每条 cue 都有真实测量且无裁切/越界；
- human review 是真实完成的独立证据；
- `approve-subtitles` 新建 approval、ready source 和 ready evidence；
- release guard 和最终渲染退出码均为 0；
- 本地 Git 状态中没有媒体、ASS、PNG、日志、缓存、ASR 中间文件或凭据。
