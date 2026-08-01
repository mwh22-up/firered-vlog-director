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

## 已实现的本地执行器

- `scripts/stabilize.ps1`：通过 `vidstabdetect` + `vidstabtransform` 两遍防抖；
- `scripts/render-enhancement.ps1`：对白 `loudnorm`、配乐侧链 ducking、静态插画 overlay、ASS 字幕和最终编码；
- 最终渲染前自动执行高光保护门禁和增强计划门禁。

```powershell
.\scripts\render-enhancement.ps1 `
  -ProjectPath D:\vlog-projects\family-trip `
  -Version 1
```

当前 `render-enhancement` 以已完成基础剪辑的 `output/preview.mp4` 为输入。逐片段防抖完成后，应由家里的现有粗剪流水线重新生成该预览，再执行最终增强。
