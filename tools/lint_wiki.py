#!/usr/bin/env python3
"""Lint the wiki synthesis layer.

Checks, over wiki/pages/*.md plus wiki/index.md and wiki/overview.md:

  1. every citation link to `sources/posts/...` resolves to a real file;
  2. every internal `*.md` link resolves to a real file;
  3. every `wiki/*.md` path in the mkdocs.yml nav exists;
  4. no leftover template markers (`{{`, `TODO`, `placeholder`, ...);
  5. `sources:` frontmatter count matches the catalog for category pages;
  6. `sources/_catalog.tsv` has one row per file (no duplicate paths, no
     dangling paths) — a duplicate row silently inflates the post count;
  7. no known homoglyph / transcription typos (`TYPO_PATTERNS`).

Exits non-zero if any check fails. Run it before finishing a batch of page
edits (see wiki/schema.md -> Lint).

Usage:
    python3 tools/lint_wiki.py
"""
import csv
import datetime
import glob
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CATALOG = os.path.join(ROOT, "sources", "_catalog.tsv")
MKDS = os.path.join(ROOT, "mkdocs.yml")

LINK_RE = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")
TITLE_RE = re.compile(r"^title:\s*(.+?)\s*$", re.M)
SOURCES_RE = re.compile(r"^sources:\s*(\d+)\s*$", re.M)

# marker -> human hint
BAD_MARKERS = {
    "{{": "unrendered template",
    "TODO": "unfinished placeholder",
    "placeholder": "unfinished placeholder",
}

# Optional page-specific spellings to police: {bad: good}. Add your own, e.g.
# {"写到": "写道"} — keys should be unusual enough that they cannot
# false-positive on legitimate text (add corrections only after a real slip).
TYPO_PATTERNS = {}

SKIP_PREFIXES = ("http://", "https://", "mailto:", "#")

# Regenerated on demand by tools/gen_index.py / tools/extract_books.py, and
# deliberately absent from a fresh clone until the first ingest — links and
# nav entries pointing at them are therefore not errors.
GENERATED = ("wiki/sources.md", "wiki/overview.md", "wiki/books.md")


def is_generated(rel_path):
    """True for a path that the generators own (may legitimately be absent)."""
    rel = os.path.normpath(rel_path).replace(os.sep, "/")
    return rel in GENERATED


def category_counts():
    """map: category keyword -> number of posts carrying it (substring match)"""
    counts = {}
    if not os.path.exists(CATALOG):
        return counts
    with open(CATALOG, encoding="utf-8") as f:
        for row in csv.DictReader(f, delimiter="\t"):
            for cat in row["categories"].split("|"):
                cat = cat.strip()
                if cat:
                    counts[cat] = counts.get(cat, 0) + 1
    return counts


def count_for(keyword, counts):
    """posts whose categories mention `keyword` (e.g. 编程 -> 编程、软件、技术)"""
    return sum(n for cat, n in counts.items() if keyword in cat)


def catalog_integrity():
    """One file per post: duplicate or dangling rows inflate every count."""
    if not os.path.exists(CATALOG):
        return []  # no corpus yet (fresh clone: run the converter first)
    errors = []
    seen = {}
    with open(CATALOG, encoding="utf-8", newline="") as f:
        for lineno, row in enumerate(csv.DictReader(f, delimiter="\t"), start=2):
            path = row.get("path") or ""
            if not path:
                errors.append(f"_catalog.tsv:{lineno}: row without a path")
                continue
            if not os.path.exists(os.path.join(ROOT, path)):
                errors.append(f"_catalog.tsv:{lineno}: missing file -> {path}")
            if path in seen:
                errors.append(
                    f"_catalog.tsv:{lineno}: duplicate path {path} "
                    f"(post_id {seen[path]} and {row.get('post_id') or '?'}) "
                    f"— re-run tools/wxr_to_md.py")
            seen[path] = row.get("post_id") or "?"
    return errors


