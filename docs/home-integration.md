# 家庭电脑接入

## 1. 获取代码

```powershell
git clone https://github.com/mwh22-up/firered-vlog-director.git D:\vlog-studio\firered-vlog-director
cd D:\vlog-studio\firered-vlog-director
.\scripts\check-environment.ps1
.\scripts\test.ps1
```

## 2. 接入已有项目

已有项目不需要迁移视频。只需确保目录中存在：

```text
.vlog-project.json
brief.yaml
work\analysis\moments.json
work\plans\edit_plan.v{version}.json
work\qa\
```

如果目录结构还不一致，先用 `init-project.ps1` 创建一个空项目，再把已有 `raw`、分析结果、计划和输出映射进去。

## 3. 挂到现有 pipeline.py

在调用 FFmpeg 之前增加：

```python
from pathlib import Path

from vlog_director import guard_project_render

result = guard_project_render(Path(project_path), version)
if result["status"] != "passed":
    raise RuntimeError(f"Protection guard blocked render: {result['report_path']}")
```

`locked` 或 `protected` 节点覆盖不足、笑点上下文缺失时，流水线必须停止，不允许静默继续渲染。

## 4. 公司与家庭电脑协作

公司电脑只提交代码、规则、Schema、Prompt、导演档案和脱敏测试。家庭电脑负责真实视频运行，并把失败情况整理为不含人脸、对白原文和绝对路径的测试数据。

每轮改造遵循：

```text
公司电脑修改并测试
→ 提交并推送 GitHub
→ 家庭电脑 git pull
→ 真实素材验证
→ 记录脱敏反馈
→ 下一轮修改
```
