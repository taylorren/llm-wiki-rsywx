#!/usr/bin/env python3
"""Generate wiki/overview.md and wiki/sources.md from sources/_catalog.tsv.

It does NOT touch wiki/index.md or the root index.md -- both are curated by
hand.
"""
import csv
import os
import sys
from collections import Counter, defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CATALOG = os.path.join(ROOT, "sources", "_catalog.tsv")

REQUIRED = ("date", "year", "title", "categories", "words", "path")

if not os.path.exists(CATALOG):
    sys.exit(f"{os.path.relpath(CATALOG, ROOT)} not found — ingest the corpus "
             f"first (tools/wxr_to_md.py, or tools/sync_posts.py on a machine "
             f"with the blog export)")

rows = []
with open(CATALOG, encoding="utf-8", newline="") as f:
    reader = csv.DictReader(f, delimiter="\t")
    missing = [c for c in REQUIRED if c not in (reader.fieldnames or [])]
    if missing:
        sys.exit(f"{CATALOG}: missing column(s): {', '.join(missing)}")
    for lineno, row in enumerate(reader, start=2):
        try:
            words = int(row["words"])
        except (TypeError, ValueError):
            sys.exit(f"{CATALOG}:{lineno}: bad word count {row['words']!r}")
        rows.append({"date": row["date"], "year": row["year"],
                     "title": row["title"],
                     "cats": [c for c in (row["categories"] or "").split("|") if c],
                     "words": words, "path": row["path"],
                     "post_id": row.get("post_id", "")})

# One file per post: a duplicate path would inflate every count below.
seen_paths = {}
for r in rows:
    if r["path"] in seen_paths:
        sys.exit(f"{CATALOG}: duplicate path {r['path']} "
                 f"(post_id {seen_paths[r['path']]} and {r['post_id']}) — "
                 f"re-run tools/wxr_to_md.py")
    seen_paths[r["path"]] = r["post_id"]

# ---- overview ----
by_year = Counter(r["year"] for r in rows)
cat_count = Counter()
for r in rows:
    for c in r["cats"]:
        cat_count[c] += 1
total_words = sum(r["words"] for r in rows)

ov = ["# 博客总览 / Blog Overview", "",
      f"Total posts: **{len(rows)}** · Total words (approx): "
      f"**{total_words:,}** · Span: **{min(by_year)}–{max(by_year)}**", "",
      "## Posts by year", "", "| Year | Posts |", "|---|---|"]
for y in sorted(by_year):
    ov.append(f"| {y} | {by_year[y]} |")
ov += ["", "## Top categories", "", "| Category | Posts |", "|---|---|"]
for c, n in cat_count.most_common(25):
    ov.append(f"| {c} | {n} |")
ov.append("")
with open(os.path.join(ROOT, "wiki", "overview.md"), "w", encoding="utf-8") as f:
    f.write("\n".join(ov))

# ---- source catalog (auto-generated; wiki/index.md is curated by hand) ----
idx = ["# 原始资料索引 / Source Catalog", "",
       "Automatically generated catalog of all ingested sources. "
       "Regenerate with `python3 tools/gen_index.py`. "
       "See [wiki index](index.md) for the curated overview.",
       ""]
by_year_rows = defaultdict(list)
for r in rows:
    by_year_rows[r["year"]].append(r)
for y in sorted(by_year_rows):
    idx += [f"## {y} ({len(by_year_rows[y])} posts)", ""]
    for r in sorted(by_year_rows[y], key=lambda r: r["date"]):
        cats = ", ".join(r["cats"]) or "—"
        rel = os.path.relpath(r["path"], os.path.join(ROOT, "wiki"))
        idx.append(f"- [{r['title']}]({rel}) — {r['date']} · {cats}")
    idx.append("")
with open(os.path.join(ROOT, "wiki", "sources.md"), "w", encoding="utf-8") as f:
    f.write("\n".join(idx))

print(f"overview.md + sources.md written ({len(rows)} posts)")
