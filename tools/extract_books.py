#!/usr/bin/env python3
"""Extract every book-catalog link from the corpus.

If your posts link books to a catalog page such as
https://example.com/books/02072.html, this tool recovers those links into:

  - sources/_books.tsv  — one row per unique book URL
    (id, url, title, n_posts, posts) ; posts is a comma-separated list of
    catalog paths. Regenerate after each sync.
  - wiki/books.md       — generated index page, newest acquisitions (highest
    book id) first, each entry linking to the book page and to the posts
    that mention it.

Set the catalog prefix in config.py (BOOKS_BASE, see config.example.py) or via
LLMWIKI_BOOKS_BASE; leave it empty to skip. Like gen_index.py
(overview.md / sources.md), the wiki page is auto-generated and safe to
overwrite.

Usage:
    python3 tools/extract_books.py
"""
import csv
import html
import os
import re
import sys
import urllib.parse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import site_config  # noqa: E402

CATALOG = os.path.join(ROOT, "sources", "_catalog.tsv")
TSV_OUT = os.path.join(ROOT, "sources", "_books.tsv")
PAGE_OUT = os.path.join(ROOT, "wiki", "books.md")

# e.g. "https://example.com/books" -> matches .../books/02072.html
BOOKS_BASE = str(site_config.get("BOOKS_BASE")).rstrip("/")
_parsed = urllib.parse.urlparse(BOOKS_BASE)
_BOOK_HOST = re.escape(_parsed.netloc)
_BOOK_PATH = re.escape(_parsed.path.rstrip("/"))
BOOK_URL = BOOKS_BASE + "/"
# Older posts carry raw HTML anchors; newer synced posts use markdown links.
A_HTML_RE = re.compile(
    rf'<a[^>]*href="(https?://{_BOOK_HOST}{_BOOK_PATH}/(\d+)\.html)"[^>]*>'
    rf'(.*?)</a>', re.S | re.I)
A_MD_RE = re.compile(
    rf'\[([^\]]*)\]\((https?://{_BOOK_HOST}{_BOOK_PATH}/(\d+)\.html)\)')
TAG_ANY = re.compile(r"<[^>]+>")
MAX_POST_LINKS = 6  # per-book post links shown before folding into "…等 N 篇"

PAGE_HEADER = """# 书目索引 / Book Index

> 本页由 `tools/extract_books.py` 自动生成（与 `overview.md`、`sources.md` 同属
> 生成层），汇总正文里指向 [{books_base}]({root_url}) 的全部
> 书目链接——共 {n_books} 本、散布于 {n_posts} 篇日志中。按书号降序（即最近的
> 书在前）。重新同步后运行 `python3 tools/extract_books.py` 再生成。
>
> 书目链接前缀由 `config.py` 的 `BOOKS_BASE` 决定（见 `config.example.py`）。

"""


def main():
    if not BOOKS_BASE or _parsed.netloc in ("", "example.com"):
        print("[books] BOOKS_BASE is not configured (config.py) — nothing to "
              "do. See config.example.py.", file=sys.stderr)
        return
    if not os.path.exists(CATALOG):
        print(f"[books] {os.path.relpath(CATALOG, ROOT)} not found — run the "
              f"converter (tools/wxr_to_md.py) first.", file=sys.stderr)
        sys.exit(1)

    mentions = {}  # url -> {"id", "title", posts:set}
    posts = []     # (path, date, title) in catalog order
    with open(CATALOG, encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f, delimiter="\t"):
            if row.get("path"):
                posts.append((row["path"], row.get("date", ""),
                              row.get("title", "")))

    for path, date, title in posts:
        with open(os.path.join(ROOT, path), encoding="utf-8") as f:
            raw = f.read()
        hits = ([(u, b, TAG_ANY.sub("", html.unescape(t)).strip())
                 for u, b, t in A_HTML_RE.findall(raw)]
                + [(u, b, t.strip())
                   for t, u, b in A_MD_RE.findall(raw)])
        for url, bid, text in hits:
            text = text.replace("|", "/").replace("\n", " ").strip()
            rec = mentions.setdefault(url, {"id": bid, "title": text,
                                            "posts": set()})
            if text and not rec["title"]:
                rec["title"] = text
            rec["posts"].add(path)

    rows = sorted(mentions.values(), key=lambda r: r["id"], reverse=True)
    n_touched = len({p for r in rows for p in r["posts"]})

    with open(TSV_OUT, "w", encoding="utf-8") as f:
        f.write("id\turl\ttitle\tn_posts\tposts\n")
        for r in rows:
            f.write("\t".join([r["id"], BOOK_URL + r["id"] + ".html",
                               r["title"], str(len(r["posts"])),
                               ",".join(sorted(r["posts"]))]) + "\n")

    out = [PAGE_HEADER.format(n_books=len(rows), n_posts=n_touched,
                              books_base=BOOKS_BASE,
                              root_url=BOOKS_BASE.rsplit("/", 1)[0]),
           "| 书号 | 书目 | 提及篇数 | 提及该书的日志 |\n",
           "|---|---|---|---|\n"]
    for r in rows:
        plist = sorted(r["posts"])
        shown = []
        for p in plist[:MAX_POST_LINKS]:
            date = next((d for pa, d, _ in posts if pa == p), "")
            shown.append(f"[{date[5:10]}]({os.path.relpath(p, 'wiki')})")
        if len(plist) > MAX_POST_LINKS:
            shown.append(f"…等 {len(plist)} 篇")
        out.append(f"| {r['id']} | [{r['title'] or '（未命名）'}]({BOOK_URL}"
                   f"{r['id']}.html) | {len(plist)} | {' · '.join(shown)} |\n")

    with open(PAGE_OUT, "w", encoding="utf-8") as f:
        f.writelines(out)

    print(f"[books] {len(rows)} unique books across {n_touched} posts",
          file=sys.stderr)
    print(f"[books] wrote {os.path.relpath(TSV_OUT, ROOT)} and "
          f"{os.path.relpath(PAGE_OUT, ROOT)}", file=sys.stderr)


if __name__ == "__main__":
    main()
