"""
db/models.py — SQLite database schema and helpers
All post queue, logs, and reply tracking stored here.
"""

import sqlite3
import os
from datetime import datetime, timezone

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "db", "autopilot.db")


def get_conn():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH, detect_types=sqlite3.PARSE_DECLTYPES)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Create all tables if they don't exist."""
    conn = get_conn()
    c = conn.cursor()

    # ── Post Queue ────────────────────────────────────────────
    c.execute("""
        CREATE TABLE IF NOT EXISTS posts (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            source_url      TEXT,
            source_title    TEXT,
            source_type     TEXT,               -- reddit | github | rss
            tweet_text      TEXT NOT NULL,
            thread_json     TEXT,               -- JSON array of tweet strings (for threads)
            is_thread       INTEGER DEFAULT 0,
            image_path      TEXT,
            video_path      TEXT,
            image_prompt    TEXT,
            scheduled_at    TEXT,               -- ISO datetime string
            status          TEXT DEFAULT 'queued', -- queued | publishing | published | failed | skipped
            published_at    TEXT,
            error_msg       TEXT,
            created_at      TEXT DEFAULT (datetime('now'))
        )
    """)

    # ── Publish Logs ──────────────────────────────────────────
    c.execute("""
        CREATE TABLE IF NOT EXISTS logs (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            level       TEXT,   -- INFO | WARN | ERROR | SUCCESS
            module      TEXT,   -- scraper | ai_engine | publisher | scheduler | reply_guy
            message     TEXT,
            created_at  TEXT DEFAULT (datetime('now'))
        )
    """)

    # ── Reply Guy Tracking ────────────────────────────────────
    c.execute("""
        CREATE TABLE IF NOT EXISTS replies (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            target_account  TEXT,
            target_tweet_id TEXT,
            target_tweet    TEXT,
            reply_text      TEXT,
            status          TEXT DEFAULT 'queued',  -- queued | sent | failed
            sent_at         TEXT,
            created_at      TEXT DEFAULT (datetime('now'))
        )
    """)

    # ── Scraped Content Cache (avoid re-processing same item) ─
    c.execute("""
        CREATE TABLE IF NOT EXISTS seen_content (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            content_hash TEXT UNIQUE,
            source_url  TEXT,
            seen_at     TEXT DEFAULT (datetime('now'))
        )
    """)

    # ── System Stats ──────────────────────────────────────────
    c.execute("""
        CREATE TABLE IF NOT EXISTS stats (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            date            TEXT UNIQUE,
            posts_published INTEGER DEFAULT 0,
            posts_failed    INTEGER DEFAULT 0,
            replies_sent    INTEGER DEFAULT 0,
            items_scraped   INTEGER DEFAULT 0
        )
    """)

    # ── Auto-prune seen content older than 3 days ─────────────
    c.execute("DELETE FROM seen_content WHERE datetime(seen_at) < datetime('now', '-3 days')")

    conn.commit()
    conn.close()
    print(f"[DB] Database initialized at {DB_PATH}")


# ── Post Queue Helpers ────────────────────────────────────────

def add_post(source_url, source_title, source_type, tweet_text,
             thread_json=None, is_thread=False, image_path=None,
             video_path=None, image_prompt=None, scheduled_at=None):
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        INSERT INTO posts (source_url, source_title, source_type, tweet_text,
                           thread_json, is_thread, image_path, video_path,
                           image_prompt, scheduled_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (source_url, source_title, source_type, tweet_text,
          thread_json, 1 if is_thread else 0, image_path,
          video_path, image_prompt, scheduled_at))
    post_id = c.lastrowid
    conn.commit()
    conn.close()
    return post_id


def get_next_queued_post():
    conn = get_conn()
    c = conn.cursor()
    now = datetime.now(timezone.utc).isoformat()
    row = c.execute("""
        SELECT * FROM posts
        WHERE status = 'queued' AND scheduled_at <= ?
        ORDER BY scheduled_at ASC
        LIMIT 1
    """, (now,)).fetchone()
    conn.close()
    return dict(row) if row else None


def update_post_status(post_id, status, error_msg=None):
    conn = get_conn()
    c = conn.cursor()
    published_at = datetime.now(timezone.utc).isoformat() if status == "published" else None
    c.execute("""
        UPDATE posts SET status = ?, error_msg = ?, published_at = ?
        WHERE id = ?
    """, (status, error_msg, published_at, post_id))
    conn.commit()
    conn.close()


