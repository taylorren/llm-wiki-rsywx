# Copy this file to config.py and edit it. config.py is gitignored, so your
# blog URL, book catalog and SMTP credentials never land in the repository.
#
# Everything below can also come from environment variables
# (LLMWIKI_BLOG_URL, LLMWIKI_BOOKS_BASE, LLMWIKI_MAIL_HOST, ...), which is
# handy in cron jobs and CI.

# --- source blog (WordPress with the REST API enabled) ---
BLOG_URL = "https://blog.example.com"
# Shown in the sync cron mail and used as the sync User-Agent.
USER_AGENT = "llm-wiki-sync/0.1 (+https://wiki.example.com)"

# --- book catalog (optional) ---
# If your posts link books to a catalog page such as
# https://example.com/books/02072.html, set the prefix here;
# tools/extract_books.py then builds wiki/books.md from those links.
# Leave empty to skip the book index entirely.
BOOKS_BASE = "https://example.com/books"

# --- cron notifications for tools/sync_posts.py --notify (optional) ---
# Keep MAIL_HOST empty to disable notifications. The password is best kept out
# of this file entirely: put it in a 0600 file (default
# ~/.config/mail/relay.pass, override with LLMWIKI_MAIL_PASS_FILE) and leave
# MAIL_PASS unset -- cron then needs no environment at all.
MAIL_HOST = ""
MAIL_PORT = 587
MAIL_USER = ""
MAIL_PASS = ""
MAIL_FROM = ""