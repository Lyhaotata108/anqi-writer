# Anqi Writer Web UI

这个界面把命令行流程封装成一个本地网页，并支持三个分类同时运行：

```text
weight_loss
cbd
blood
```

页面流程：

1. 选择要运行的分类，可以单选，也可以三个一起选
2. 每个分类单独上传或粘贴关键词
3. 一键运行关键词聚类
4. 一键生成主文章标题
5. 一键生成正文蓝图
6. 一键生成完整 Markdown 正文：可选模板生成或 AI 生成
7. 页面预览结果和下载 CSV / Markdown

## 本地启动

```bash
cd /Users/hjg/Documents/anqicms-writer
git fetch origin main
git reset --hard origin/main
python3 -m pip install -r requirements.txt
python3 -m streamlit run web_app.py
```

启动后浏览器会打开：

```text
http://localhost:8501
```

## 使用方式

左侧选择要运行的分类：

```text
Weight Loss
CBD
Blood
```

可以三个同时选中。页面中会出现三个输入 Tab，每个分类独立输入自己的关键词。

### 方式一：直接粘贴关键词

在对应分类的输入框里粘贴关键词，一行一个。

### 方式二：上传 TXT / CSV

每个分类都可以单独上传 TXT 或 CSV 文件：

- TXT：一行一个关键词
- CSV：支持 `keyword` 或 `primary_keyword` 字段

## AI 正文生成

左侧勾选：

```text
使用 AI 生成爆款正文
```

然后填写：

```text
API Key
API Base URL
Model
Temperature
每个分类最多生成几篇
```

默认使用 OpenAI-compatible `/v1/chat/completions` 接口，所以也可以接兼容 OpenAI 协议的代理或第三方模型服务。

建议批量生成时先这样测试：

```text
每个分类最多生成几篇 = 3 或 5
```

确认文章风格、长度、FAQ、表格都没问题后，再改成：

```text
每个分类最多生成几篇 = 0
```

`0` 表示全量生成。

## 批量生成策略

系统不是一次把所有文章塞给 AI，而是：

```text
一篇文章 = 一次 API 请求
```

每篇生成完会立刻写入 Markdown 文件和发布队列。这样即使中途断开，也可以继续跑；已存在的 Markdown 默认会跳过，除非勾选“覆盖已存在 Markdown”。

## 输出文件

每次运行会生成一个独立目录：

```text
output/web_runs/<run_name>/
```

如果三个分类同时跑，目录结构是：

```text
output/web_runs/<run_name>/weight_loss/
output/web_runs/<run_name>/cbd/
output/web_runs/<run_name>/blood/
```

每个分类目录里面都有：

```text
keywords.txt
keyword_cluster_audit.csv
primary_article_queue.csv
title_intent_audit.csv
body_blueprint_audit.csv
article_publish_queue.csv
articles/
```

`articles/` 目录里是一篇文章一个 Markdown 文件，可以预览、下载，也可以作为 CMS 导入源。

## 页面功能

- 多分类同时运行：Weight Loss / CBD / Blood
- 每个分类单独上传关键词
- 每个分类单独生成聚类、标题、正文蓝图、完整 Markdown 正文
- 支持 AI 正文生成，也保留模板正文生成作为备用
- 多分类运行汇总表
- 查看关键词聚类结果
- 查看主文章队列
- 查看标题审计表
- 查看正文蓝图
- 查看完整正文发布队列
- 预览 Markdown 正文
- 查看标题结构分布
- 查看正文模板分布
- 查看正文质量状态
- 下载每一步 CSV
- 下载单篇 Markdown

## 推荐流程

先看每个分类的 `primary_article_queue.csv`，确认主关键词选择是否合理。

再看 `title_intent_audit.csv`，确认标题是否符合点击风格。

然后看 `body_blueprint_audit.csv`，确认正文模板、H2、目标字数、FAQ 关键词是否合理。

最后看 `article_publish_queue.csv` 和 `articles/` 里的 Markdown 正文。`quality_status = PASS` 表示基础结构检查通过；医疗、CBD、Blood 类内容发布前仍建议人工快速扫一遍。

## 命令行备用方式

模板正文：

```bash
python3 scripts/body_writer_engine.py output/body_blueprint_audit_v2.csv --articles-dir output/articles/weight_loss --queue-output output/article_publish_queue_weight_loss.csv
```

AI 正文：

```bash
export OPENAI_API_KEY="你的 API Key"
export OPENAI_BASE_URL="https://api.openai.com/v1"
export OPENAI_MODEL="gpt-4o-mini"
python3 scripts/ai_body_writer_engine.py output/body_blueprint_audit_v2.csv --articles-dir output/ai_articles/weight_loss --queue-output output/ai_article_publish_queue_weight_loss.csv --max-articles 3
```

全量 AI 生成时把 `--max-articles 3` 改成 `--max-articles 0` 或直接删掉这个参数。
