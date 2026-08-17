# 逐段画面美化生产闭环

这条流水线只改变已批准片段的像素表现，不改变镜头选择、顺序或 realized timeline 时长。音乐固定为 `disabled`，最终输出保留原始对白和环境声，配乐由用户在剪映中完成。

## 正式顺序

```text
approved edit plan + realized timeline + directed base
→ analyze-visual-segments
→ plan-visual-treatments
→ render-treatment-preview
→ qa-visual-treatments
→ 人工逐段复核
→ approve-visual-treatments
→ apply-visual-treatments
→ guard-enhancement --mode release
→ render-enhancement --mode release
```

正式产物使用双份一致的 JSON Schema。分析、代理、QA 和审批都绑定 edit plan、realized timeline、base media、FFmpeg 和文件 SHA-256；任何输入或建议参数变化都会使旧证据失效。

## 支持范围

Planner 第一版只会提出 renderer 已真实执行的保守参数：

- brightness、contrast、saturation；
- 有低运动和测量证据时的 `hqdn3d` 轻度降噪；
- 有低运动、低噪声和低细节证据时的 `unsharp` 轻度锐化。

执行器仍支持 exposure、gamma 和 RGB white balance，但当前自动 planner 不会在缺少可靠中性参照时猜测白平衡。没有真实保护区域时绝不自动 reframe/crop。逐段防抖、crossfade、dip-to-black、match action 和 speed 不属于本闭环，继续 fail closed。

## PowerShell 示例

```powershell
$project = (Resolve-Path '..\video-projects\family-trip').Path
$python = (Resolve-Path '.\.venv-analysis\Scripts\python.exe').Path
$env:PYTHONPATH = (Resolve-Path '.\src').Path
$ffmpeg = & $python -c "from imageio_ffmpeg import get_ffmpeg_exe; print(get_ffmpeg_exe())"

& $python -m vlog_director.cli analyze-visual-segments `
  --project $project `
  --base-video "$project\output\directed.v3.mp4" `
  --edit-plan "$project\work\plans\edit_plan.v3.json" `
  --realized-timeline "$project\work\qa\realized.v3.json" `
  --output "$project\work\analysis\visual\analysis.v3.json" `
  --ffmpeg-executable $ffmpeg `
  --detached

& $python -m vlog_director.cli plan-visual-treatments `
  --project $project `
  --edit-plan "$project\work\plans\edit_plan.v3.json" `
  --analysis "$project\work\analysis\visual\analysis.v3.json" `
  --output "$project\work\treatments\visual-treatment-plan.v3.json"

& $python -m vlog_director.cli render-treatment-preview `
  --project $project `
  --base-video "$project\output\directed.v3.mp4" `
  --plan "$project\work\treatments\visual-treatment-plan.v3.json" `
  --realized-timeline "$project\work\qa\realized.v3.json" `
  --output-directory "$project\work\proxy\treatments\preview-v3-001" `
  --ffmpeg-executable $ffmpeg `
  --detached

& $python -m vlog_director.cli qa-visual-treatments `
  --project $project `
  --plan "$project\work\treatments\visual-treatment-plan.v3.json" `
  --preview-manifest "$project\work\proxy\treatments\preview-v3-001\preview-manifest.json" `
  --output-directory "$project\work\qa\treatments\qa-v3-001" `
  --ffmpeg-executable $ffmpeg `
  --detached
```

Detached 命令会在 `work/jobs/<operation>/<unique-id>/` 写入 `job.json`、`status.json` 和 worker log。必须查看 terminal status、真实产物和退出信息，不能只凭 PID 存在判断成功。

## 人工复核与批准

`qa-visual-treatments` 为每个 proposal 生成 entry、middle、exit 三帧，并检查完整解码、黑帧、疑似冻结和时长偏差。机器结论固定为：

> 已生成视觉帧和技术证据，画面审美适配性仍需人工检查。

人工 review 必须符合 `visual-treatment-human-review.schema.json`，逐 proposal 检查 `exposure`、`color`、`detail` 和 `composition`，可以接受或拒绝每条建议。系统不会伪造人工通过状态。

```powershell
& $python -m vlog_director.cli approve-visual-treatments `
  --project $project `
  --plan "$project\work\treatments\visual-treatment-plan.v3.json" `
  --preview-manifest "$project\work\proxy\treatments\preview-v3-001\preview-manifest.json" `
  --visual-qa "$project\work\qa\treatments\qa-v3-001\visual-qa.json" `
  --human-review "$project\work\qa\treatments\qa-v3-001\human-review.json" `
  --output "$project\work\qa\treatments\qa-v3-001\approval.json"

& $python -m vlog_director.cli apply-visual-treatments `
  --project $project `
  --enhancement-plan "$project\work\enhancement\enhancement_plan.v3.json" `
  --plan "$project\work\treatments\visual-treatment-plan.v3.json" `
  --preview-manifest "$project\work\proxy\treatments\preview-v3-001\preview-manifest.json" `
  --visual-qa "$project\work\qa\treatments\qa-v3-001\visual-qa.json" `
  --human-review "$project\work\qa\treatments\qa-v3-001\human-review.json" `
  --approval "$project\work\qa\treatments\qa-v3-001\approval.json" `
  --output "$project\work\enhancement\enhancement_plan.v4.json"
```

`apply-visual-treatments` 只生成下一版本，不覆盖旧计划，并强制写入 `music.status=disabled`、空 tracks 和关闭 ducking。release guard 对存在像素处理但缺少当前 approval evidence 的计划 fail closed。

## 保护区域与动效

`visual-protected-regions.schema.json` 统一描述 `face`、`main_subject`、`subtitle` 和 `critical_text_logo` 的时段 bbox。分析和动效 QA 会校验 base media SHA、provider 输入 SHA 和实际画布；没有这些证据时 analyzer 明确记录 warning，自动 reframe 保持关闭。

叙事型 HyperFrames 支持 `time_jump_card`、`location_card`、`route_map`、`step_card` 和 `source_card`。它们只从显式 `effect_hint` 生成，且要求 `fact_check_status=verified`、可追踪 `source_reference` 以及 `owned|licensed|public_domain` 版权状态；不满足条件时不会编译为动效。

代理视频、抽帧、日志和分析中间文件属于本地项目产物，不得提交到代码仓库。
