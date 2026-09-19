#!/usr/bin/env python3
"""Incrementally fetch new posts from your blog into sources/posts/.

Configure the blog URL in config.py (see config.example.py) or via the
LLMWIKI_BLOG_URL environment variable.

This is **stage A** of the sync pipeline: FETCH ONLY. It never writes
synthesis prose. It appends raw sources, refreshes the derived catalog and
indexes, runs the validation gate, and leaves a worklist under `inbox/` for a
human+LLM session to synthesize from (stage B, done by an agent, because
synthesis cannot be safely automated -- see wiki/schema.md).

Usage:
    python3 tools/sync_posts.py               # fetch, then gen_index/lint/build
    python3 tools/sync_posts.py --dry-run     # report only, change nothing
    python3 tools/sync_posts.py --no-build    # fetch only, skip the gate
    python3 tools/sync_posts.py --window 90   # widen the re-scan window (days)

Why the REST API and not the WXR export: the WXR is a full snapshot, used for
backfill by `tools/wxr_to_md.py`. `/wp-json/wp/v2/posts` supports `after=` for
delta detection and reports `x-wp-total`, so a cron run costs a few requests.
Bodies are rendered through `wxr_to_md.render_markdown()` so that both ingest
paths stay byte-compatible. Do not fork that renderer.

State lives in `sources/_sync_state.json`: the date cursor plus a
`post_id -> modified_gmt` map, which is how upstream *edits* (not just new
posts) get surfaced. Edits are reported, never rewritten -- `sources/` is
append-only.
"""
import argparse
import csv
import html
import json
import os
import re
import smtplib
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from email.utils import format_datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wxr_to_md  # noqa: E402  shared renderer/helpers: single source of truth
import site_config  # noqa: E402  site-specific settings live in config.py / env

ROOT = wxr_to_md.ROOT
SITE = str(site_config.get("BLOG_URL")).rstrip("/")
API = f"{SITE}/wp-json/wp/v2"
UA = str(site_config.get("USER_AGENT"))
CATALOG = os.path.join(ROOT, "sources", "_catalog.tsv")
STATE = os.path.join(ROOT, "sources", "_sync_state.json")
INBOX_DIR = os.path.join(ROOT, "inbox")
MAX_ATTEMPTS = 3

# Mail notification for cron runs. Configured in config.py (gitignored) or
# via LLMWIKI_MAIL_* env vars; with MAIL_HOST empty, --notify is a no-op.
MAIL_HOST = str(site_config.get("MAIL_HOST"))
MAIL_PORT = int(site_config.get("MAIL_PORT"))
MAIL_USER = str(site_config.get("MAIL_USER"))
MAIL_PASS = str(site_config.get("MAIL_PASS"))
MAIL_FROM = str(site_config.get("MAIL_FROM") or MAIL_USER)


def send_mail(to, subject, body):
    if not MAIL_HOST:
        raise RuntimeError("mail is not configured: set MAIL_HOST (and the "
                           "other MAIL_* values) in config.py, or drop "
                           "--notify")
    msg = EmailMessage()
    msg["From"] = MAIL_FROM
    msg["To"] = to
    msg["Subject"] = subject
    msg["Message-ID"] = f"<{uuid.uuid4()}@{MAIL_HOST}>"
    msg["Date"] = format_datetime(datetime.now(timezone.utc))
    msg.set_content(body)
    with smtplib.SMTP(MAIL_HOST, MAIL_PORT) as smtp:
        smtp.starttls()
        smtp.login(MAIL_USER, MAIL_PASS)
        smtp.send_message(msg)


def notify_new_posts(email, new):
    """One line per new post (title + uri), then the rebuild command."""
    lines = [f"{r['title']} — {r['link']}" for r in new]
    lines.append(f"cd {ROOT} && {sys.executable} tools/build_site.py")
    send_mail(email, f"[llm-wiki] {len(new)} new post(s) from {SITE}",
              "\n".join(lines))

# WP slugs are usually URL-safe ASCII, but non-ASCII slugs come back
# percent-encoded (e.g. %e7%bb%b4%e7%93%a6%e5%b0%94%e7%ac%ac) -- those are not
# usable as filenames, so fall back to the title slug like the WXR path does.
SAFE_SLUG = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
HTML_TAG = re.compile(r"<[^>]+>")


