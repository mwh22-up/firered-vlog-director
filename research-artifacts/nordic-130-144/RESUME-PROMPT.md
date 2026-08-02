# 明天公司电脑续接提示词

请继续完善 `firered-vlog-director` 的 GX010130–GX010144 旅行 Vlog。不要只给方案，直接检查、实现、验证、独立提交并推送；除非真实阻塞，否则持续工作。

仓库与分支：

- 仓库：`https://github.com/mwh22-up/firered-vlog-director.git`
- 分支：`feature/director-learning-loop`
- 交付目录：`research-artifacts/nordic-130-144/`

开始时：

1. 检查工作区并保留已有改动。
2. `git fetch`，然后 `git pull --ff-only`。
3. 确认 Git LFS 已安装并执行：
   `git lfs pull --include="research-artifacts/nordic-130-144/media/*"`
4. 检查 `media/final.v3.mp4` 约 1.07 GB、`directed.v3.mp4` 约 657 MB；若只有几百字节，说明 LFS 尚未拉取成功。
5. 阅读：
   - `research-artifacts/nordic-130-144/README.md`
   - `research-artifacts/nordic-130-144/RESEARCH-NOTES.md`
   - `research-artifacts/nordic-130-144/project/work/analysis/moments.json`
   - `research-artifacts/nordic-130-144/project/work/plans/edit_plan.v3.json`
   - `research-artifacts/nordic-130-144/project/work/enhancement/enhancement_plan.v3.json`
   - `reference-learning/director-profile.aggregate.v5.json`
   - `reference-learning/reference-techniques.aggregate.v1.json`
   - `src/vlog_director/enhancement.py`
   - `src/vlog_director/renderers.py`

当前基线：

- 15/15 完整 ASR、镜头、音频和事件分析 ready。
- v3 为正式基础剪辑：44 段，实际 14:28.3。
- 43 个 source 实际切点自动 0 flagged，并已人工复核。
- Protection、Enhancement、Audio QA 全部 passed。
- `final.v3.mp4` 为当前可交付版：-16.7 LUFS、-1.2 dBFS。
- 当前没有字幕、音乐或贴图。
- 所有绝对路径已替换为 `${PROJECT_ROOT}` / `${RAW_MEDIA_ROOT}`。

下一项只做一个闭环增量：

为 v3 制作“自然旅行 Vlog”美化、字幕和轻动效的 30–60 秒真实样片，不要直接全片重编码。

要求：

1. 以 `media/directed.v3.mp4` 为 base video；不要从已二次编码的 `final.v3.mp4` 再加工。
2. 先审计并实现主 enhancement renderer 对逐段 `video_treatments` 的真实执行，至少明确 stabilization、continuity、per-segment audio 哪些已支持、哪些必须阻断。
3. 补齐字幕 `position`、`max_lines`、`safe_margin_percent` 到真实 ASS/FFmpeg 布局的映射和测试。
4. overlay 若加入样片，必须实现可验证的入场/退场动画；不要只写计划字段。
5. 从完整 ASR 映射样片字幕，但每条 cue 必须逐条听校后才标 `review_status=verified`；不得直接烧入原始 ASR。
6. UTF-8 无 BOM，验证中文不乱码。
7. 视觉采用轻量分段策略：雪地/瀑布保持冷色干净，人物肤色不过度偏蓝，列车内避免过饱和；不要套全片强 LUT。
8. 动效仅用于章节标题、地点信息或有证据的笑点，不堆贴纸。
9. 先产出短样片，完成完整音视频双流解码、字幕安全区截图、响度和 True Peak QA。
10. 通过后独立提交并推送；媒体样片继续使用 Git LFS，禁止普通 Git 大文件。

后续再做：

- 全片字幕逐条听校。
- 全片逐段 video treatments。
- 全片 overlay 动画。
- 正式选曲、ducking 和最终混音。