# FireRed Vlog Director Core

> 大胆动效已接入 HyperFrames 生产闭环：导演系统生成 `firecut-bold-v1` 效果计划，固定 `hyperframes@0.7.90` 渲染透明 MOV，再经过基础剪辑合成代理、三帧视觉证据、独立人工复核、SHA approval 和 enhancement release gate。四类首发 recipe 为 `impact_hit`、`kinetic_explain`、`place_reveal`、`reaction_burst`。完整命令与安全边界见 [HyperFrames 大胆动效生产闭环](docs/effect-production-loop.md)。

从目标素材分析、候选 EDL、基础剪辑交接，到字幕、动效、音乐、最终 visual QA 和人工发布批准的整体顺序见 [生产导演与发布闭环](docs/production-director-release-loop.md)。

可移植的“导演大脑”，用于分析目标原片、应用参考片经验、生成并评分多套候选 EDL、保护重要事件链，并在人工批准后驱动原片重剪。

当前包含：

- 目标原片的镜头、事件、对白和声音分析；
- `concise`（趣味优先）、`balanced`（美景与趣味平衡）、`immersive`（美景优先）三套会改变选片的候选时间线；
- 参考片档案对镜头角色、节奏和事件链的可追踪评分影响；
- 十二来源 Technique Aggregate，以及仅凭目标证据触发的白名单执行规则；
- 新旧时间线差异门禁，禁止换版本号后原样复制旧 EDL；
- 候选推荐与人工批准分离，批准后使用 SHA-256 防止 EDL 被静默修改；
- 渲染后逐切点黑帧、静音、音频爆点和前后帧审查清单；
- `moments.json`、`director_profile.json` 数据契约；
- `locked`、`protected`、`optional` 保护策略；
- `setup/payoff/reaction` 成组保护；
- `edit_plan.json` 覆盖率校验；
- 参考片学习清单与导演档案契约；
- ASR、镜头评分、事件分组、声音分段与跨视频聚合；
- 配乐、防抖与连贯、字幕、插画动效的统一增强计划及运行时 Schema 门禁；
- 字幕可读性硬门禁、真实 FFmpeg/libass 排版测量、字幕专属代理、视觉 QA 和 SHA 绑定人工审批；
- 不依赖真实素材的单元测试，以及生成计划到基础 CLI 渲染与 QA 的 FFmpeg `lavfi` 集成测试。

## 推荐目录

代码仓库和真实视频项目分开保存：

```text
D:\vlog-studio\firered-vlog-director\   # GitHub 代码仓库
D:\vlog-projects\                       # 不进入 GitHub
  family-trip\
    raw\
    brief.yaml
    work\analysis\moments.json
    work\plans\edit_plan.v1.json
    work\qa\protection.v1.json
    output\
```

## 本地运行

```powershell
cd firered-vlog-director
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[test]"
.\scripts\test.ps1
```

`test` extra 会安装单元测试、参考分析和固定版本的便携 FFmpeg 所需依赖；测试会校验全部 14 个 Schema、仓库中的正式 JSON 产物，并用临时 `lavfi` 音视频验证生成计划、运行时门禁、基础 CLI 渲染、字幕真实排版与专属代理、音频 QA 和双流完整解码。合成媒体只存在于测试临时目录，不进入 Git。

校验剪辑计划：

```powershell
vlog-director validate-protection `
  --moments tests/fixtures/moments.json `
  --plan tests/fixtures/edit_plan.valid.json
```

退出码为 `0` 表示通过，`2` 表示存在阻止渲染的问题。

初始化一个仓库外的真实视频项目：

```powershell
.\scripts\init-project.ps1 `
  -ProjectsRoot D:\vlog-projects `
  -ProjectId family-trip
```

在 FFmpeg 渲染前执行保护检查：

```powershell
.\scripts\guard-render.ps1 `
  -ProjectPath D:\vlog-projects\family-trip `
  -Version 1
```

检查报告写入 `work\qa\protection.v1.json`。命令失败时必须停止渲染。

## 接入现有流水线

在生成 `edit_plan.json` 后、FFmpeg 渲染前调用校验器。真实视频、模型、缓存、Cookie、Token 和输出文件不得提交到 GitHub。

