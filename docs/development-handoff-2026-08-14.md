# 导演系统开发交接（2026-08-14）

## 1. 仓库与代码基线

两个仓库必须放在同一父目录下，并使用同一分支：

- Director: `https://github.com/mwh22-up/firered-vlog-director.git`
- Pipeline: `https://github.com/mwh22-up/firered-vlog-pipeline.git`
- Branch: `feature/director-learning-loop`
- Director 功能提交: `38df3dcb1236a5e9855b798c61e3f8311f469fa8`
- Pipeline 功能提交: `78388ccb50930f276811cf2503fca25a95f85670`
- 参考视频学习完成提交: `14eb3a20aa6ada5402e93c99fb035a0547dd5fbf`

交接文件本身位于 Director 的后续独立提交。新电脑拉取分支后，应以远端分支最新 HEAD 为准，并确认上述功能提交都在历史中。

## 2. 已完成能力

### 参考学习

- 当前正式进度已扩展为 26/26 个参考视频学习完成；本交接文件中的旧功能提交仍作为历史基线。
- 当前聚合结果包含 26 个独立来源；具体稳定模式数量以 `reference-learning/reference-techniques.aggregate.v1.json` 为准。
- 学习数据、证据范围、guardrail 和聚合一致性已有 Schema 与测试覆盖。

### Director

- 根据对白、动作、反应、风景、趣味、质量等目标素材证据生成多候选 EDL。
- 支持 concise、balanced、immersive 三种候选方向及候选评分。
- 支持事件链、对白短语、人工必留节点和显式用户反馈保护。
- 支持候选预览选择、真实 cut QA、人工审核及 SHA 绑定审批。
- Pattern Compiler 当前将 3 条 stable pattern 编译为执行规则：
  - `humor-preserve-real-awkward-process`: evidence-backed 自动候选。
  - `opening-phased-hook-not-uniform-fast-cut`: 三阶段开场自动候选。
  - `playback-rate-fast-forward-travel-compression-visual-estimate`: preview-only 候选。
- 三阶段开场要求未来回报、人物反应、行动推进三类低对白高质量镜头同时存在，否则 fail-closed。
- 旅行压缩要求连续镜头不少于 8 秒、`speech_ratio <= 0.1`、`visual.motion >= 0.085`，只输出 `preview_required_patterns`，不自动写入倍率。
- 旅行压缩 proposal 现有稳定 `proposal_id` 和结构化 evidence；locked/protected、user lock 或关键对白区间 fail closed。

### Pipeline

- 可按 Director 候选生成 proxy 预览，并强制叠加 `NON-RELEASE CANDIDATE` 水印。
- 预览按候选 SHA 隔离缓存，防止旧预览冒充新候选。
- 可生成真实 cut QA、候选 review pack 和渲染时间线测量。
- 最终审批绑定候选、realized timeline、cut QA 和基础媒体 SHA；任一输入变化都会使批准失效。
- 发布渲染仍要求正式审批，候选预览不能直接成为发布文件。
- Pipeline 已能为每个合格 proposal 生成带水印的 1.25x、1.5x、2.0x 完整时间线候选，执行 `setpts` + `atempo`，记录实际时长、FFmpeg identity 与 A/V sync。
- v2 人工审批可选择至多一个 proposal/rate 或拒绝全部，并绑定 proposal、derived plan、preview、realized timeline、cut QA 及其 SHA；拒绝全部不会修改基础计划。

## 3. 最近验证结果

- Director 变速、审批和跨仓库目标测试：38 OK。
- Director 全量：318 tests，`OK (skipped=3)`。
- Pipeline 全量：`49 passed`，包含带水印候选和 2.0x 后实际时长、A/V sync 的真实 FFmpeg 短媒体集成。
- Ruff、compileall、`git diff --check`、敏感信息扫描通过。
- preview-only 契约检查通过：变速候选的 `playback_rate` 保持 `null`，edit plan segment 不包含未受支持的倍率字段。

不要把环境依赖错误描述成代码测试失败，也不要把受控候选倍率描述为参考学习得到的真实精确倍率。当前能渲染和审批变速候选，但仍必须由人工比较并选择或全部拒绝。

## 4. 新电脑环境恢复

建议统一使用 Python 3.11。Pipeline 声明 `<3.12`，Director 声明 `<3.13`，因此 3.11 是两个仓库的共同兼容版本。

```powershell
mkdir vlog-director-work
cd vlog-director-work

git clone --branch feature/director-learning-loop https://github.com/mwh22-up/firered-vlog-director.git
git clone --branch feature/director-learning-loop https://github.com/mwh22-up/firered-vlog-pipeline.git

cd firered-vlog-director
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[test]" PyYAML
.\.venv\Scripts\python.exe -m unittest discover -s tests

cd ..\firered-vlog-pipeline
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m pytest -q
```

如果不需要立即重跑耗时媒体测试，至少先执行：

