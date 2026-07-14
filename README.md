# aesthetic-v4 图片风格评估操作手册

这个项目可以直接评估图片目录里的 UI 截图风格，输出结构化评分、CSV 和 HTML 报告。当前主要入口是：

```powershell
python pipeline\scripts\run_image_aesthetic_v4.py <图片目录> --run-dir <输出目录>
```

## 1. 环境配置

本地模型配置放在：

```text
config\aesthetic-v4.env
```

这个文件已被 `.gitignore` 忽略，不要提交到仓库。

支持多个 OpenAI-compatible 模型 API。变量命名规则是：

```text
<PROVIDER>_API_URL=...
<PROVIDER>_API_KEY=...
<PROVIDER>_MODEL=...
```

示例：

```text
MINIMAX_API_URL=https://api.minimaxi.com/v1/chat/completions
MINIMAX_API_KEY=your_key_here
MINIMAX_MODEL=MiniMax-M3

DOUBAO_API_URL=https://ark.cn-beijing.volces.com/api/v3/chat/completions
DOUBAO_API_KEY=your_key_here
DOUBAO_MODEL=doubao-seed-2-1-pro-260628

AESTHETIC_V4_MODEL_PROVIDER=minimax
AESTHETIC_V4_CASE_IMAGE_NAME=card.dsl.png
AESTHETIC_JUDGE_RETRIES=3
AESTHETIC_V4_WORKERS=1
```

依赖安装：

```powershell
python -m pip install -r pipeline\requirements.txt
```

## 2. 支持的数据集结构

默认支持这种结构：

```text
datasets\case-600-newSkill-gpt5.5-long\
  Case-01-low-power-001\
    card.dsl.png
  Case-01-low-power-002\
    card.dsl.png
  ...
```

默认评估每个 Case 子目录里的：

```text
card.dsl.png
```

如果要改文件名：

```powershell
python pipeline\scripts\run_image_aesthetic_v4.py D:\A2UI\CartTaskSpec\datasets\case-600-newSkill-gpt5.5-long --case-image-name other.png --run-dir runs\case-600-other
```

如果想递归评估目录里所有图片：

```powershell
python pipeline\scripts\run_image_aesthetic_v4.py input\test_60 --all-images --run-dir runs\case-600-all-images
```

## 3. 常用命令

先试跑 5 张：

```powershell
python pipeline\scripts\run_image_aesthetic_v4.py D:\A2UI\CartTaskSpec\datasets\case-600-newSkill-gpt5.5-long --limit 5 --run-dir runs\case-600-smoke
```

全量跑：

```powershell
python pipeline\scripts\run_image_aesthetic_v4.py D:\A2UI\CartTaskSpec\datasets\case-600-newSkill-gpt5.5-long --run-dir runs\case-600-long --resume
```

并发 4 路：

```powershell
python pipeline\scripts\run_image_aesthetic_v4.py D:\A2UI\CartTaskSpec\datasets\case-600-newSkill-gpt5.5-long --run-dir runs\case-600-long --workers 4 --resume
```

使用 MiniMax：

```powershell
python pipeline\scripts\run_image_aesthetic_v4.py D:\A2UI\CartTaskSpec\datasets\case-600-newSkill-gpt5.5-long --model-provider minimax --run-dir runs\case-600-minimax --limit 5
```

使用豆包：

```powershell
python pipeline\scripts\run_image_aesthetic_v4.py D:\A2UI\CartTaskSpec\datasets\case-600-newSkill-gpt5.5-long --model-provider doubao --run-dir runs\case-600-doubao --limit 5
```

## 4. 重要参数说明

`--run-dir`

本次评估的输出目录。比如 `--run-dir runs\case-600-long` 会把报告、CSV、缓存和中间文件都写到这个目录。

`--limit`

本次最多评估多少张图片。`--limit 5` 表示只跑前 5 张；默认 `0` 表示不限制，跑全部。

`--resume`

断点续跑。会跳过已经写入 `scores.jsonl` 的样本。注意：失败记录也会被跳过。如果要重跑失败样本，不要加 `--resume`，或者换一个新的 `--run-dir`。

`--workers`

并发数。默认是 1。可以试 `--workers 2` 或 `--workers 4`。如果遇到限流或超时，就调小。

`--judge-retries`

模型调用失败后的重试次数。默认是 3，也就是最多尝试 4 次。

`--model-provider`

选择模型 API。`minimax` 会读取 `MINIMAX_*` 配置，`doubao` 会读取 `DOUBAO_*` 配置。

`--score-only`

只要求模型返回分数，速度更快但信息更少。默认使用 full JSON；如果 full JSON 解析失败，脚本会自动 fallback 到 score-only。

## 5. 输出文件

每次运行后，`--run-dir` 目录下会生成：

```text
manifest.jsonl          # 本次找到的图片清单
scores.jsonl            # 每张图的原始评分结果
score_cache.jsonl       # 模型评分缓存
scores.csv              # 表格结果
report.html             # HTML 报告，优先打开这个看
report.summary.json     # 报告摘要
run.summary.json        # 本次运行摘要，包含 provider/model 信息
```

最常看的两个文件：

```text
report.html
scores.csv
```

## 6. 失败和重试策略

脚本当前有以下容错：

- 模型调用失败会按 `--judge-retries` 重试，默认 3 次。
- 模型输出会先用标准 JSON 解析。
- 标准 JSON 失败后会尝试 JSON5 / 宽松解析。
- 支持尾逗号、未加引号的 key、Markdown 代码块等常见模型输出问题。
- full JSON 仍失败时，会自动 fallback 到 score-only 再请求一次。

如果某次运行中有 failed 记录，想重跑：

```powershell
python pipeline\scripts\run_image_aesthetic_v4.py D:\A2UI\CartTaskSpec\datasets\case-600-newSkill-gpt5.5-long --run-dir runs\case-600-long
```

这里不要加 `--resume`。成功样本有缓存，通常不会重复消耗模型调用。

## 7. 推荐工作流

1. 先跑 5 张确认配置：

```powershell
python pipeline\scripts\run_image_aesthetic_v4.py D:\A2UI\CartTaskSpec\datasets\case-600-newSkill-gpt5.5-long --limit 5 --run-dir runs\case-600-smoke
```

2. 打开报告：

```text
runs\case-600-smoke\report.html
```

3. 确认正常后全量跑：

```powershell
python pipeline\scripts\run_image_aesthetic_v4.py D:\A2UI\CartTaskSpec\datasets\case-600-newSkill-gpt5.5-long --run-dir runs\case-600-long --workers 2 --resume
```

4. 如中断，继续执行同一条命令即可续跑。

## 8. 旧说明

原始项目说明保留在：

```text
README_old.md
```
