# 行业实现调研与技术选择

本项目优先采用成熟项目验证过的处理方式，而不是自行发明媒体算法。

## 字幕

WhisperX 在 Whisper/faster-whisper 之上加入 VAD、词级强制对齐和可选说话人分离。项目采用其处理思路：先得到词级时间戳，再按语义和停顿合并字幕，最后输出 ASS，由 FFmpeg 的 `subtitles`/libass 滤镜烧录。

首版不强制安装 WhisperX，因为它涉及 PyTorch、对齐模型和可选 Hugging Face 模型。家里环境完成模型验证后，再作为独立可选依赖接入。

## 防抖

vid.stab 官方明确要求 FFmpeg 使用两遍模式：第一遍 `vidstabdetect` 生成变换文件，第二遍 `vidstabtransform` 应用变换。项目按这一方式实现，并限制最大裁切，避免为了稳定画面而严重裁脸。

## 配乐和对白

FFmpeg 提供 `loudnorm` 和 `sidechaincompress`。项目先统一对白响度，再把对白作为 sidechain 压低音乐，避免简单固定音量导致轻声对白被盖住。

## 镜头边界和连贯性

PySceneDetect 的 ContentDetector/AdaptiveDetector 是成熟的镜头切分方案；后续自动连贯性分析将使用镜头边界而不是固定秒数采样。转场仍以硬切优先，只有章节或时空变化才使用淡化。

## 时间轴

OpenTimelineIO 的成熟边界是保存剪辑顺序、长度和外部媒体引用，而不承载媒体本身。本项目沿用这个边界：`edit_plan` 和 `enhancement_plan` 只引用本地媒体，真实视频不进入代码仓库。

## 插画动效

首版使用 FFmpeg overlay 完成透明位图、贴纸、地图和标题卡。Remotion 适合数据驱动、React 组件化的复杂动画，但会引入 Node/Chromium 渲染链路；待简单 overlay 稳定后再作为高级执行器接入，而不是替换基础 FFmpeg 渲染。

## 一手来源

- FFmpeg Filters Documentation: https://ffmpeg.org/ffmpeg-filters.html
- WhisperX: https://github.com/m-bain/whisperX
- vid.stab: https://github.com/georgmartius/vid.stab
- PySceneDetect: https://github.com/Breakthrough/PySceneDetect
- OpenTimelineIO: https://github.com/AcademySoftwareFoundation/OpenTimelineIO
- Remotion: https://github.com/remotion-dev/remotion
