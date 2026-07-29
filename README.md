# FireRed Vlog Director Core

可移植的“导演大脑”基础模块，用于在现有本地剪辑流水线中保护重要节点、笑点及其上下文。

当前包含：

- `moments.json`、`director_profile.json` 数据契约；
- `locked`、`protected`、`optional` 保护策略；
- `setup/payoff/reaction` 成组保护；
- `edit_plan.json` 覆盖率校验；
- 参考片学习清单与导演档案契约；
- ASR、镜头评分、事件分组、声音分段与跨视频聚合；
- 配乐、防抖与连贯、字幕、插画动效的统一增强计划；
- 不依赖真实视频的单元测试。

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
python -m pip install -e .
.\scripts\test.ps1
```

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

## 参考片学习

安装本地分析依赖：

```powershell
python -m venv .venv-analysis
.\.venv-analysis\Scripts\python.exe -m pip install -e ".[analysis]"
```

生成逐镜头、事件、ASR 和声音分析，并输出事件抽查联系表：

```powershell
.\.venv-analysis\Scripts\vlog-director.exe analyze-reference `
  --input C:\tmp\bilibili-BV-example\proxy.mp4 `
  --source-id bilibili-BV-example `
  --url https://www.bilibili.com/video/BV-example/ `
  --work-directory C:\tmp\bilibili-BV-example\learning-work `
  --review-directory C:\tmp\bilibili-BV-example\event-review `
  --output C:\tmp\bilibili-BV-example\analysis.full.json `
  --portable-output reference-learning\analysis.BV-example.json `
  --asr-provider faster-whisper `
  --asr-model small
```

聚合多支参考片：

```powershell
.\.venv-analysis\Scripts\vlog-director.exe aggregate-reference `
  --analysis reference-learning\analysis.BV-a.json reference-learning\analysis.BV-b.json `
  --profile reference-learning\director-profile.BV-a.v2.json reference-learning\director-profile.BV-b.v2.json `
  --output reference-learning\director-profile.aggregate.json
```

Git 只保存 JSON 分析与规则。代理视频、模型缓存、逐帧图片和完整字幕保留在本地。

家庭电脑从安装、学习新视频到接入现有导演流水线的完整步骤见
`docs/reference-learning-home-guide.md`。
