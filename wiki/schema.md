# Blog Wiki Schema

> Pattern credit: this wiki implements Andrej Karpathy's
> [LLM Wiki](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) —
> an LLM incrementally builds and maintains a persistent wiki over raw sources.

Read `llm-wiki.md` first for the idea; this file is the working contract for
the agent that maintains *this* wiki.

## Structure

- `blog/` — the original export (WordPress WXR). **Immutable.** Gitignored:
  keep it local, it can be re-exported at any time.
- `sources/posts/<YYYY>/` — one markdown file per post, converted by
  `tools/wxr_to_md.py` (backfill) or `tools/sync_posts.py` (incremental).
  **Immutable. Do not edit.** Frontmatter: title, date, categories, source URL.
- `sources/_catalog.tsv` — tab-separated catalog of all posts (date, year,
  title, categories, words, path, post_id). **Generated, gitignored.**
  **Invariant: one row per file** — its row count must equal the number of
  `sources/posts/**/*.md` files. A duplicate row silently inflates every count
  derived from it (post total, per-year table, `overview.md` word counts);
  `gen_index.py` and `lint_wiki.py` both fail loudly on a duplicate path.
  If one shows up, re-run the converter rather than hand-editing the TSV.
- `wiki/` — the LLM-owned knowledge layer:
  - `overview.md` — blog-wide stats (posts/year, categories). **Generated.**
  - `index.md` — curated index (hand-maintained, links the topic pages).
  - `sources.md` — full catalog by year. **Generated.**
  - `books.md` — book index derived from book-catalog links in post bodies.
    **Generated** (needs `BOOKS_BASE` in `config.py`; optional).
  - `schema.md` — this file.
  - `log.md` — chronological record of wiki operations, newest entry first.
    Entries record **what changed, how it was verified, and what is next** —
    not the discussion that produced it.
- `index.md` (repo root) — the public landing page, hand-maintained. No script
  may generate or overwrite it; `build_site.py` only copies it.
- `assets/` — static files referenced by `mkdocs.yml` (logo, css, favicon).
  `build_site.py` stages exactly the files `mkdocs.yml` points at, so the repo
  ships only what it references.
- `tools/` — helper scripts (`wxr_to_md.py`, `sync_posts.py`, `digest.py`,
  `gen_index.py`, `extract_books.py`, `lint_wiki.py`, `build_site.py`,
  `deploy.sh`). Site-specific settings live in `config.py` (gitignored; copy
  `config.example.py`) or `LLMWIKI_*` environment variables — never in the
  scripts.

## Generated vs. tracked

`overview.md`, `sources.md`, `books.md`, `_catalog.tsv`, `_books.tsv` are all
**generated artifacts** and are gitignored: they describe *your* corpus, not
the tooling. A fresh clone generates them on first run:

```bash
python3 tools/wxr_to_md.py     # corpus + _catalog.tsv  (needs blog/ WXR)
python3 tools/sync_posts.py    # or fetch incrementally from the live blog
python3 tools/gen_index.py     # overview.md + sources.md
python3 tools/extract_books.py # books.md + _books.tsv (optional)
```

## Conventions for synthesis pages

- Filename: `wiki/pages/<topic>.md`, one topic per page (kebab-case or native
  script titles both fine).
- Every claim taken from a post cites that post as a relative link to the file
  under `sources/posts/...` (with the post date).
- Page metadata goes in an HTML comment so it never renders, with `title`,
  `created`, `updated`, `sources`:

  ```markdown
  <!-- page-metadata
  title: 读书总览
  created: 2026-01-01
  updated: 2026-01-02
  sources: 262
  -->
  ```

  - **Date discipline**: when creating a page write `created` and `updated`
    identically; afterwards bump **only** `updated`, never `created`.
    `lint_wiki.py` catches a forgotten bump by comparing mtime with `updated`.
  - `sources` = the number of corpus posts in the page's cluster (i.e. how many
    catalog rows match its category keyword) — **not** the number of citation
    links in the body. Compute it, don't guess:

    ```bash
    python3 -c "import csv;rows=list(csv.DictReader(open('sources/_catalog.tsv'),delimiter='\t'));print(sum(1 for r in rows if '游记' in r['categories']))"
    ```

  - A hub page must be titled `<category>总览` for the count check to match it;
    a differently-named page legitimately declares the count of posts it cites.
- A "local citations" block lists the posts cited on the page;
  `build_site.py` rewrites those links to the original blog URLs at publish
  time, so the public site never exposes the local `sources/` tree.
- **Numeric claims must be verified, not estimated.** Word counts, per-year
  post counts and totals all live in `sources/_catalog.tsv`. Never invent
  titles: every post named in a timeline must exist in the catalog.
- Cross-link related pages with markdown links; citations use a page-relative
  path such as `../../sources/posts/2024/2024-01-01-example.md`.

## Lint

Run before finishing a batch of page edits:

```bash
python3 tools/lint_wiki.py
```

It checks that every citation / internal link resolves, that no template
marker is left behind, that `sources:` counts match the catalog for hub pages,
that `_catalog.tsv` has exactly one row per file, and that page dates are
honest. Add your own `TYPO_PATTERNS` to it as you find slips.