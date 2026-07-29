# 参考视频学习：家庭电脑使用说明

## 1. 仓库里有什么

GitHub 保存：

- 参考视频学习代码、CLI、Schema 和测试；
- 4 支参考视频的脱敏逐镜头分析；
- 4 份 v2 单视频语义档案；
- 1 份四视频聚合导演档案。

GitHub 不保存：

- 原视频、代理视频、音频和联系表；
- 完整 ASR 逐字稿；
- Whisper 模型缓存；
- Cookie、Token、密钥和家庭视频。

直接使用的聚合档案：

```text
reference-learning\director-profile.aggregate.v2.json
```

重点字段：

- `semantic_principles`：跨视频共同导演原则；
- `shot_selection_model.retain_archetypes`：优先保留镜头类型；
- `shot_selection_model.selective_archetypes`：满足条件才保留的镜头；
- `shot_selection_model.cut_first_signals`：优先剪除信号；
- `shot_selection_model.sequence_dependencies`：铺垫、行动、结果和反应的成组约束；
- `pacing_model`：正文和开场镜头时长范围；
- `audio_model`：对白、可能配乐、环境声和静音比例。

## 2. 首次安装

```powershell
git clone https://github.com/mwh22-up/firered-vlog-director.git D:\vlog-studio\firered-vlog-director
cd D:\vlog-studio\firered-vlog-director

.\scripts\check-environment.ps1

python -m venv .venv-analysis
.\.venv-analysis\Scripts\python.exe -m pip install --upgrade pip
.\.venv-analysis\Scripts\python.exe -m pip install -e ".[analysis]"

.\.venv-analysis\Scripts\python.exe -m unittest discover -s tests -v
```

要求：

- Python 3.11 或 3.12；
- Git；
- FFmpeg 和 FFprobe；
- 可访问 GitHub、Bilibili 公开接口和 Hugging Face 模型下载。

首次使用 `faster-whisper small` 时会下载模型。模型保存在用户缓存目录，不进入 Git。

## 3. 直接使用已有导演档案

在现有导演 Prompt 或 `edit_plan` 生成阶段读取：

```python
import json
from pathlib import Path

profile_path = Path(
    r"D:\vlog-studio\firered-vlog-director"
    r"\reference-learning\director-profile.aggregate.v2.json"
)
profile = json.loads(profile_path.read_text(encoding="utf-8"))

director_context = {
    "principles": profile["semantic_principles"],
    "retain": profile["shot_selection_model"]["retain_archetypes"],
    "selective": profile["shot_selection_model"]["selective_archetypes"],
    "cut_first": profile["shot_selection_model"]["cut_first_signals"],
    "dependencies": profile["shot_selection_model"]["sequence_dependencies"],
    "pacing": profile["pacing_model"],
    "audio": profile["audio_model"],
}
```

导演生成计划时必须遵守：

1. 有效对白、动作推进、人物反应和结果优先进入候选；
2. 环境、细节和转场只有提供新信息或完成事件结构时保留；
3. 铺垫、行动、结果和反应必须成组判断；
4. 重复、模糊、无动作、无声音和无新增信息的镜头优先删除；
5. 应用档案后仍必须运行原有 `validate-protection` 门禁。

## 4. 学习新的 Bilibili 视频

### 4.1 下载公开低清代理

```powershell
$bvid = "BVxxxxxxxxxx"
$cache = "D:\vlog-cache\bilibili-$bvid"

.\scripts\fetch-bilibili-proxy.ps1 `
  -Bvid $bvid `
  -OutputDirectory $cache
```

脚本只使用公开匿名接口，不需要 Cookie 或 Token。

### 4.2 执行完整分析

ASR 长视频默认串行运行，不要同时启动多支视频。

```powershell
.\.venv-analysis\Scripts\vlog-director.exe analyze-reference `
  --input "$cache\proxy.mp4" `
  --source-id "bilibili-$bvid" `
  --url "https://www.bilibili.com/video/$bvid/" `
  --work-directory "$cache\learning\work" `
  --output "$cache\learning\analysis.full.json" `
  --portable-output "reference-learning\analysis.$bvid.json" `
  --review-directory "$cache\learning\review" `
  --review-event-limit 12 `
  --asr-provider faster-whisper `
  --asr-model small
```

输出：

- `$cache\learning\analysis.full.json`：本地完整分析，包含逐字稿；
- `$cache\learning\review\event-*.jpg`：事件级联系表；
- `reference-learning\analysis.<BV>.json`：可提交 Git 的脱敏分析。

## 5. 人工抽查事件

优先检查：

1. `protect` 事件是否确实值得保留；
2. 联系表是否覆盖环境、行动、结果和反应；
3. `cut_first` 是否仅来自重复、模糊或无新增信息；
4. ASR 是否把配乐或环境声误识别成对白；
5. 长镜头是否因包含完整对白或真实反应而被合理保留。

如果只修改评分和聚合规则，不要重新跑 ASR。保存本地 `transcript.json` 后使用：

```powershell
--transcript "$cache\learning\transcript.json"
```

## 6. 更新聚合导演档案

先为新视频建立遵循 `schemas\director-profile.schema.json` 的 v2 语义档案，然后执行：

```powershell
.\.venv-analysis\Scripts\vlog-director.exe aggregate-reference `
  --analysis `
    reference-learning\analysis.BV-a.json `
    reference-learning\analysis.BV-b.json `
  --profile `
    reference-learning\director-profile.BV-a.v2.json `
    reference-learning\director-profile.BV-b.v2.json `
  --output reference-learning\director-profile.aggregate.v2.json
```

只有至少一半参考视频共同支持的规则才进入聚合档案。

## 7. 更新代码

公司电脑推送新版本后，家庭电脑执行：

```powershell
cd D:\vlog-studio\firered-vlog-director
git pull origin main
.\.venv-analysis\Scripts\python.exe -m pip install -e ".[analysis]"
.\.venv-analysis\Scripts\python.exe -m unittest discover -s tests -v
```

## 8. 当前能力边界

- ASR 可能误识别地名、方言、多人重叠对白和背景音乐；
- `music_likely` 是声学启发式判断，不是歌曲识别；
- 参考成片只能学习被保留镜头的正向模式；
- 真正监督学习“保留或删除”需要原始素材、最终成片和时间线映射；
- 聚合档案已经可读取，但接入你家里的导演生成器需要把 `director_context` 加入现有 Prompt 或模型输入。

## 9. 验收清单

- `git pull` 成功；
- 环境检查通过；
- 26 项测试通过；
- 聚合档案可读取；
- 新视频代理保存在仓库外；
- 完整逐字稿没有进入 Git；
- 事件联系表已人工检查；
- 导演生成计划后仍通过保护门禁。