## GitHub 同步

当前电脑直接使用 Git 自带的 Credential Manager，不需要安装 GitHub CLI，也不要把 Personal Access Token 写入文件或发送给 Agent：

```powershell
git pull
git push
```

创建仓库、首次提交和推送前，先执行：

```powershell
.\scripts\check-environment.ps1
git status --short
git check-ignore -v .env reference-videos\sample.mp4 projects\demo\raw\private.mp4
```

家里电脑通过 `git clone` 获取代码，真实视频和模型继续保存在仓库外。

详细接入步骤见 `docs/home-integration.md`，后续改造顺序见 `docs/roadmap.md`。

成片增强的处理顺序、约束和命令见 `docs/enhancement-pipeline.md`。

## 字幕生产闭环

正式字幕流程已接入六个 CLI：

```text
project-subtitles
→ audit-subtitles
→ probe-subtitle-layout
→ render-subtitle-preview
→ qa-subtitles
→ approve-subtitles
```

字幕代理只烧录 ASS 并保留原音轨，不执行画面 treatment、音乐、ducking、overlay 或完整 enhancement render。`render-subtitle-preview` 和 `qa-subtitles` 默认提交可独立存活的 detached job；风险短代理支持按 cue、segment 或 chapter 输出，最终审批则要求 release readability、真实 libass layout、all-scope visual QA 和独立人工听校记录。

机器视觉 QA 不执行 OCR，也不会伪造人工通过状态。没有 OCR 时它只能准确说明：“已生成视觉帧和布局证据，文字准确性仍需人工听校。”preview 缺少真实布局只能 warning；release 缺少真实 libass 证据必须 blocker，且会绕过磁盘布局 cache 重新测量。完整目录约束、不可重放后台 job、状态检查、六个可复制 PowerShell 命令、人工审批和 `subtitle-ready-evidence-v1` 接入方式见 [字幕生产闭环](docs/subtitle-production-loop.md)。

## 参考片学习

安装本地分析依赖：

```powershell
python -m venv .venv-analysis
.\.venv-analysis\Scripts\python.exe -m pip install -e ".[analysis]"
```

生成逐镜头、事件、ASR 和声音分析，并输出事件抽查联系表：

```powershell
.\.venv-analysis\Scripts\vlog-director.exe analyze-reference `
  --input workspace\proxy.mp4 `
  --source-id bilibili-BV-example `
  --url https://www.bilibili.com/video/BV-example/ `
  --work-directory C:\tmp\bilibili-BV-example\learning-work `
  --review-directory C:\tmp\bilibili-BV-example\event-review `
  --output C:\tmp\bilibili-BV-example\analysis.full.json `
  --portable-output reference-learning\analysis.BV-example.json `
  --asr-provider faster-whisper `
  --asr-model small
```

生成受限 context packet，并在调用 `/responses` 前校验完整 JSON body：

```powershell
.\.venv-analysis\Scripts\vlog-director.exe pack-reference-context `
  --analysis workspace\analysis.full.json `
  --output workspace\reference-context.json `
  --max-characters 180000

.\.venv-analysis\Scripts\vlog-director.exe preflight-model-request `
  --request workspace\responses-request.json `
  --max-bytes 200000
```

Context packet 必须严格小于 180,000 字符。`--request` 文件必须已经是包含 `model`、`input` 以及实际使用的 `instructions`、`tools` 和其他协议字段的最终 Responses body；`preflight-model-request` 按文件的原始 UTF-8 字节（包括空白和换行）执行严格 `<200,000` 门禁，等于上限也会阻断，并输出绑定该 body 的 SHA-256。发送端必须逐字节发送与该摘要一致的文件，不能再由 SDK 包装或重新序列化。程序内调用应使用 `dispatch_responses_request`，让 transport 直接消费已经校验的紧凑 body bytes。中文等多字节文本不能只按 Python 字符数判断；UTF-8 BOM、缺少 Responses 基础结构、重复 JSON 字段、任意层级凭据字段和非有限 JSON 数值均会被拒绝。请求 JSON 只能放在 Git 忽略目录，不能写入 Cookie、Token 或 Authorization；若供应商限制更低，则通过 `--max-bytes` 使用更小门槛。命令返回 `ready` 只表示精确 body 字节门禁和最小 Responses 结构通过，不替代 OpenAI SDK 或上游 API 对不同 tool type 的完整 Schema 校验。

聚合多支参考片：

```powershell
.\.venv-analysis\Scripts\vlog-director.exe aggregate-reference `
  --analysis reference-learning\analysis.BV-a.json reference-learning\analysis.BV-b.json `
  --profile reference-learning\director-profile.BV-a.v2.json reference-learning\director-profile.BV-b.v2.json `
  --output reference-learning\director-profile.aggregate.json
```

