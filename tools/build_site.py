#!/usr/bin/env python3
"""Stage a public build of the wiki and run MkDocs.

Publishes ONLY the wiki layer (wiki/ + root index.md). Raw posts in
sources/ stay local; citation links of the form

    ../sources/posts/<year>/<file>.md

are rewritten to the post's original blog URL (from its frontmatter
`source:` field), so citations still resolve on the public site.

Usage:
    python3 tools/build_site.py                          # build to site/
    python3 tools/build_site.py --serve                   # preview on 0.0.0.0:8001
    python3 tools/build_site.py --serve --port 9001       # pick another port
    python3 tools/build_site.py --serve --host 127.0.0.1   # localhost only

The preview server binds all interfaces by default so the draft can be
reviewed from other devices on the LAN; the reachable URLs are printed.
"""
import argparse
import glob
import os
import re
import shutil
import socket
import subprocess

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STAGE = os.path.join(ROOT, "docs")
MKDS = os.path.join(ROOT, "mkdocs.yml")
# MkDocs from the project venv if present, else $LLMWIKI_MKDOCS, else PATH.
MKDOCS = os.environ.get("LLMWIKI_MKDOCS",
                        os.path.join(ROOT, ".venv", "bin", "mkdocs"))
if not os.path.exists(MKDOCS):
    MKDOCS = shutil.which("mkdocs") or ""
if not MKDOCS:
    raise SystemExit(
        "build_site: mkdocs not found — create the venv and install the "
        "requirements (.venv/bin/pip install -r requirements.txt), or point "
        "LLMWIKI_MKDOCS at the executable")

FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n", re.S)
SOURCE_RE = re.compile(r'^source:\s*"(.*?)"\s*$', re.M)
# matches links such as ../sources/posts/2007/x.md or ../../sources/posts/2007/x.md
LINK_RE = re.compile(r"(?:\.\./)+sources/(posts/[^)\s]+?\.md)")

DEFAULT_SERVE_HOST = "0.0.0.0"
DEFAULT_SERVE_PORT = 8001


def lan_addresses():
    """Best-effort list of this machine's non-loopback IPv4 addresses."""
    ips = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.add(info[4][0])
    except OSError:
        pass
    try:  # address of the interface used for egress traffic
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            probe.connect(("8.8.8.8", 80))
            ips.add(probe.getsockname()[0])
        finally:
            probe.close()
    except OSError:
        pass
    return sorted(ip for ip in ips if not ip.startswith("127."))


