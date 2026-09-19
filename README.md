# llm-wiki — build a personal wiki from your blog archive

A working implementation of Andrej Karpathy's
[LLM Wiki](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f)
pattern (copied verbatim as [`llm-wiki.md`](llm-wiki.md)):

> Instead of retrieving from raw documents at query time, an LLM **incrementally
> builds and maintains a persistent wiki** — a structured, interlinked
> collection of markdown files that sits between you and the raw sources.

**Bring your own blog archive.** This repository contains only the tooling,
the conventions and the site skeleton — no posts, no synthesized pages, no
personal settings. You point it at your own WordPress export (or live blog)
and let an LLM agent maintain the wiki.

## How it works

```
blog/WordPress.*.xml            your export (local, gitignored)
        │  tools/wxr_to_md.py            backfill: XML -> markdown
        │  tools/sync_posts.py           delta:    REST API -> markdown
        ▼
sources/posts/<YYYY>/*.md       immutable corpus + sources/_catalog.tsv
        │  tools/digest.py               plain-text digests for the LLM
        ▼
wiki/pages/*.md                 the wiki: LLM-written, hand-reviewed pages
        │  tools/gen_index.py            overview.md + sources.md
        │  tools/extract_books.py        books.md (optional book index)
        │  tools/lint_wiki.py            the gate: links, counts, dates
        ▼
site/                           tools/build_site.py -> MkDocs -> publish
```

Three layers, deliberately separated:

| Layer | Who owns it | In git? |
|---|---|---|
| `sources/` — converted posts | the converter, **never edited** | your call (ignored by default) |
| `wiki/` — synthesis pages | the LLM (+ your review) | **yes** — this is the knowledge |
| `wiki/overview.md`, `sources.md`, `books.md`, `_catalog.tsv` | generators | **no** — regenerate |

Citations in `wiki/` point at local files (`../../sources/posts/2024/x.md`)
so the LLM can verify every claim, and `build_site.py` rewrites them to the
original blog URLs when publishing — so your raw corpus and your blog export
never end up on the public site.
## Quick start

Requires Python 3.9+ (3.11+ recommended).

```bash
git clone <this repo> my-wiki && cd my-wiki
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

cp config.example.py config.py      # blog URL, book catalog, mail (optional)
# then edit config.py
```

### 1. Ingest your posts

Either from a WordPress export (full backfill):

```bash
mkdir -p blog && cp /path/to/WordPress.*.xml blog/
python3 tools/wxr_to_md.py          # -> sources/posts/**/*.md + _catalog.tsv
```

…or incrementally from the live blog (needs the REST API open, and
`BLOG_URL` in `config.py`):

```bash
python3 tools/sync_posts.py --dry-run     # report what is new
python3 tools/sync_posts.py               # fetch + refresh + validate
```

`sync_posts.py` is **stage A: fetch only** — it never writes prose. It leaves a
worklist in `inbox/<date>.md` listing the new posts and candidate hub pages.

### 2. Generate the derived indexes

```bash
python3 tools/gen_index.py            # wiki/overview.md + wiki/sources.md
python3 tools/extract_books.py        # wiki/books.md  (needs BOOKS_BASE)
```

### 3. Build the wiki with your LLM agent

This is **stage B**, and it is deliberately not automated: open your agent
(e.g. Claude Code, Codex, an IDE assistant) in this repo and ask it to work
through the worklist, then have it read [`wiki/schema.md`](wiki/schema.md) —
that file is the contract (page metadata, citation format, how `sources:`
counts are computed, when to bump `updated`).

Typical session prompt:

> Read `wiki/schema.md` and `inbox/2026-09-19.md`. Update the affected hub
> pages from the new posts, verify every number against
> `sources/_catalog.tsv`, add citations, then run lint and the build.

Feed it `tools/digest.py` output when a batch is too large to read file by
file:

```bash
python3 tools/digest.py 读书 --limit 60 --min-chars 400 > /tmp/digest.txt
```

