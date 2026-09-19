#!/usr/bin/env python3
"""Site-specific settings, kept out of the code.

Lookup order for every setting:

  1. `config.py` in the repo root (copy `config.example.py`; gitignored)
  2. the matching `LLMWIKI_*` environment variable
  3. the built-in default

That keeps the tracked scripts generic: nothing here names a specific blog,
book catalog or mail relay.

Settings
    BLOG_URL     base URL of the source blog (WordPress, needs the REST API),
                 e.g. "https://blog.example.com"
    BOOKS_BASE   link prefix of the book catalog, e.g.
                 "https://example.com/books" -> .../books/02072.html
                 (used by tools/extract_books.py; set to "" to disable)
    USER_AGENT   User-Agent sent when fetching posts
    MAIL_HOST / MAIL_PORT / MAIL_USER / MAIL_PASS / MAIL_FROM
                 SMTP relay for `sync_posts.py --notify`; leave MAIL_HOST
                 empty to disable notifications
"""
import importlib.util
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(ROOT, "config.py")

_cfg = None
_loaded = False

DEFAULTS = {
    "BLOG_URL": "https://example.com",
    "BOOKS_BASE": "https://example.com/books",
    "USER_AGENT": "llm-wiki-sync/0.1",
    "MAIL_HOST": "",
    "MAIL_PORT": "587",
    "MAIL_USER": "",
    "MAIL_PASS": "",
    "MAIL_FROM": "",
}


def _config():
    global _cfg, _loaded
    if not _loaded:
        if os.path.exists(CONFIG_PATH):
            spec = importlib.util.spec_from_file_location("llmwiki_config",
                                                          CONFIG_PATH)
            _cfg = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(_cfg)
        _loaded = True
    return _cfg


def get(name, default=None):
    """config.py value, else $LLMWIKI_<name>, else the default."""
    cfg = _config()
    if cfg is not None and getattr(cfg, name, None) not in (None, ""):
        return getattr(cfg, name)
    env = os.environ.get(f"LLMWIKI_{name}")
    if env not in (None, ""):
        return env
    if default is not None:
        return default
    return DEFAULTS.get(name, "")


def is_configured(name):
    """True when config.py or the environment supplies a non-default value."""
    cfg = _config()
    if cfg is not None and getattr(cfg, name, None) not in (None, ""):
        return True
    return os.environ.get(f"LLMWIKI_{name}") not in (None, "")