十二份正式 Technique Study 聚合为可追踪技巧档案时，必须显式指定来源支持门槛：

```powershell
.\.venv-analysis\Scripts\vlog-director.exe aggregate-techniques `
  --study `
    reference-learning\technique-study.BV1C3546DEC6.v1.json `
    reference-learning\technique-study.BV1CrHwzUEJa.v1.json `
    reference-learning\technique-study.BV19sm2BBEDd.v1.json `
    reference-learning\technique-study.BV1ETNMzEEWQ.v1.json `
    reference-learning\technique-study.BV1aDHQejEAP.v1.json `
    reference-learning\technique-study.BV1TNZUB4EF6.v1.json `
    reference-learning\technique-study.BV15XMC6KETm.v1.json `
    reference-learning\technique-study.BV1a7Tj6nEe9.v1.json `
    reference-learning\technique-study.BV1TYVA6sEhm.v1.json `
    reference-learning\technique-study.BV1Mi536EELv.v1.json `
    reference-learning\technique-study.BV11Ao7BYEyv.v1.json `
    reference-learning\technique-study.BV1LS3r6gE7k.v1.json `
  --minimum-source-support 2 `
  --output reference-learning\reference-techniques.aggregate.v1.json
```

正式产物包含 12 个独立来源、42 条稳定模式和 57 条来源特定模式。聚合时保留每条模式的来源、观察编号、时间证据和 guardrails；不能把参考片绝对时间或自由格式参数直接套到目标素材。

Git 只保存 JSON 分析与规则。代理视频、模型缓存、逐帧图片和完整字幕保留在本地。

家庭电脑从安装、学习新视频到接入现有导演流水线的完整步骤见
`docs/reference-learning-home-guide.md`。

## 可执行导演流程

导演系统不会直接把推荐方案当成最终剪辑，也不会在缺少目标原片分析时复制旧时间线。

### 1. 分析目标原片并生成候选

先在视频管线项目中完成素材入库和逐字稿，再运行：

```powershell
.\scripts\direct-project.ps1 `
  -ProjectPath ..\firered-vlog-pipeline\projects\nordic-arrival `
  -ParentPlan ..\firered-vlog-pipeline\projects\nordic-arrival\work\plans\edit_plan.v1.json `
  -Profile .\reference-learning\director-profile.aggregate.v5.json `
  -TechniqueProfile .\reference-learning\reference-techniques.aggregate.v1.json `
  -Moments ..\firered-vlog-pipeline\projects\nordic-arrival\work\analysis\moments.json `
  -Version 2 `
  -TargetDurationSec 600
```

输出目录 `work/director/v2-proposal/` 包含三套候选 EDL、推荐方案、评分报告、目标语义视图与切点清单。状态是 `review_required`，不是完成。

`direct-project.ps1` 默认加载 `reference-techniques.aggregate.v1.json`。当前只有一个稳定模式具备自动执行器：`humor-preserve-real-awkward-process` 仅在目标镜头、事件或 optional moment 存在显式 `fun_score >= 0.55`、该证据让边缘镜头跨过选片阈值且最终通过预算拟合时，小幅提高真实尴尬过程的保留权重。它不会重排本来已入选的镜头，也不会覆盖用户 `remove/avoid` 或对已保护区间重复报功。`narrative-failure-adaptation-payoff` 在目标分析器具备真实语义标注前只作为 guidance。正式十二来源档案因此包含 1 条 executable pattern 和 98 条 guidance patterns；没有对应目标证据时 EDL 必须保持不变。

