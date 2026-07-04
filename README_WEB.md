# Anqi Writer Web UI

这个界面把命令行流程封装成一个本地网页，并支持三个分类：

```text
weight_loss
cbd
blood
```

页面流程：

1. 选择分类
2. 上传或粘贴关键词
3. 关键词聚类
4. 主文章标题生成
5. 正文蓝图生成
6. 结果预览和 CSV 下载

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

先在左侧选择分类：

```text
Weight Loss
CBD
Blood
```

然后在页面中的“粘贴关键词”输入框里，一行一个关键词，点击左侧“开始运行”。

### 方式二：上传 TXT / CSV

上传 TXT 或 CSV 文件：

- TXT：一行一个关键词
- CSV：支持 `keyword` 或 `primary_keyword` 字段

当前版本是一批关键词使用同一个分类。比如你要跑 CBD，就先选择 CBD，再上传 CBD 关键词。

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

- 分类选择：Weight Loss / CBD / Blood
- 查看关键词聚类结果
- 查看主文章队列
- 查看标题审计表
- 查看正文蓝图
- 查看分类分布
- 查看标题结构分布
- 查看正文模板分布
- 下载每一步 CSV

## 推荐流程

先看 `primary_article_queue.csv`，确认主关键词选择是否合理。

再看 `title_intent_audit.csv`，确认标题是否符合点击风格。

最后看 `body_blueprint_audit.csv`，确认正文模板、H2、目标字数、FAQ 关键词是否合理。

## 命令行备用方式

Weight Loss：

```bash
python3 scripts/keyword_cluster_engine.py data/title_intent_seed_keywords.txt --category weight_loss --audit-output output/keyword_cluster_audit_v1.csv --queue-output output/primary_article_queue_v1.csv
python3 scripts/title_intent_audit.py output/primary_article_queue_v1.csv --category weight_loss --output output/title_intent_audit_v38.csv
python3 scripts/body_blueprint_engine.py output/title_intent_audit_v38.csv --output output/body_blueprint_audit_v2.csv
```

CBD：

```bash
python3 scripts/keyword_cluster_engine.py data/cbd_keywords.txt --category cbd --audit-output output/cbd_cluster_audit.csv --queue-output output/cbd_primary_queue.csv
python3 scripts/title_intent_audit.py output/cbd_primary_queue.csv --category cbd --output output/cbd_title_audit.csv
python3 scripts/body_blueprint_engine.py output/cbd_title_audit.csv --output output/cbd_body_blueprint.csv
```

Blood：

```bash
python3 scripts/keyword_cluster_engine.py data/blood_keywords.txt --category blood --audit-output output/blood_cluster_audit.csv --queue-output output/blood_primary_queue.csv
python3 scripts/title_intent_audit.py output/blood_primary_queue.csv --category blood --output output/blood_title_audit.csv
python3 scripts/body_blueprint_engine.py output/blood_title_audit.csv --output output/blood_body_blueprint.csv
```