def port_is_free(host, port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
        except OSError:
            return False
    return True


def pick_port(host, port, span=20):
    """Return `port` if free, else the next free port after it."""
    for candidate in range(port, port + span):
        if port_is_free(host, candidate):
            if candidate != port:
                print(f"port {port} is in use -> falling back to {candidate}")
            return candidate
    raise SystemExit(f"no free port in range {port}-{port + span - 1}")


def build_link_map():
    """map: posts/<year>/<file>.md  ->  original blog URL"""
    links = {}
    for path in glob.glob(os.path.join(ROOT, "sources", "posts", "*", "*.md")):
        with open(path, encoding="utf-8") as f:
            head = f.read(3000)
        fm = FRONTMATTER_RE.match(head)
        if not fm:
            continue
        m = SOURCE_RE.search(fm.group(1))
        if m:
            key = os.path.relpath(path, os.path.join(ROOT, "sources"))
            links[key] = m.group(1)
    return links


def mask_code(text: str) -> str:
    """Blank out fenced code blocks and inline code spans (same length, spaces).

    Documentation legitimately shows example paths such as
    `../../sources/posts/2024/2024-01-01-example.md`; those must not be
    mistaken for real citations (rewritten or counted as unresolved).
    """
    masked = re.sub(r"`[^`\n]*`", lambda m: " " * (m.end() - m.start()), text)
    lines = masked.splitlines(keepends=True)
    in_fence = False
    for i, line in enumerate(lines):
        stripped = line.lstrip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_fence = not in_fence
            lines[i] = " " * (len(line) - 1) + ("\n" if line.endswith("\n") else "")
        elif in_fence:
            lines[i] = " " * (len(line) - 1) + ("\n" if line.endswith("\n") else "")
    return "".join(lines)


def rewrite(text, links, stats):
    mask = mask_code(text)

    def sub(match):
        if not mask[match.start():match.end()].strip():
            return match.group(0)  # inside code: documentation, leave alone
        url = links.get(match.group(1))
        if url:
            stats["rewritten"] += 1
            return url
        stats["unresolved"] += 1
        return match.group(0)
    return LINK_RE.sub(sub, text)


def with_date_footer(text: str) -> str:
    """Append a visible creation/last-update line to pages carrying a
    page-metadata block. Dates live in the (HTML-comment) metadata, which
    visitors never see; this surfaces them. Pages without the block (auto
    generated overview/sources.md) are left untouched."""
    m = re.search(r"<!--\s*page-metadata(.*?)-->", text, re.S)
    if not m:
        return text
    meta = m.group(1)
    created = re.search(r"(?m)^created:\s*(\S+)", meta)
    updated = re.search(r"(?m)^updated:\s*(\S+)", meta)
    if not (created or updated):
        return text
    parts = []
    if created:
        parts.append(f"创建于 {created.group(1)}")
    if updated and (not created or updated.group(1) != created.group(1)):
        parts.append(f"最后更新于 {updated.group(1)}")
    return text.rstrip() + f"\n\n---\n*本页{'，'.join(parts)}。*\n"


def main():
    parser = argparse.ArgumentParser(
        description="Stage the public wiki layer and build it with MkDocs.")
    parser.add_argument("--serve", action="store_true",
                        help="run a live preview server instead of a one-shot build")
    parser.add_argument("--host", default=DEFAULT_SERVE_HOST,
                        help=f"preview bind address (default: {DEFAULT_SERVE_HOST})")
    parser.add_argument("--port", type=int, default=DEFAULT_SERVE_PORT,
                        help=f"preview port (default: {DEFAULT_SERVE_PORT})")
    args = parser.parse_args()

    links = build_link_map()
    print(f"indexed {len(links)} post permalinks")

    if os.path.isdir(STAGE):
        shutil.rmtree(STAGE)
    os.makedirs(STAGE)

    stats = {"rewritten": 0, "unresolved": 0}
    n_pages = 0

    # wiki/ synthesis layer
    for src in glob.glob(os.path.join(ROOT, "wiki", "**", "*.md"), recursive=True):
        rel = os.path.relpath(src, ROOT)
        dst = os.path.join(STAGE, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        with open(src, encoding="utf-8") as f:
            text = f.read()
        with open(dst, "w", encoding="utf-8") as f:
            f.write(rewrite(with_date_footer(text), links, stats))
        n_pages += 1

    # root landing page
    shutil.copy(os.path.join(ROOT, "index.md"), os.path.join(STAGE, "index.md"))

    # Static assets referenced from mkdocs.yml (theme.favicon / theme.logo /
    # extra_css) are mirrored into docs/ so those references stay valid. The
    # list comes from mkdocs.yml itself, so the repo ships only what it
    # actually references. A missing one must fail the build rather than
    # silently ship a broken header or an unstyled page -- MkDocs does NOT
    # fail when theme.logo/theme.favicon is missing; it happily emits an <img>
    # pointing at a 404, so this check is the only thing between a rename and
    # a broken site.
    with open(os.path.join(ROOT, "mkdocs.yml"), encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    refs = []
    theme_cfg = cfg.get("theme")
    if isinstance(theme_cfg, dict):
        for key in ("favicon", "logo"):
            if theme_cfg.get(key):
                refs.append(theme_cfg[key])
    refs.extend(cfg.get("extra_css") or [])
    for rel in refs:
        src = os.path.join(ROOT, rel)
        if not os.path.exists(src):
            raise SystemExit(f"build_site: mkdocs.yml refers to {rel}, which "
                             f"does not exist in the repo")
        dst = os.path.join(STAGE, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy(src, dst)
        print(f"asset: {rel} -> docs/{rel}")
    print(f"references: {len(refs)} mkdocs.yml asset reference(s) verified")

    print(f"staged {n_pages} wiki pages -> docs/")
    print(f"citation links: {stats['rewritten']} rewritten to blog URLs, "
          f"{stats['unresolved']} left unresolved")

    if args.serve:
        port = pick_port(args.host, args.port)
        print(f"serving on {args.host}:{port}")
        print(f"  local: http://127.0.0.1:{port}/")
        if args.host in ("0.0.0.0", "::"):
            for ip in lan_addresses():
                print(f"  LAN:   http://{ip}:{port}/")
            print("  (unreachable from other devices? open the port in this host's firewall)")
        cmd = [MKDOCS, "serve", "-f", MKDS, "-a", f"{args.host}:{port}"]
    else:
        cmd = [MKDOCS, "build", "-f", MKDS, "--strict"]
    raise SystemExit(subprocess.call(cmd))


if __name__ == "__main__":
    main()