```powershell
cd ..\firered-vlog-director
.\.venv\Scripts\python.exe -m unittest tests.test_technique_policy tests.test_director_engine tests.test_pipeline_contract_integration

cd ..\firered-vlog-pipeline
.\.venv\Scripts\python.exe -m pytest -q
```

## 5. 下一阶段开发顺序

### P0: 把变速 proposal 接入真实候选预览（已实现，待生产项目人工使用）

目标是消费 Director 的 `preview_required_patterns`，生成可比较但不可发布的变速预览，而不是自动决定倍率。

实现要求：

- 已实现 Pipeline 读取 proposal 素材区间与结构化证据。
- 已实现只对低对白、连续移动区间生成固定 1.25x、1.5x、2.0x 人工比较候选；倍率不是参考片推断结果。
- 已实现视频 `setpts`、音频显式 `atempo`、实际时长和音画同步 fail-closed 测量。
- 已实现不可发布水印及 proposal SHA、倍率、输出 SHA、realized timeline、cut QA、FFmpeg identity 绑定。
- 已实现人工选择一个 proposal/rate 或拒绝全部；未选择时不把倍率写入发布 edit plan。
- 已增加真实短媒体集成、字幕映射、cut boundary、时长和审批失效测试。

### P0: 时间跳跃卡

接入 `subtitle-time-card-compresses-waiting`，只在目标素材能证明等待前后状态及时间跳跃时生成独立时间卡。必须明确表示省略，不得伪装成实时连续过程，也不得误报为变速。

### P1: 纪录片信息图层

依次实现地点卡、地图路线、资料引用卡、编号步骤卡、聊天或历史资料对照。每类资产必须有来源、版权状态、OCR/事实核验、屏幕安全区和人工审核状态。

### P1: Reference style evaluator

对参考片和候选成片测量镜头长度分布、节奏曲线、字幕密度、图形覆盖率、音乐段落、SFX 密度和色彩层级。该评分用于候选比较，不能替代人工审批。

## 6. 不可破坏的边界

- 参考视频只提供正向风格证据，不能替代目标原片分析。
- 用户反馈优先于目标素材证据，目标素材证据优先于跨参考 pattern。
- 未经目标证据触发的 pattern 必须留在 guidance。
- preview-only 能力不得静默进入发布 edit plan。
- 不提交参考原视频、Cookie、Token、完整敏感字幕或本地绝对媒体路径。
- 不回滚两个仓库中已经存在的审批、候选预览和真实 cut QA 改造。
- 所有发布批准必须绑定真实渲染产物及其 SHA，任何输入变化都应使批准失效。

## 7. 新电脑续开发提示词

将下面整段发送给新电脑上的 Codex：

```text
请继续开发我的 vlog 导演系统。先阅读工作区 AGENTS.md，以及 firered-vlog-director/docs/development-handoff-2026-08-14.md，然后审计两个同级仓库：firered-vlog-director 和 firered-vlog-pipeline。

两个仓库都应位于 feature/director-learning-loop。先确认 git status、tracking、远端 SHA，并确认 Director 历史包含 38df3dcb1236a5e9855b798c61e3f8311f469fa8，Pipeline 历史包含 78388ccb50930f276811cf2503fca25a95f85670。不要回滚或覆盖已有改造。

本轮从交接文档的 P0“把变速 proposal 接入真实候选预览”开始，直接完成实现、测试和双仓库契约接入，不要只写方案。必须遵守以下边界：
1. Director 的 playback-rate pattern 当前只是 preview_required_patterns，参考学习没有提供可信精确倍率。
2. Pipeline 只能生成带 NON-RELEASE CANDIDATE 水印的多倍率候选，不能自动选择或直接发布。
3. 只处理低对白、连续移动且有 motion 证据的区间；含关键对白时 fail-closed。
4. 人工选择必须绑定 proposal、预览文件、realized timeline、cut QA 和 SHA；输入变化后批准失效。
5. edit plan Schema、renderer、duration calculation、subtitle projection、cut QA 都要正确处理输出时长变化。
6. 添加单元测试、真实 FFmpeg 媒体集成测试和跨仓库契约测试。

开始前先运行交接文档中的最小测试。实现后运行 Director 目标测试、相关全量测试、Pipeline pytest、Ruff、git diff --check 和敏感信息扫描。说明实际通过数量、未运行项和残余风险。完成后提交并推送两个仓库到当前分支，再核对本地 HEAD、tracking 和 GitHub 远端 SHA 一致。
```

## 8. 完成定义

下一阶段只有在以下条件全部满足时才算完成：

- 同一个 proposal 至少生成两个带身份记录的倍率预览。
- 人工可以选择一个倍率或拒绝全部候选。
- 未选择、证据不足、对白风险、SHA 不一致时发布链路 fail-closed。
- 选择后的时间线时长、字幕映射、cut QA 和真实渲染测量一致。
- 两个仓库测试通过、工作区干净、提交已推送、远端 SHA 已核对。
