#!/usr/bin/env bash
#
# Build the site and rsync it to your own web host.
#
#   tools/deploy.sh              # build + sync + checksum verify
#   tools/deploy.sh --dry-run    # show what would change, transfer nothing
#
# Required (no defaults -- set them for your host):
#   WIKI_SSH_HOST      e.g. your-server.example.com
# Optional:
#   WIKI_SSH_USER      default: $USER
#   WIKI_SSH_PORT      default: 22
#   WIKI_REMOTE_DIR    default: /var/www/wiki
#   WIKI_SITE_URL      printed at the end, e.g. https://wiki.example.com/
#
# Example:
#   WIKI_SSH_HOST=vps.example.com WIKI_SSH_USER=web \
#   WIKI_REMOTE_DIR=/home/web/wiki tools/deploy.sh
set -euo pipefail

SSH_PORT="${WIKI_SSH_PORT:-22}"
SSH_USER="${WIKI_SSH_USER:-$USER}"
SSH_HOST="${WIKI_SSH_HOST:-}"
REMOTE_DIR="${WIKI_REMOTE_DIR:-/var/www/wiki}"
SITE_URL="${WIKI_SITE_URL:-}"

if [[ -z "$SSH_HOST" ]]; then
    echo "!!! WIKI_SSH_HOST is not set (e.g. WIKI_SSH_HOST=vps.example.com)" >&2
    exit 1
fi

cd "$(dirname "$0")/.."

DRY=""
if [[ "${1:-}" == "--dry-run" || "${1:-}" == "-n" ]]; then
    DRY="-n"
    echo ">>> DRY RUN（不会真正传输）"
fi

echo ">>> 构建 site/"
python3 tools/build_site.py

echo ">>> 同步 site/ -> ${SSH_USER}@${SSH_HOST}:${REMOTE_DIR}/"
rsync -avz --delete ${DRY} -e "ssh -p ${SSH_PORT}" site/ \
    "${SSH_USER}@${SSH_HOST}:${REMOTE_DIR}/"

if [[ -z "$DRY" ]]; then
    echo ">>> 复核（无输出 = 远端与本地逐字节一致）"
    rsync -ainc --delete -e "ssh -p ${SSH_PORT}" site/ \
        "${SSH_USER}@${SSH_HOST}:${REMOTE_DIR}/" | grep -v '^\.d' || true
    [[ -n "$SITE_URL" ]] && echo ">>> 完成：${SITE_URL}"
fi