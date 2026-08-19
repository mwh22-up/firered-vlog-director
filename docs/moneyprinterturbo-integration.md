# MoneyPrinterTurbo 集成与优化建议

更新时间：2026-08-19

## 结论

MoneyPrinterTurbo（MPT）适合负责“主题/脚本 -> 旁白 -> B-roll -> 字幕 -> 短视频包装”的前半段；FireRed Pipeline + Director 继续负责长素材分析、参考片学习、镜头级 EDL、候选预览、人工审批、真实切点 QA 和发布门禁。

采用窄桥接，不复制 MPT 整套应用，也不让 MPT 的 `final-*.mp4` 直接进入发布链路。MPT 只产出待验收资产包，Pipeline 重新入库并计算 SHA，Director 决定镜头与叙事。

## 基线

- MPT：`https://github.com/harry0703/MoneyPrinterTurbo`，`main`，`c57f3c600e0b5d8886c025a56b44e364588c9632`。
- Pipeline：`feature/director-learning-loop`，`78388cc`，`39 passed`。
- Director：`feature/director-learning-loop`，`91e7f86`；`311 passed / 1 skipped`。跨仓库契约测试在兼容环境 `2 passed`。
- MPT 本轮只做源码审计，未调用真实 LLM、TTS 或素材 API。

## 本轮实际完成内容

1. 将 MoneyPrinterTurbo 拉取到同级工作区，恢复首次 clone 超时留下的仓库，并用浅抓取完成 `main` 工作树。
2. 核对 MPT 远端、HEAD、工作树和 Git 对象：远端为官方仓库，HEAD 为 `c57f3c6`，工作树干净，对象校验通过。
3. 阅读 MPT 的 CLI、FastAPI、任务编排、脚本生成、TTS、字幕、在线素材、MoviePy 合成、任务状态、TwelveLabs 和跨平台发布实现。
4. 阅读 Pipeline 的 ingest、edit plan、candidate preview、FFmpeg render、cut QA、subtitle gate 和 Director guard。
5. 阅读 Director 的 moments、reference learning、candidate EDL、preview selection、enhancement、字幕/动效 QA、人工审批和 release gate。
6. 对比三者的真实数据流和边界，确认 MPT 适合作为创作资产供应器，不适合替换 FireRed 的导演决策与正式渲染链。
7. 运行 Pipeline 全量测试，结果为 `39 passed`。
8. 运行 Director 全量测试：共 314 项，311 通过、1 跳过；2 项因 Director venv 缺少 Pipeline 的 `PyYAML` 导入失败。
9. 使用包含兼容依赖的 Pipeline 环境重跑上述 2 个跨仓库契约测试，结果为 `2 passed`，确认是环境依赖问题而非契约回归。
10. 设计 `generated-asset-pack.v1`、`creative_mode`、共享 `vlog-contracts` 和 release 后发布状态的分阶段方案。
11. 未修改 MPT、Pipeline 或 Director 的生产代码；本轮只新增此分析文档。
12. 曾误将分析发布到 Rooter Note。当前 Rooter 工具明确不提供 delete 权限，因此无法从本地自动删除该页面；后续此项目文档只维护在 Git。

## 能力映射

| MPT 能力 | 接入位置 | 约束 |
| --- | --- | --- |
| 多 LLM、脚本候选 | Director 计划前 | 只产候选脚本，不直接改 EDL；保留模型、prompt、候选编号和 SHA |
| 多种 TTS | narrated/hybrid 旁白阶段 | 音频入库、探测时长、SHA，并进入听审 |
| Edge/Whisper 字幕 | 字幕初稿 | 继续走 source-audio 听校、可读性、layout、visual QA 和 approval |
| Pexels/Pixabay/Coverr/本地素材 | B-roll 供应器 | 重新走 Pipeline ingest，补来源页、asset id、授权状态和 SHA |
| TwelveLabs 重排/分析 | B-roll 初筛 | 只提供 evidence/score，不绕过 Director 复核 |
| MoviePy 固定时长拼接 | 草稿/proxy | 不替换 FFmpeg directed renderer |
| 社媒 metadata / Upload-Post | release 后台 | 绑定 release approval 和成片 SHA |