def main():
    wiki_files = sorted(glob.glob(os.path.join(ROOT, "wiki", "pages", "*.md")))
    wiki_files += [os.path.join(ROOT, "wiki", n) for n in ("index.md", "overview.md")]
    wiki_files = [f for f in wiki_files if os.path.exists(f)]

    errors = []
    n_cit = n_int = 0

    errors.extend(catalog_integrity())

    for wf in wiki_files:
        rel_wf = os.path.relpath(wf, ROOT)
        text = open(wf, encoding="utf-8").read()

        for match in LINK_RE.finditer(text):
            link = match.group(1)
            if link.startswith(SKIP_PREFIXES):
                continue
            if link.endswith(".md"):
                target = os.path.normpath(
                    os.path.join(os.path.dirname(wf), link.split("#")[0]))
                if "sources/" in link:
                    n_cit += 1
                    kind = "citation"
                else:
                    n_int += 1
                    kind = "internal link"
                if not os.path.exists(target) and not is_generated(
                        os.path.relpath(target, ROOT)):
                    errors.append(f"{rel_wf}: broken {kind} -> {link}")

        for marker, hint in BAD_MARKERS.items():
            if marker in text:
                errors.append(f"{rel_wf}: leftover {hint} ({marker!r})")

        for bad, fix in TYPO_PATTERNS.items():
            if bad in text:
                errors.append(f"{rel_wf}: typo {bad!r} -> {fix!r}")

    # page-metadata dates vs file modification time. There is no git here, so
    # mtime is the only machine-readable "when was this last touched" signal.
    # If a file was edited after its declared `updated:` date, the date was
    # almost certainly forgotten (it is hand-maintained). Compare on calendar
    # days: same-day rebuilds must not fail, only edits on a *later* day.
    for wf in wiki_files:
        header, _, _ = open(wf, encoding="utf-8").read().partition("-->")
        m = re.search(r"(?m)^updated:\s*(\d{4}-\d{2}-\d{2})\s*$", header)
        if not m:
            continue
        declared = datetime.date.fromisoformat(m.group(1))
        # created must not be later than updated (only updated is bumped).
        c = re.search(r"(?m)^created:\s*(\d{4}-\d{2}-\d{2})\s*$", header)
        if c and datetime.date.fromisoformat(c.group(1)) > declared:
            errors.append(
                f"{os.path.relpath(wf, ROOT)}: created {c.group(1)} is later "
                f"than updated {m.group(1)} — created never moves, bump updated")
        mtime = datetime.date.fromtimestamp(os.path.getmtime(wf))
        if mtime > declared:
            errors.append(
                f"{os.path.relpath(wf, ROOT)}: file modified on {mtime.isoformat()} "
                f"but page-metadata says updated: {m.group(1)} — bump the date")

    # nav paths
    if os.path.exists(MKDS):
        nav = open(MKDS, encoding="utf-8").read()
        for match in re.finditer(r":\s+(wiki/[\w./-]+\.md)\s*$", nav, re.M):
            path = match.group(1)
            if not os.path.exists(os.path.join(ROOT, path)) \
                    and not is_generated(path):
                errors.append(f"mkdocs.yml: nav target missing -> {path}")

    # sources: frontmatter vs catalog, for hub pages ("<category>总览" only —
    # sub-pages like 读书方法论 legitimately declare the number of posts they cite)
    counts = category_counts()
    for wf in glob.glob(os.path.join(ROOT, "wiki", "pages", "*.md")):
        text = open(wf, encoding="utf-8").read()
        header, _, _ = text.partition("-->")
        declared = SOURCES_RE.search(header)
        title = TITLE_RE.search(header)
        if not (declared and title and title.group(1).endswith("总览")):
            continue
        keyword = title.group(1)[:-len("总览")]
        actual = count_for(keyword, counts)
        if actual and int(declared.group(1)) != actual:
            errors.append(
                f"{os.path.relpath(wf, ROOT)}: sources: {declared.group(1)} "
                f"but catalog has {actual} posts for '{keyword}'")

    print(f"wiki files: {len(wiki_files)} | citations: {n_cit} | internal links: {n_int}")
    if errors:
        print(f"FAIL: {len(errors)} problem(s)")
        for e in errors:
            print(f"  {e}")
        return 1
    print("OK: all links resolve, no stale markers, frontmatter counts consistent")
    return 0


if __name__ == "__main__":
    sys.exit(main())