def get_queue(limit=50):
    conn = get_conn()
    rows = conn.execute("""
        SELECT * FROM posts
        WHERE status IN ('queued', 'publishing')
        ORDER BY scheduled_at ASC
        LIMIT ?
    """, (limit,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_history(limit=100):
    conn = get_conn()
    rows = conn.execute("""
        SELECT * FROM posts
        WHERE status IN ('published', 'failed', 'skipped')
        ORDER BY created_at DESC
        LIMIT ?
    """, (limit,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_queue_count():
    conn = get_conn()
    row = conn.execute("SELECT COUNT(*) as c FROM posts WHERE status='queued'").fetchone()
    conn.close()
    return row["c"]


def delete_post(post_id):
    conn = get_conn()
    conn.execute("DELETE FROM posts WHERE id=?", (post_id,))
    conn.commit()
    conn.close()


# ── Log Helpers ───────────────────────────────────────────────

def log(level, module, message):
    conn = get_conn()
    conn.execute("INSERT INTO logs (level, module, message) VALUES (?,?,?)",
                 (level, module, message))
    conn.commit()
    conn.close()
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] [{level}] [{module}] {message}")


def get_logs(limit=200):
    conn = get_conn()
    rows = conn.execute("""
        SELECT * FROM logs ORDER BY created_at DESC LIMIT ?
    """, (limit,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── Seen Content Dedup ────────────────────────────────────────

def is_seen(content_hash):
    conn = get_conn()
    row = conn.execute("SELECT id FROM seen_content WHERE content_hash=?",
                       (content_hash,)).fetchone()
    conn.close()
    return row is not None


def mark_seen(content_hash, source_url):
    conn = get_conn()
    try:
        conn.execute("INSERT INTO seen_content (content_hash, source_url) VALUES (?,?)",
                     (content_hash, source_url))
        conn.commit()
    except sqlite3.IntegrityError:
        pass
    conn.close()


# ── Reply Helpers ─────────────────────────────────────────────

def add_reply(target_account, target_tweet_id, target_tweet, reply_text):
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        INSERT INTO replies (target_account, target_tweet_id, target_tweet, reply_text)
        VALUES (?, ?, ?, ?)
    """, (target_account, target_tweet_id, target_tweet, reply_text))
    reply_id = c.lastrowid
    conn.commit()
    conn.close()
    return reply_id


def get_next_queued_reply():
    conn = get_conn()
    row = conn.execute("""
        SELECT * FROM replies WHERE status='queued' ORDER BY created_at ASC LIMIT 1
    """).fetchone()
    conn.close()
    return dict(row) if row else None


def update_reply_status(reply_id, status):
    conn = get_conn()
    sent_at = datetime.now(timezone.utc).isoformat() if status == "sent" else None
    conn.execute("UPDATE replies SET status=?, sent_at=? WHERE id=?",
                 (status, sent_at, reply_id))
    conn.commit()
    conn.close()


# ── Stats Helpers ─────────────────────────────────────────────

def increment_stat(field):
    today = datetime.now().strftime("%Y-%m-%d")
    conn = get_conn()
    conn.execute("""
        INSERT INTO stats (date, {}) VALUES (?, 1)
        ON CONFLICT(date) DO UPDATE SET {} = {} + 1
    """.format(field, field, field), (today,))
    conn.commit()
    conn.close()


def get_stats_today():
    today = datetime.now().strftime("%Y-%m-%d")
    conn = get_conn()
    row = conn.execute("SELECT * FROM stats WHERE date=?", (today,)).fetchone()
    conn.close()
    return dict(row) if row else {
        "date": today, "posts_published": 0, "posts_failed": 0,
        "replies_sent": 0, "items_scraped": 0
    }


def get_stats_totals():
    conn = get_conn()
    row = conn.execute("""
        SELECT
            SUM(posts_published) as total_published,
            SUM(posts_failed)    as total_failed,
            SUM(replies_sent)    as total_replies,
            SUM(items_scraped)   as total_scraped
        FROM stats
    """).fetchone()
    conn.close()
    return dict(row) if row else {}


if __name__ == "__main__":
    init_db()