`director_report.json` 分开记录 `eligible_patterns`、真正改变候选的 `applied_patterns` 和 `guidance_patterns`；每条 applied trace 都包含目标证据及受影响区间。仅加载技巧档案不算已应用。

### 2. 人工批准候选

```powershell
.\scripts\approve-timeline.ps1 `
  -ProjectPath ..\firered-vlog-pipeline\projects\nordic-arrival `
  -Version 2 `
  -Candidate ..\firered-vlog-pipeline\projects\nordic-arrival\work\director\v2-proposal\candidate.balanced.json `
  -ApprovedBy "reviewer-name"
```

批准后会生成 `edit_plan.v2.json` 和绑定内容哈希的凭证。EDL 再被修改时，渲染门禁会要求重新批准。

### 3. 从原片重剪并审查切点

在 `firered-vlog-pipeline` 运行 `scripts/render-directed.ps1`。不要把旧基础 MP4 传给增强器冒充新剪辑。

## 设计边界

- Video Use 仅借鉴“紧凑语义视图 → EDL → 渲染后逐切点自检”，不作为架构依赖。
- 参考片是评分先验，不是目标素材；缺少目标原片分析或完整对白转录时直接阻断。
- 自动评分只能推荐，不能代替人工确认故事语义、对白完整性和视觉连续性。
- HyperFrames 属于效果层，不参与镜头选择或时间线审批。
## 配乐参考单

导演系统在画面时间线完成后，只输出非阻断的配乐参考：建议时间段、情绪与节奏、剪映搜索关键词、音量参考和淡入淡出方式。它不自动选歌、不自动混音、不影响画面版本发布；用户在剪映中自行搜索和试听。

```powershell
vlog-director plan-music --plan edit_plan.v2.json --profile director-profile.aggregate.v5.json --subtitles subtitles.review.v2.json --dialogue-padding-sec 0.35 --output music_reference.v2.json
```

参考单会避开已知字幕对白区间，但实际添加时仍需试听，优先保留现场对白和环境声。HyperFrames 仍只属于视觉效果层，不参与配乐点位决策。

## 导演学习闭环

导演学习不再把所有参考视频平均成一条万能规则，而是分为四层：

1. **内容记忆**：美景和趣味分别评分；趣味按 `setup → trigger → payoff → reaction` 事件链判断。
2. **剪辑记忆**：三套候选分别偏向趣味、平衡和美景，必须真实改变目标原片 EDL。
3. **效果记忆**：贴图和动效只能在高置信趣味事件之后建议，默认非阻断；具体风格等待用户参考视频，不提前写死。
4. **反馈记忆**：人工的保留、删除、恢复、延长、缩短和锁定决定优先于参考片先验。

固定优先级为：**显式用户反馈 > 目标原片证据 > 多参考片共同模式 > 单一参考片模式**。参考成片只能提供正向保留模式；没有原片、成片与 EDL 映射时，不推断真实删片偏好。

镜头角色先验档案为 `reference-learning/director-profile.aggregate.v5.json`。它修正了“11 支视频的人工总结只算 1 份证据”的问题，按独立参考视频 ID 去重统计支持度。十二支正式 Study 的技巧档案为 `reference-learning/reference-techniques.aggregate.v1.json`；两个档案职责不同，导演流程会同时加载。

如需让下一版吸收人工修改，复制 `reference-learning/feedback.example.json`，填写镜头决定后运行：

```powershell
.\scripts\direct-project.ps1 `
  -ProjectPath ..\firered-vlog-pipeline\projects\nordic-arrival `
  -ParentPlan ..\firered-vlog-pipeline\projects\nordic-arrival\work\plans\edit_plan.v1.json `
  -Profile .\reference-learning\director-profile.aggregate.v5.json `
  -TechniqueProfile .\reference-learning\reference-techniques.aggregate.v1.json `
  -Moments ..\firered-vlog-pipeline\projects\nordic-arrival\work\analysis\moments.json `
  -Feedback .\reference-learning\feedback.my-project.v1.json `
  -Version 2 `
  -TargetDurationSec 600
```
