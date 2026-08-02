# Nordic GX010130–GX010144 research handoff

这是 2026-08-02 在家里电脑完成的可迁移研究包。它保存本批素材的完整分析、导演决策、版本化剪辑方案、人工复核证据、QA，以及可直接播放或继续增强的成片。

## 当前结果

- 素材范围：`GX010130.MP4` 至 `GX010144.MP4`，15/15。
- 原片合计：56:36.970。
- 完整代理解码、完整 ASR、镜头/事件/音频分析：15/15 ready，0 failure。
- 正式剪辑：v3，44 段，43 个真实切点。
- 计划时长：865.58 秒；source 实际时长：868.3114 秒（14:28.3）。
- Protection：passed，0 blocking，0 warning。
- Cut QA：43 个切点，0 flagged；v2 全量人工复核，v3 改动切点再次按 source 帧复核。
- Enhancement gate：passed，0 blocking，0 warning。
- Audio QA：passed，-16.7 LUFS，True Peak -1.2 dBFS。
- 最终片没有烧入字幕、配乐或贴图，避免未经听校的错字和乱码。

## 媒体（Git LFS）

- `media/final.v3.mp4`：当前正式 1080p 成片；已做响度标准化。
- `media/directed.v3.mp4`：无二次增强的 1080p 基础剪辑；明天继续美化、字幕和动效时优先以它为 base video。
- `media/preview.v3.mp4`：v3 轻量代理预览。
- `media/preview.v2.mp4`：v2 对照代理，用于研究 v2→v3 的人工收紧。

这些文件由 Git LFS 管理。公司电脑首次拉取后必须确认它们不是几百字节的 LFS pointer：

```powershell
git lfs install
git lfs pull --include="research-artifacts/nordic-130-144/media/*"
Get-ChildItem research-artifacts\nordic-130-144\media
```

## 研究文件

- `project/work/director/target-analysis/`：15 支素材完整 ASR、镜头、事件与音频分析。
- `project/work/analysis/moments.json`：39 个 moments 与 6 条 setup→payoff→reaction 事件链，已按最终人工复核边界更新。
- `project/work/director/v2-proposal/`：自动 Director 候选、报告、语义视图及人工候选。
- `project/work/director/v3-proposal/`：最终人工收紧候选。
- `project/work/plans/`：v1、v2、v3 计划和批准凭证。
- `project/work/qa/`：Plan、Protection、render、cut、enhancement、audio QA 和真实切点帧。
- `project/work/enhancement/`：当前 enhancement plan；字幕、音乐、贴图均为空。
- `project/work/thumbnails/`：素材缩略图。
- `review/`：联系表、边界源帧及 v2/v3 人工复核图。
- `RESEARCH-NOTES.md`：完整导演思路、版本演进、能力边界和下一步。
- `RESUME-PROMPT.md`：公司电脑可直接粘贴的续接提示词。
- `MANIFEST.sha256`：研究包全部文件的 SHA-256 清单（不包含清单自身）。

## 没有上传的内容

- 原始 `GX010130–GX010144` 媒体。
- `work/proxy/` 的 15 个可重建素材代理。
- `work/render/` 的逐段转码缓存。
- `output/chapters/` 的可重建章节中间成片。
- cookies、Token、凭据、模型和缓存。

以上内容若全部上传会再增加约 2.6 GB，且对继续分析没有必要。需要从原片重剪时，在公司电脑重新指定原始素材目录并运行 ingest；继续字幕/美化则可以直接使用 LFS 中的 `directed.v3.mp4`。

## 路径可移植性

历史报告中的本地路径已替换为：

- `${PROJECT_ROOT}`：在新电脑上放置项目的目录。
- `${RAW_MEDIA_ROOT}`：在新电脑上保存 GX 原片的目录。

这些替换只影响历史报告中的路径字段，不改变计划时间码、批准哈希或分析证据。