def api_get(resource, params, timeout=30):
    """GET an API resource, retrying with backoff. Returns (data, total_pages)."""
    url = f"{API}/{resource}?" + urllib.parse.urlencode(params)
    last = None
    for attempt in range(MAX_ATTEMPTS):
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": UA, "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = json.loads(r.read().decode("utf-8"))
                return data, int(r.headers.get("X-WP-TotalPages") or 1)
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError,
                ValueError) as exc:
            last = exc
            if attempt < MAX_ATTEMPTS - 1:
                time.sleep(2 ** attempt)
    raise SystemExit(f"sync: GET failed after {MAX_ATTEMPTS} attempts: {url}\n"
                     f"  {last}")


def api_all(resource, params):
    """Follow x-wp-totalpages and return every item."""
    items, page = [], 1
    while True:
        batch, total_pages = api_get(resource, dict(params, page=page,
                                                    per_page=100))
        items.extend(batch)
        if page >= total_pages or not batch:
            return items
        page += 1
        time.sleep(0.3)  # be a polite client; the host throttles bursts


def id_name_map(resource, fields="id,name"):
    return {str(r["id"]): r[fields.split(",")[1]]
            for r in api_all(resource, {"_fields": fields})}


def plain_text(rendered):
    """REST returns HTML entities in titles; WXR titles were plain CDATA."""
    return html.unescape(HTML_TAG.sub("", rendered or "")).strip()


def read_catalog():
    with open(CATALOG, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f, delimiter="\t"))


def write_catalog(rows):
    """Same shape and ordering as tools/wxr_to_md.py writes."""
    with open(CATALOG, "w", encoding="utf-8") as f:
        f.write("date\tyear\ttitle\tcategories\twords\tpath\tpost_id\n")
        for r in sorted(rows, key=lambda r: (r["date"], r["title"])):
            f.write("\t".join([
                r["date"], r["year"], r["title"], r["categories"],
                r["words"], r["path"], r["post_id"]]) + "\n")


