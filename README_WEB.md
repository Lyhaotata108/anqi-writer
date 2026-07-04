# Anqi Writer Web UI

这个界面把命令行流程封装成一个本地网页：

1. 关键词聚类
2. 主文章标题生成
3. 正文蓝图生成
4. 结果预览和 CSV 下载

## 本地启动

```bash
cd /Users/hjg/Documents/anqicms-writer
git fetch origin main
git reset --hard origin/main
python3 -m pip install -r requirements.txt
streamlit run web_app.py
```

启动后浏览器会打开：

```text
http://localhost:8501
```

## 使用方式

### 方式一：直接粘贴关键词

在页面中的“粘贴关键词”输入框里，一行一个关键词，然后点击左侧“开始运行”。

### 方式二：上传 TXT / CSV

上传 TXT 或 CSV 文件：

- TXT：一行一个关键词
- CSV：支持 `keyword` 或 `primary_keyword` 字段

## 输出文件

每次运行会生成一个独立目录：

```text
output/web_runs/<run_name>/
```

里面包含：

```text
keywords.txt
keyword_cluster_audit.csv
primary_article_queue.csv
title_intent_audit.csv
body_blueprint_audit.csv
```

## 页面功能

- 查看关键词聚类结果
- 查看主文章队列
- 查看标题审计表
- 查看正文蓝图
- 查看标题结构分布
- 查看正文模板分布
- 下载每一步 CSV

## 推荐流程

先看 `primary_article_queue.csv`，确认主关键词选择是否合理。

再看 `title_intent_audit.csv`，确认标题是否符合点击风格。

最后看 `body_blueprint_audit.csv`，确认正文模板、H2、目标字数、FAQ 关键词是否合理。