The digest strips WordPress HTML but **keeps links** (including book-catalog
links), so URLs survive into the synthesis.

### 4. Validate and publish

```bash
python3 tools/lint_wiki.py            # gate: links, markers, counts, dates
python3 tools/build_site.py --serve   # preview on http://0.0.0.0:8001
python3 tools/build_site.py           # one-shot build into site/
tools/deploy.sh --dry-run             # rsync preview (needs WIKI_SSH_HOST)
tools/deploy.sh                       # build + sync + checksum verify
```

`build_site.py` runs MkDocs in `--strict` mode, so a green build is a real
check on internal links, not a formality.

## Tools

| Tool | Purpose |
|---|---|
| `tools/wxr_to_md.py` | Convert a WordPress WXR export into `sources/posts/` + `_catalog.tsv` |
| `tools/sync_posts.py` | Fetch new/edited posts via the REST API; writes the `inbox/` worklist |
| `tools/digest.py` | Plain-text digest of posts (by category/title/words) for LLM context |
| `tools/gen_index.py` | Generate `wiki/overview.md` (stats) and `wiki/sources.md` (catalog) |
| `tools/extract_books.py` | Build the book index (`wiki/books.md`) from book links in posts |
| `tools/lint_wiki.py` | Validation gate over the wiki layer |
| `tools/build_site.py` | Stage the public layer and run MkDocs (build or serve) |
| `tools/deploy.sh` | rsync `site/` to your host, then verify with checksums |
| `tools/site_config.py` | Loads `config.py` / `LLMWIKI_*` env vars for the tools above |

## Configuration

`config.py` (gitignored — copy from `config.example.py`) or environment
variables:

| Setting | Env var | Meaning |
|---|---|---|
| `BLOG_URL` | `LLMWIKI_BLOG_URL` | Source blog, e.g. `https://blog.example.com` |
| `BOOKS_BASE` | `LLMWIKI_BOOKS_BASE` | Book catalog prefix, e.g. `https://example.com/books` (posts link `.../books/02072.html`) |
| `USER_AGENT` | `LLMWIKI_USER_AGENT` | User-Agent used when fetching |
| `MAIL_HOST`, `MAIL_PORT`, `MAIL_USER`, `MAIL_PASS`, `MAIL_FROM` | `LLMWIKI_MAIL_*` | SMTP relay for `sync_posts.py --notify`; leave `MAIL_HOST` empty to disable |
| — | `LLMWIKI_MKDOCS` | Path to the `mkdocs` executable, if not in `.venv` or `$PATH` |

Deployment uses `WIKI_SSH_HOST`, `WIKI_SSH_USER`, `WIKI_SSH_PORT`,
`WIKI_REMOTE_DIR`, `WIKI_SITE_URL`.

### Customising the site

- `mkdocs.yml` — `site_name`, `site_url`, `nav`, theme, optional `copyright`.
- `assets/` — `logo.svg`, `favicon.ico`, `stylesheets/extra.css`. Only files
  referenced by `mkdocs.yml` are shipped; drop the `extra_css:` entry and the
  stylesheet if you have no logo to size.
- `wiki/index.md` and the root `index.md` — your landing pages (hand-written).

## What stays private

`.gitignore` keeps your data out of the repository by default: `blog/`,
`inbox/`, `sources/posts/`, `sources/_sync_state.json`, `config.py`, plus the
generated `wiki/overview.md`, `wiki/sources.md`, `wiki/books.md`,
`sources/_catalog.tsv` and `sources/_books.tsv`.

Flip `sources/posts/` back into version control by deleting that one line if
you want the corpus committed too — then `lint_wiki.py` can verify citations
from a fresh clone. Either way, `build_site.py` publishes only the wiki layer.

## License

MIT for the tooling (see [LICENSE.md](LICENSE.md)). Content you generate is
yours. `llm-wiki.md` is a verbatim copy of Karpathy's pattern file.