## 推荐数据流

```text
creative_brief.v1
 -> MPT bridge（script / voice / stock candidates）
 -> generated-asset-pack.v1
 -> Pipeline ingest（proxy、metadata、SHA、来源）
 -> Director candidate EDL + preview + cut QA
 -> human approval -> source render -> release approval
 -> optional social metadata / cross-post
```

## 中间契约

新增 `generated-asset-pack.v1`，至少包含：

- `project_id`、`generation_id`、`provider_commit`、`created_at`
- `script`、`script_sha256`
- `audio.path`、`audio.sha256`、`audio.duration_sec`
- `subtitle.path`、`subtitle.sha256`、`subtitle.language`
- `materials[]`：`provider`、`asset_id`、`source_page`、`local_path`、`sha256`、`duration_sec`、`width`、`height`、`search_term`
- `license_status`、`source_info`

MPT 当前 `script.json` 有脚本、搜索词、参数和素材来源，但没有完整的本地文件 SHA/授权状态，桥接层必须补齐。

## 分阶段路线

### P0：契约闭环

1. Pipeline 增加 `import-generated-pack` CLI：校验 schema，限制路径在任务目录内，计算媒体 SHA，生成标准 `assets.json`。
2. Director 增加 `creative_mode`：`source_vlog`、`narrated_explainer`、`hybrid`；默认不引入 MPT 旁白。
3. 旁白作为 enhancement 独立音轨；`hybrid` 只允许在明确的非对话区间使用，原声锁定区继续由 `keep_original_audio` 保护。
4. 抽出版本化 `vlog-contracts` 小包，消除跨仓库测试手工切换 venv 的问题。

### P1：候选比较

MPT 的多脚本/多素材候选必须进入 `directed-candidate-review-pack`，带 candidate SHA、proxy、realized timeline、cut QA 和 `NON-RELEASE CANDIDATE` 标记。评分可包含脚本覆盖率、来源完整度、旁白/画面时长误差、镜头重复率和字幕覆盖率，但只用于排序，不替代人工审批。

### P2：Director 自身缺口

继续完成 playback-rate 真实 proxy 预览、证据约束的时间跳跃卡、reference style evaluator，并保持 `source media SHA -> plan SHA -> realized timeline -> cut QA -> human approval -> release output SHA` 证据链。这些不能靠 MPT 自动补齐。

### P3：发布闭环

状态分离为 `video_release=approved`、`metadata=generated/reviewed`、`cross_post=pending/processing/complete/failed`。第三方发布失败不能覆盖成片状态，且必须后置到 release approval 之后。

## 不建议

- 不复制 MPT 的 `app`、Streamlit、MoviePy、FastAPI，避免大依赖面和第二套任务状态机。
- 不把 MPT `final-1.mp4` 当作 Pipeline source 或 Director approved base。
- 不把 MPT 固定 3–5 秒切片当成长 vlog 导演逻辑。
- 不根据参考片自动推断精确变速倍率；当前 `preview_required_patterns` 应继续 fail-closed。

## 首个 MVP

MPT 生成 2 个脚本候选、旁白、字幕初稿和 B-roll 候选；桥接层输出 `generated-asset-pack.v1`；Pipeline 入库并记录 SHA/来源；Director 生成 2 套候选 EDL 和 proxy；人工选择或拒绝；最后走 cut QA、字幕听校、enhancement gate 和 release approval。

验收：素材来源记录 100%；候选 SHA 绑定 100%；审批前不得出现 release output；旁白与字幕时长误差 <100ms；跨仓库契约测试在单一兼容环境通过。

---
🤖 *本内容由 AI Agent 自动发布*
