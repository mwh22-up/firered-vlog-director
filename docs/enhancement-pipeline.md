# 成片增强流水线

`edit_plan.json` 决定镜头选择和故事顺序，`enhancement_plan.json` 决定如何处理这些镜头。增强阶段不得删除、缩短或重排导演计划中的片段。

## 固定渲染顺序

```text
单镜头防抖与重新构图
→ 连贯性拼接和转场
→ 对白响度归一
→ 配乐与对白自动避让
→ 插画、贴纸、地图和标题动效
→ 字幕作为最上层可读信息
→ 最终编码与质量检查
```

## 四项能力

### 配乐

- 由导演按章节情绪选择音乐，不按整片随机铺一首歌；
- 现场对白出现时必须自动 ducking，默认使用 `threshold=0.125`、`ratio=8:1`、`attack=20 ms`、`release=250 ms`；
- 音乐切换优先对齐章节、情绪转折和节拍，不截断重要对白；
- 音乐文件存入项目的 `assets/music/`，不进入代码仓库。

### 连贯与防抖

- 防抖先在每个源片段上处理，再进行拼接；
- 默认 `auto`，最大裁切 8%，硬上限 15%；
- 人脸、主体或字幕安全区被裁切时应降低强度或关闭；
- 连贯性通过动作方向、人物位置、时间和环境音判断；普通硬切优先，转场只在章节或时空变化时使用。

### 字幕

- Whisper 生成词级时间戳，再按完整语义和停顿合并；
- 每条最多两行，避免逐字跳动和过长整句；
- 字幕位于安全区，并在插画动效之后渲染，确保始终可读；
- 对白保留原文，口误是否修正由用户策略决定。

### 插画动效

- 只服务于地点、时间、人物关系、解释和笑点强化；
- 类型包括插画、贴纸、标注、地图和标题卡；
- 使用本地透明 PNG/WebP、短视频或后续生成的位图资产；
- 默认避开字幕区和人物脸部，不用动效掩盖无内容镜头。

## 使用方式

在已有 `edit_plan.v1.json` 的项目中运行：

```powershell
.\scripts\init-enhancement.ps1 `
  -ProjectPath D:\vlog-projects\family-trip `
  -Version 1
```

编辑生成的 `work/enhancement/enhancement_plan.v1.json` 后，最终渲染前运行：

```powershell
.\scripts\guard-enhancement.ps1 `
  -ProjectPath D:\vlog-projects\family-trip `
  -Version 1
```

## 真实 smoke gate

提交增强渲染改动前，运行可移植 smoke gate：

```powershell
$python = (Resolve-Path .\.venv-test\Scripts\python.exe).Path
$ffmpeg = & $python -c "from imageio_ffmpeg import get_ffmpeg_exe; print(get_ffmpeg_exe())"
.\scripts\smoke-render.ps1 `
  -PythonExecutable $python `
  -FFmpegExecutable $ffmpeg
```

`-FFmpegExecutable` 可省略；脚本会通过所选 Python 的 `imageio_ffmpeg` 查找 bundled FFmpeg，而不依赖系统 `PATH`。脚本先检查同一 FFmpeg 的 filter 清单：核心 filter 缺失时立即失败，字幕、贴图和防抖等可选能力只在实际可用时启用，否则输出明确的跳过信息。

smoke 数据只写入唯一的系统临时目录，结束时自动清理。门禁覆盖正式及运行时 enhancement plan Schema、真实增强渲染、audio QA，以及用同一 FFmpeg 强制映射视频流和音频流后的完整解码；不依赖 `ffprobe`。

## 已实现的本地执行器

- `scripts/stabilize.ps1`：提供整支输入的独立两遍防抖工具；它不代表逐段 enhancement treatment 已执行；
- `scripts/render-enhancement.ps1`：逐段画面/原声 treatment、对白 `loudnorm`、配乐侧链 ducking、静态插画 overlay、ASS 字幕和最终编码；
- 最终渲染前自动执行高光保护门禁和增强计划门禁。

```powershell
.\scripts\render-enhancement.ps1 `
  -ProjectPath D:\vlog-projects\family-trip `
  -Version 1
```

当前 `render-enhancement` 以已完成基础剪辑的 `output/preview.mp4` 为输入。存在逐段非中性 treatment 时，必须同时提供实际编码边界：

```powershell
python -m vlog_director.cli render-enhancement `
  --project D:\vlog-projects\family-trip `
  --base-video D:\vlog-projects\family-trip\output\directed.v3.mp4 `
  --plan D:\vlog-projects\family-trip\work\enhancement\enhancement_plan.v3.json `
  --realized-timeline D:\vlog-projects\family-trip\work\qa\render.v3.json `
  --output D:\vlog-projects\family-trip\output\final.v4.mp4
```

若省略 `--realized-timeline`，CLI 会查找 `work/qa/render.v<edit_plan_version>.json`。render report 的 `cut_boundaries.actual_time_sec` 是基础剪辑中的权威切点；计划时长不能替代实际编码时长。

逐段执行器支持：

- `exposure_ev`、`brightness`、`contrast`、`saturation`、`gamma` 和 RGB white-balance shift；
- `hqdn3d` 轻度降噪、`unsharp` 锐化，以及保持原宽高比并缩放回输出画布的 crop/reframe；
- 原声 `gain_db`、mute/preserve，以及全片一致的 dialogue normalization 决策；
- 基于实际边界的 `trim/atrim`、时长补齐和硬切 concat，滤镜脚本写入系统临时目录并在渲染后清理。

当前逐段防抖 `auto/force`、非硬切 transition、`match_action=true` 和非 `1.0` speed 尚未形成可靠的确定性实现，运行时会在启动 FFmpeg 前明确阻断。`stabilization.mode=off` 必须使用 `strength=0`、`max_crop_percent=0`。
