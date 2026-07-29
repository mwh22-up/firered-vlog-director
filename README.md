# FireRed Vlog Director Core

可移植的“导演大脑”基础模块，用于在现有本地剪辑流水线中保护重要节点、笑点及其上下文。

当前包含：

- `moments.json`、`director_profile.json` 数据契约；
- `locked`、`protected`、`optional` 保护策略；
- `setup/payoff/reaction` 成组保护；
- `edit_plan.json` 覆盖率校验；
- 参考片学习清单与导演档案契约；
- 不依赖真实视频的单元测试。

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

## 接入现有流水线

在生成 `edit_plan.json` 后、FFmpeg 渲染前调用校验器。真实视频、模型、缓存、Cookie、Token 和输出文件不得提交到 GitHub。

## GitHub 同步

推荐使用 GitHub CLI 的浏览器授权，不要把 Personal Access Token 写入文件或发送给 Agent：

```powershell
gh auth login --web --git-protocol https
gh repo create firered-vlog-director --private --source . --remote origin
```

创建仓库、首次提交和推送前，先执行：

```powershell
.\scripts\check-environment.ps1
git status --short
git check-ignore -v .env reference-videos\sample.mp4 projects\demo\raw\private.mp4
```

家里电脑通过 `git clone` 获取代码，真实视频和模型继续保存在仓库外。
