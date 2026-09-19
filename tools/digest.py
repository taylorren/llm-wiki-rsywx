#!/usr/bin/env python3
"""Dump plain-text digests of source posts matching a category (or all).

Strips WordPress HTML so the LLM can read many posts quickly, and strips
the YAML frontmatter boilerplate. Output goes to a single file with a
parseable header per post.

Usage:
    python3 tools/digest.py 读书 > /tmp/dushu.txt
    python3 tools/digest.py 读书 --limit 60 --min-chars 400 > /tmp/dushu_top.txt
"""
import argparse
import html
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CATALOG = os.path.join(ROOT, "sources", "_catalog.tsv")

TAG_RE = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.S | re.I)
BLOCK_RE = re.compile(
    r"</?(p|div|br|li|ul|ol|h[1-6]|blockquote|tr|table|pre)[^>]*>", re.I)
TAG_ANY = re.compile(r"<[^>]+>")
FRONTMATTER_RE = re.compile(r"^---\n.*?\n---\n", re.S)
MD_HEAD_RE = re.compile(r"^# .*\n", re.M)
IMG_RE = re.compile(r"<img[^>]*alt=\"([^\"]*)\"[^>]*>", re.I)
# Keep anchors as markdown links so URLs (e.g. links to your book catalog)
# survive into the digest and the LLM can cite them when synthesizing pages.
A_RE = re.compile(r"<a[^>]*href=\"([^\"]*)\"[^>]*>(.*?)</a>", re.S | re.I)


def to_text(raw: str) -> str:
    raw = IMG_RE.sub(r"[图片: \1] ", raw)
    raw = A_RE.sub(r"[\2](\1)", raw)
    raw = TAG_RE.sub(" ", raw)
    raw = BLOCK_RE.sub("\n", raw)
    raw = TAG_ANY.sub("", raw)
    text = html.unescape(raw)
    text = text.replace("<!--more-->", "\n[READ MORE]\n")
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("category", nargs="?", default="")
    ap.add_argument("--min-chars", type=int, default=0)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--select", help="file with one title-substring per line")
    ap.add_argument("--exclude", action="store_true",
                    help="with --select: exclude instead of include")
    args = ap.parse_args()

    selected = None
    if args.select:
        with open(args.select, encoding="utf-8") as f:
            selected = [ln.strip() for ln in f if ln.strip()]

    rows = []
    with open(CATALOG, encoding="utf-8") as f:
        next(f)
        for line in f:
            parts = line.rstrip("\n").split("\t")
            if len(parts) != 6:
                continue
            date, year, title, cats, words, path = parts
            if args.category and args.category not in cats.split("|"):
                continue
            if selected is not None:
                hit = any(s in title for s in selected)
                if hit == args.exclude:
                    continue
            rows.append((date, title, cats, int(words), path))

    rows.sort()
    if args.limit:
        rows = sorted(rows, key=lambda r: -r[3])[:args.limit]
        rows.sort()

    out = []
    for date, title, cats, words, path in rows:
        with open(os.path.join(ROOT, path), encoding="utf-8") as f:
            raw = f.read()
        body = MD_HEAD_RE.sub("", FRONTMATTER_RE.sub("", raw), count=1)
        text = to_text(body)
        if len(text) < args.min_chars:
            continue
        out.append(f"\n{'=' * 70}\n## {date} | {title}\n"
                   f"cats: {cats} | file: {path}\n{'=' * 70}\n{text}\n")
    print("".join(out))
    print(f"\n[digest] {len(out)} posts", file=__import__("sys").stderr)


if __name__ == "__main__":
    main()