def load_state():
    if os.path.exists(STATE):
        with open(STATE, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_state(state):
    with open(STATE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")


def hub_keywords():
    """{hub page name: keyword} from the `<X>总览` pages in wiki/index.md."""
    index = os.path.join(ROOT, "wiki", "index.md")
    hubs = {}
    if os.path.exists(index):
        for name in re.findall(r"\[([^\]]+?总览)\]", open(index, encoding="utf-8").read()):
            hubs[name] = name[:-len("总览")]
    return hubs


def suggest_hubs(cats, hubs):
    text = "、".join(cats)
    hits = [name for name, kw in hubs.items() if kw and kw in text]
    return hits


def build_inbox(added, edited, moved, hubs):
    """A worklist for the synthesis session (stage B). Not published."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    lines = [
        f"# Sync worklist {today}",
        "",
        "Generated by `tools/sync_posts.py`. **These sources are fetched but not",
        "synthesized.** No topic page reflects them yet. Stage B (an agent",
        "session) must read each post, update the relevant hub pages, verify",
        "every numeric claim against `sources/_catalog.tsv`, then log and rebuild.",
        "",
    ]
    if added:
        lines += [f"## New posts ({len(added)})", ""]
        for r in added:
            hits = suggest_hubs(r["categories"], hubs)
            lines += [
                f"- **{r['title']}** — {r['date']} · {r['words']} words",
                f"  - source: {r['link']}",
                f"  - categories: {', '.join(r['categories']) or '—'}",
                f"  - tags: {', '.join(r['tags']) or '—'}",
                f"  - local: `{r['path']}`",
                f"  - candidate hubs: {', '.join(hits) if hits else '_none — new topic?_'}",
            ]
        lines.append("")
        gaps = sorted({c for r in added for c in r["categories"]
                       if not suggest_hubs([c], hubs)})
        if gaps:
            lines += ["## Categories with no hub page", "",
                      ", ".join(gaps), "",
                      "These posts have nowhere to land yet; consider a new hub.",
                      ""]
    if edited:
        lines += [f"## Edited upstream ({len(edited)}) — report only", "",
                  "`sources/` is append-only, so these files were **not** "
                  "rewritten. The wiki may now describe an older revision.",
                  ""]
        for r in edited:
            lines.append(f"- post {r['post_id']} — {r['title']} "
                         f"(modified {r['modified_gmt']})")
        lines.append("")
    if moved:
        lines += [f"## Moved upstream, baseline recorded ({len(moved)})", "",
                  "First observation of a change to these posts: their "
                  "`modified_gmt` is now recorded, so a future change will be "
                  "reported as confirmed drift. Not rewritten — `sources/` is "
                  "append-only.",
                  ""]
        for r in moved:
            lines.append(f"- post {r['post_id']} — {r['title']} "
                         f"(modified {r['modified_gmt']})")
        lines.append("")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description="Fetch new blog posts (stage A).")
    ap.add_argument("--dry-run", action="store_true",
                    help="report what would be fetched, write nothing")
    ap.add_argument("--no-build", action="store_true",
                    help="skip gen_index / lint / build")
    ap.add_argument("--notify", metavar="EMAIL", default=None,
                    help="email this address when new posts are ingested "
                         "(for the cron job)")
    ap.add_argument("--window", type=int, default=30,
                    help="re-scan this many days before the newest known post "
                         "(default 30) to survive back-dated publishing")
    args = ap.parse_args()

    rows = read_catalog()
    known = {r["post_id"]: r for r in rows}
    state = load_state()
    tracked = dict(state.get("modified_gmt", {}))
    newest = max((r["date"] for r in rows if r["date"]), default="2004-01-01")
    since = (datetime.strptime(newest, "%Y-%m-%d")
             - timedelta(days=args.window)).strftime("%Y-%m-%dT%H:%M:%S")
    print(f"catalog: {len(rows)} posts | newest {newest} | fetching after {since}")

    cats = id_name_map("categories")
    users = id_name_map("users", "id,slug")
    print(f"resolved {len(cats)} categories, {len(users)} authors")

    posts = api_all("posts", {
        "after": since, "orderby": "date", "order": "asc",
        "_fields": "id,date_gmt,modified_gmt,slug,link,title,author,"
                   "categories,tags,content",
    })
    print(f"API returned {len(posts)} post(s) in window")

    # Resolve only the tags these posts actually use. Paginating the whole tag
    # table is ~15 requests and grows forever; `include=` is one.
    want = sorted({str(t) for p in posts for t in p.get("tags", [])})
    tags = {}
    if want:
        for chunk in range(0, len(want), 100):
            batch, _ = api_get("tags", {"include": ",".join(want[chunk:chunk + 100]),
                                        "per_page": 100, "_fields": "id,name"})
            tags.update({str(t["id"]): t["name"] for t in batch})
    print(f"resolved {len(tags)} tag(s) in use")

    # Upstream edits need a *separate* query: `after=` filters on publication
    # date, so a 2020 post edited today never appears in it. `modified_after=`
    # catches those, which is how the wiki learns it is describing a stale
    # revision. One day of overlap is deliberate; the comparison dedupes.
    #
    # Baselines are learned lazily rather than bulk-seeded: WXR-backfilled posts
    # have no recorded `modified_gmt`, and paginating all 1654 of them on every
    # run (or once, in one fragile burst) is both slow and unnecessary. The
    # first time a post shows up here we record its baseline and report it as a
    # move; from the next occurrence we can state precisely that it differs.
    edited, moved = [], []
    last_sync = state.get("last_sync_utc")
    if last_sync:
        mark = (datetime.strptime(last_sync, "%Y-%m-%dT%H:%M:%SZ")
                - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S")
        for p in api_all("posts", {
                "modified_after": mark, "orderby": "modified", "order": "desc",
                "_fields": "id,date_gmt,modified_gmt,slug,link,title"}):
            pid = str(p["id"])
            if pid not in known:
                continue
            rec = {"post_id": pid,
                   "title": plain_text(p["title"]["rendered"]),
                   "modified_gmt": p["modified_gmt"]}
            base = tracked.get(pid)
            if base is None:
                tracked[pid] = p["modified_gmt"]  # learn the baseline
                moved.append(rec)
            elif base != p["modified_gmt"]:
                edited.append(rec)
        if edited:
            print(f"detected {len(edited)} post(s) edited upstream")
        if moved:
            print(f"{len(moved)} post(s) moved upstream (baseline recorded)")
    else:
        print("no previous sync state: seeding edit tracking (edits will be "
              "reported from the next run)")

    edited_ids = {e["post_id"] for e in edited}
    new, taken = [], {r["path"] for r in rows}
    for p in posts:
        pid = str(p["id"])
        if pid in known:
            base = tracked.get(pid)
            if base is None:
                tracked[pid] = p["modified_gmt"]
            elif base != p["modified_gmt"] and pid not in edited_ids:
                edited.append({"post_id": pid,
                               "title": plain_text(p["title"]["rendered"]),
                               "modified_gmt": p["modified_gmt"]})
                edited_ids.add(pid)
            continue

        date_gmt = p["date_gmt"] or ""
        iso_date = date_gmt[:10]
        year = iso_date[:4] or "unknown"
        slug = (p.get("slug") or "").strip()
        if not SAFE_SLUG.match(slug):
            slug = wxr_to_md.slugify(plain_text(p["title"]["rendered"]))
        title = plain_text(p["title"]["rendered"])
        body = (p.get("content") or {}).get("rendered") or ""

        path = os.path.join(wxr_to_md.OUT_DIR, year,
                            f"{iso_date or 'nodate'}-{slug}.md")
        rel = os.path.relpath(path, ROOT)
        if rel in taken:  # never overwrite: disambiguate, as wxr_to_md does
            path = path[:-3] + f"-{pid}.md"
            rel = os.path.relpath(path, ROOT)
        taken.add(rel)

        cat_names = [cats.get(str(c), str(c)) for c in p.get("categories", [])]
        tag_names = [tags[str(t)] for t in p.get("tags", []) if str(t) in tags]

        text = wxr_to_md.render_markdown(
            title=title, iso_date=iso_date, ptype="post",
            author=users.get(str(p.get("author")), ""), link=p["link"],
            categories=cat_names, tags=tag_names, body=body)

        rec = {"post_id": pid, "title": title, "date": iso_date, "year": year,
               "categories": cat_names, "tags": tag_names, "link": p["link"],
               "path": rel, "words": wxr_to_md.count_len(body),
               "modified_gmt": p["modified_gmt"], "text": text}
        new.append(rec)
        print(f"  + {iso_date} {title}  ({rel})")

    if not new and not edited and not moved:
        print("nothing new: wiki is up to date")
        return 0

    if args.dry_run:
        print(f"\ndry run: would add {len(new)}, would report {len(edited)} "
              f"edited upstream, {len(moved)} moved (baseline)")
        return 0

    for rec in new:
        full = os.path.join(ROOT, rec["path"])
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w", encoding="utf-8") as f:
            f.write(rec["text"])

    for rec in new:
        rows.append({"date": rec["date"], "year": rec["year"],
                     "title": rec["title"],
                     "categories": "|".join(rec["categories"]),
                     "words": str(rec["words"]), "path": rec["path"],
                     "post_id": rec["post_id"],
                     "modified_gmt": rec["modified_gmt"]})
    write_catalog(rows)

    new_ids = {n["post_id"] for n in new}
    state["last_sync_utc"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    state["last_post_date_gmt"] = max(r["date"] for r in rows if r["date"])
    for r in rows:  # seed from whatever the catalog knows (newest is newest)
        if r.get("modified_gmt") and r["post_id"] not in new_ids:
            tracked.setdefault(r["post_id"], r["modified_gmt"])
    for n in new:
        tracked[n["post_id"]] = n["modified_gmt"]
    state["modified_gmt"] = tracked
    save_state(state)

    os.makedirs(INBOX_DIR, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    inbox = os.path.join(INBOX_DIR, f"{stamp}.md")
    with open(inbox, "w", encoding="utf-8") as f:
        f.write(build_inbox(new, edited, moved, hub_keywords()))
    print(f"\nadded {len(new)} post(s), catalog now {len(rows)} rows")
    print(f"state: {os.path.relpath(STATE, ROOT)}")
    print(f"worklist: {os.path.relpath(inbox, ROOT)}  (stage B: synthesize)")

    if args.notify and new:
        try:
            notify_new_posts(args.notify, new)
            print(f"notified: {args.notify}")
        except Exception as exc:  # never fail the sync over mail
            print(f"notify failed: {exc}", file=sys.stderr)

    if not args.no_build:
        sys.stdout.flush()
        print("\n>>> running the validation gate")
        for script in ("gen_index.py", "lint_wiki.py", "build_site.py"):
            print(f"--- {script}")
            sys.stdout.flush()
            rc = os.system(f'cd "{ROOT}" && "{sys.executable}" '
                           f'"tools/{script}"')
            if rc != 0:
                print(f"\nsync: tools/{script} failed (exit {rc >> 8}).",
                      file=sys.stderr)
                if script == "lint_wiki.py":
                    print("Expected after an ingest that lands in a hub's "
                          "category: the hub's `sources:` count and prose are "
                          "now stale. That is stage B's job (see the "
                          "worklist). The site build and deploy are "
                          "deliberately withheld so the published wiki stays "
                          "self-consistent.", file=sys.stderr)
                return rc >> 8
    return 0


if __name__ == "__main__":
    sys.exit(main())
