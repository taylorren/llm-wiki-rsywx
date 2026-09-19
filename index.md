# 我的维客 / My Wiki

这是一个用 [llm-wiki](llm-wiki.md) 模式搭建的个人知识库：把博客归档交给 LLM
增量整理成互相链接的主题页面，而不是每次提问都从原文重新检索。

## 从这里开始

- [llm-wiki.md](llm-wiki.md) — 这个模式本身（Andrej Karpathy 的原文）。
- [wiki/schema.md](wiki/schema.md) — 维护规范：目录结构、页面约定、引文格式、
  生成物与手工层的边界。
- [wiki/index.md](wiki/index.md) — 主题页面索引。
- [wiki/log.md](wiki/log.md) — 操作日志。
- [README.md](README.md) — 搭建与运行说明（安装、抓取、生成、构建、发布）。

## 快速启动

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp config.example.py config.py      # 填你的博客地址等
python3 tools/wxr_to_md.py          # 或 python3 tools/sync_posts.py
python3 tools/gen_index.py
python3 tools/lint_wiki.py
python3 tools/build_site.py --serve
```

站点内容（这个文件、`wiki/`）可以按你的许可自由发布；`sources/`、`blog/`、
`inbox/` 与所有生成物只留在本机。