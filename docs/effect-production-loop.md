# HyperFrames 大胆动效生产闭环

这条流水线把导演系统给出的效果意图变成可复核、可追溯的透明视频图层。HyperFrames 只负责效果层，不改变选片、镜头顺序或时间线时长，也不代替剪辑师判断效果是否合适。

## 视觉方向

内置 `firecut-bold-v1` 不是小面积装饰，而是高能编辑视觉：超大字、硬边几何、径向爆发、明显 overshoot，以及橙红、亮黄、青色三组高对比色。默认强度为 `0.88`，同时保留以下硬约束：

- 每个事件最多一个 primary effect，避免所有镜头同时抢戏。
- 总效果覆盖率不超过时间线的 35%，相邻效果至少保留 0.25 秒呼吸间隔。
- 效果必须落在目标 segment 内，不能改变 realized timeline 时长。
- 人脸、主体和字幕安全区是受保护区域。
- 只有目标片段的真实 story role、章节标题或显式 `effect_hint` 能触发效果。

首批四种 recipe：

| Recipe | 用途 | 视觉动作 |
|---|---|---|
| `impact_hit` | 开场撞击、节奏重拍 | 径向闪形、双环扩散、中心撞击符号 |
| `kinetic_explain` | 解释重点、信息转折 | 大字卡片横向冲入、过冲回弹、强调线展开 |
| `place_reveal` | 地点或章节切换 | 全屏色块、对向斜杠、海报式大标题 |
| `reaction_burst` | reaction/payoff | 放射爆发、徽章弹跳、圆环冲击 |

## 固定运行时

- package：`hyperframes`
- version：`0.7.90`
- Node.js：22 或更高
- 输出：带 alpha 的 ProRes 4444 MOV
- 动画：离线 WAAPI，可逐帧随机 seek；不使用 CDN、网络资源、随机数或 wall clock

`render-effects --hyperframes-executable npx` 会在不经过 shell 拼接的前提下调用固定的 `npx --yes hyperframes@0.7.90`，随后再次核对 CLI 返回版本。也可传入已安装的 `hyperframes` 或其绝对可执行文件路径；版本不是 `0.7.90` 时会阻断。

## 正式顺序

```text
已批准的 edit plan
→ plan-effects
→ compose-effects
→ HyperFrames strict check + transparent MOV
→ qa-effects
→ 人工逐项检查
→ approve-effects
→ apply-effects
→ guard-enhancement --mode release
→ render-enhancement --mode release
```

PowerShell 示例：

```powershell
$project = (Resolve-Path '..\video-projects\family-trip').Path
$python = (Resolve-Path '.\.venv-test\Scripts\python.exe').Path
$env:PYTHONPATH = (Resolve-Path '.\src').Path
$ffmpeg = & $python -c "from imageio_ffmpeg import get_ffmpeg_exe; print(get_ffmpeg_exe())"

& $python -m vlog_director.cli plan-effects `
  --project $project `
  --version 3 `
  --style-pack firecut-bold-v1

& $python -m vlog_director.cli compose-effects `
  --project $project `
  --plan "$project\work\effects\effect_plan.v3.json" `
  --output-directory "$project\work\effects\hf-v3-001" `
  --canvas-width 1920 `
  --canvas-height 1080

& $python -m vlog_director.cli render-effects `
  --project $project `
  --plan "$project\work\effects\effect_plan.v3.json" `
  --composition-manifest "$project\work\effects\hf-v3-001\composition-manifest.json" `
  --hyperframes-executable npx `
  --quality standard

& $python -m vlog_director.cli qa-effects `
  --project $project `
  --plan "$project\work\effects\effect_plan.v3.json" `
  --render-manifest "$project\work\effects\hf-v3-001\render-manifest.json" `
  --base-video "$project\output\directed.v3.mp4" `
  --output-directory "$project\work\qa\effects\qa-v3-001" `
  --ffmpeg-executable $ffmpeg
```

`qa-effects` 会把真实基础剪辑与透明 MOV 合成短代理，完整解码代理，并为每个效果生成 entry、peak、exit 三帧。机器只检查解码、时长和几何，human review 始终保持 `pending`，结论只能是：

> 已生成视觉帧和布局证据，效果适配性仍需人工检查。

这不代表机器已经判断节奏、审美、主体遮挡或“够不够大胆”。

## 人工复核与批准

剪辑师必须针对每个 `effect_id` 查看短代理和三帧证据，确认：

- `timing`：入场、峰值、退场是否踩在正确事件上；
- `safe_zones`：没有不可接受地遮挡脸、主体或字幕；
- `visual_fit`：视觉语言与本章内容匹配；
- `intensity`：强度应保留、加强还是减弱。

Human review 是独立正式产物，必须符合 `effect-human-review.schema.json`，绑定 effect plan、render manifest、visual QA 和 base media 的真实 SHA。只有真实完成复核后才能写 `status: approved` 和固定 attestation；不得由程序伪造人工通过。

```powershell
& $python -m vlog_director.cli approve-effects `
  --project $project `
  --plan "$project\work\effects\effect_plan.v3.json" `
  --render-manifest "$project\work\effects\hf-v3-001\render-manifest.json" `
  --visual-qa "$project\work\qa\effects\qa-v3-001\visual-qa.json" `
  --human-review "$project\work\qa\effects\human-review.v3.json" `
  --output "$project\work\qa\effects\approval.v3.json"

& $python -m vlog_director.cli apply-effects `
  --project $project `
  --enhancement-plan "$project\work\enhancement\enhancement_plan.v3.json" `
  --plan "$project\work\effects\effect_plan.v3.json" `
  --render-manifest "$project\work\effects\hf-v3-001\render-manifest.json" `
  --visual-qa "$project\work\qa\effects\qa-v3-001\visual-qa.json" `
  --human-review "$project\work\qa\effects\human-review.v3.json" `
  --approval "$project\work\qa\effects\approval.v3.json" `
  --output "$project\work\enhancement\enhancement_plan.v4.json"
```

`apply-effects` 不会修改旧 enhancement plan，而是创建下一版本，并把批准的透明 MOV 作为 `type=hyperframes`、`media_kind=transparent_video` 的 overlay 写入。正式 renderer 会按 timeline offset 合成，效果结束后不冻结尾帧。

## 失效规则

以下任一变化都会使 approval 失效并要求重新生成证据、重新人工复核：

- edit plan、时间线或目标 segment；
- effect plan、recipe、文字、位置、时长、样式包或强度；
- composition HTML、HyperFrames 版本或透明 MOV；
- base media、合成预览、entry/peak/exit 帧；
- render manifest、visual QA 或 human review 文件。

手工把 enhancement、review 或 approval 状态改成 `ready`/`approved` 不能绕过这些 SHA 校验。

## 目录与不可覆盖约束

- composition job 必须是 `work/effects/<unique-id>`，且目录必须全新。
- QA job 必须位于 `work/qa` 的严格子目录。
- 已存在的 composition manifest、render manifest、MOV、预览或证据不会被覆盖。
- 透明 MOV、短代理、抽帧、日志和缓存都是本地项目产物，不得提交到代码仓库。

真实 smoke 已覆盖固定版本 strict check、Windows `npx.cmd` 解析、逐帧 seek 渲染、ProRes 4444 alpha、640×360、FFmpeg 完整解码、基础剪辑合成代理和 entry/peak/exit 三帧。最新预算样例为 0.42 秒效果叠加到 1.20 秒纯合成基础剪辑；它不代表某个真实项目已通过人工审美审批。
