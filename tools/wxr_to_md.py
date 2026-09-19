#!/usr/bin/env python3
"""Convert a WordPress WXR export into one markdown file per post.

Usage: python3 tools/wxr_to_md.py blog/WordPress.*.xml
Output: sources/posts/<YYYY>/<slug>.md  (immutable raw layer)
Skips attachments, templates, styles, non-published posts.

The output path is derived from `wp:post_date_gmt` + a slug of the title, so
two distinct WXR items can collide on the same path (the blog has one such
case: post 2941 and post 2943 are the same 老彼得五上奖状 text published twice,
12h apart, across the GMT midnight boundary). Collisions are resolved here:

  * identical body  -> the duplicate item is dropped, the first item kept
    (one file, one catalog row -- the file count is the post count);
  * different body  -> the file is disambiguated with a `-<post_id>` suffix
    rather than silently overwriting.
"""
import os
import re
import sys
import glob
import html
import hashlib
import unicodedata
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

NS = {
    "content": "http://purl.org/rss/1.0/modules/content/",
    "dc": "http://purl.org/dc/elements/1.1/",
    "wp": "http://wordpress.org/export/1.2/",
}

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "sources", "posts")


def slugify(name: str) -> str:
    name = unicodedata.normalize("NFKC", name).strip()
    name = re.sub(r"[^\w\s-]", "", name, flags=re.UNICODE)
    name = re.sub(r"[\s_-]+", "-", name).strip("-.")
    return name.lower() or "untitled"


def yaml_str(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ") + '"'


def cdata(node):
    return node.text if node is not None else ""


def post_body(item) -> str:
    """Prefer rendered content:encoded; fall back to wp:post_content."""
    encoded = item.find("content:encoded", NS)
    if encoded is not None and encoded.text and encoded.text.strip():
        return encoded.text
    pc = item.find("wp:post_content", NS)
    return cdata(pc) if pc is not None else ""


def count_len(body: str) -> int:
    """Approximate size: CJK characters counted individually + non-CJK words."""
    cjk = sum(1 for ch in body if "\u4e00" <= ch <= "\u9fff")
    words = len(re.sub(r"[\u4e00-\u9fff]", " ", body).split())
    return cjk + words


def render_markdown(*, title, iso_date, ptype, author, link, categories, tags,
                    body):
    """Render one post to the canonical markdown form.

    Shared with tools/sync_posts.py (the REST-based incremental sync) so both
    ingest paths emit byte-identical files. Do not fork this function.
    """
    lines = [
        "---",
        f"title: {yaml_str(title)}",
        f"date: {iso_date or 'unknown'}",
        f"type: {ptype}",
        f"author: {yaml_str(author)}",
        f"source: {yaml_str(link)}",
    ]
    if categories:
        lines.append("categories: [" + ", ".join(
            yaml_str(c) for c in categories) + "]")
    if tags:
        lines.append("tags: [" + ", ".join(yaml_str(t) for t in tags) + "]")
    lines += ["---", "", f"# {title}", "", "<!-- Raw WordPress HTML content -->", ""]
    lines.append(body.rstrip())
    lines.append("")
    return "\n".join(lines)


def convert_item(item, stats):
    ptype = cdata(item.find("wp:post_type", NS))
    if ptype not in ("post", "page"):
        stats["skipped_type"] += 1
        return None
    status = cdata(item.find("wp:status", NS))
    if status != "publish":
        stats["skipped_status"] += 1
        return None

    title = cdata(item.find("title"))
    post_id = cdata(item.find("wp:post_id", NS))
    link = cdata(item.find("link"))
    creator = item.find("dc:creator", NS)
    author = cdata(creator) if creator is not None else ""
    date_str = cdata(item.find("wp:post_date_gmt", NS)) or cdata(
        item.find("wp:post_date", NS))
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S")
        iso_date = dt.strftime("%Y-%m-%d")
        year = dt.strftime("%Y")
    except ValueError:
        iso_date, year = "", "unknown"

    categories = []
    tags = []
    for cat in item.findall("category"):
        if cat.get("domain") == "category" and cat.get("nicename"):
            categories.append(cat.text or "")
        elif cat.get("domain") == "post_tag":
            tags.append(cat.text or "")

    body = post_body(item)
    stats["posts"] += 1

    text = render_markdown(title=title, iso_date=iso_date, ptype=ptype,
                           author=author, link=link, categories=categories,
                           tags=tags, body=body)

    slug = slugify(title)
    out_dir = os.path.join(OUT_DIR, year)
    fname = f"{iso_date or 'nodate'}-{slug}.md"
    # NOTE: the file is written by main(), after collisions are resolved.
    return {"post_id": post_id, "title": title, "date": iso_date, "year": year,
            "categories": categories, "link": link,
            "path": os.path.join(out_dir, fname),
            "words": count_len(body),
            "body_hash": hashlib.sha1(body.encode("utf-8")).hexdigest(),
            "text": text}


def main():
    files = []
    for pattern in sys.argv[1:]:
        files.extend(sorted(glob.glob(pattern)))
    if not files:
        print("no input files", file=sys.stderr)
        sys.exit(1)

    stats = {"posts": 0, "skipped_type": 0, "skipped_status": 0,
             "dup_dropped": 0, "collision_renamed": 0}
    index = []
    by_path = {}
    for fpath in files:
        print(f"parsing {fpath} ...")
        tree = ET.parse(fpath)
        for item in tree.iterfind(".//item"):
            rec = convert_item(item, stats)
            if not rec:
                continue

            prev = by_path.get(rec["path"])
            if prev is not None:
                if prev["body_hash"] == rec["body_hash"]:
                    # Same content on the same GMT date -> same file. The blog
                    # published it twice; keep one file so that file count ==
                    # post count and the catalog has no duplicate row.
                    stats["dup_dropped"] += 1
                    print(f"    duplicate dropped: post {rec['post_id']} "
                          f"== post {prev['post_id']} ({rec['title']!r}); "
                          f"kept {prev['link']}")
                    continue
                # Different content must never be silently overwritten.
                base, ext = os.path.splitext(rec["path"])
                rec["path"] = f"{base}-{rec['post_id']}{ext}"
                stats["collision_renamed"] += 1
                print(f"    collision renamed: post {rec['post_id']} -> "
                      f"{os.path.basename(rec['path'])}")

            by_path[rec["path"]] = rec
            index.append(rec)
            os.makedirs(os.path.dirname(rec["path"]), exist_ok=True)
            with open(rec["path"], "w", encoding="utf-8") as f:
                f.write(rec["text"])

    # write catalog for later wiki/index generation
    catalog_path = os.path.join(ROOT, "sources", "_catalog.tsv")
    os.makedirs(os.path.dirname(catalog_path), exist_ok=True)
    with open(catalog_path, "w", encoding="utf-8") as f:
        f.write("date\tyear\ttitle\tcategories\twords\tpath\tpost_id\n")
        for r in sorted(index, key=lambda r: (r["date"], r["title"])):
            f.write("\t".join([
                r["date"], r["year"], r["title"],
                "|".join(r["categories"]), str(r["words"]),
                os.path.relpath(r["path"], ROOT), r["post_id"]]) + "\n")

    print(f"\ndone: {len(index)} posts written, "
          f"{stats['skipped_type']} skipped (type), "
          f"{stats['skipped_status']} skipped (status), "
          f"{stats['dup_dropped']} duplicate item(s) dropped, "
          f"{stats['collision_renamed']} collision(s) renamed")
    print(f"catalog: {catalog_path} ({len(index)} rows)")


if __name__ == "__main__":
    main()
