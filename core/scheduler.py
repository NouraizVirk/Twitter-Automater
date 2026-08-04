"""
core/scheduler.py — Post Queue & Timing Engine
Uses APScheduler to manage the daily content pipeline:
  - 6 AM: Scrape + AI process + fill queue
  - Peak hours: Check queue and publish scheduled posts
  - Randomized timing for human-like behavior
"""

import json
import random
import yaml
import os
import sys
from datetime import datetime, timezone, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from db.models import (
    init_db, add_post, get_next_queued_post, update_post_status,
    get_queue_count, log, increment_stat, get_stats_today
)
from core.scraper import run_scrape
from core.ai_engine import process_content_batch
from core.media_factory import create_media_for_post, cleanup_old_media
from core.publisher import publish_post, check_chrome_connection

CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config.yaml")

_scheduler = None
_config = {}


def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


# ── Schedule Time Parser ──────────────────────────────────────

def _parse_peak_times(config: dict) -> list[tuple[int, int]]:
    """Parse HH:MM strings from config into (hour, minute) tuples."""
    times = []
    for t in config.get("schedule", {}).get("peak_times", ["09:00", "13:00", "18:00"]):
        h, m = map(int, t.split(":"))
        times.append((h, m))
    return times


def _randomize_time(hour: int, minute: int, jitter_minutes: int) -> datetime:
    """Add random jitter to a scheduled time for human-like posting."""
    jitter = random.randint(-jitter_minutes, jitter_minutes)
    base = datetime.now(timezone.utc).replace(hour=hour, minute=minute, second=0, microsecond=0)
    # Handle same-timezone offset
    local_offset = config_timezone_offset()
    base = base - timedelta(hours=local_offset)  # convert to UTC
    return base + timedelta(minutes=jitter)


def config_timezone_offset(cfg: dict = None) -> int:
    """Crude timezone offset (hours). Karachi = UTC+5."""
    use_cfg = cfg or _config
    tz = use_cfg.get("schedule", {}).get("timezone", "Asia/Karachi")
    offsets = {
        "Asia/Karachi": 5,
        "America/New_York": -5,
        "America/Los_Angeles": -8,
        "Europe/London": 0,
        "Europe/Paris": 1,
        "Asia/Dubai": 4,
        "Asia/Kolkata": 5,
    }
    return offsets.get(tz, 0)


# ── Daily Content Pipeline ────────────────────────────────────

def run_daily_pipeline(force: bool = False):
    """
    Master pipeline — runs at 9 PM daily or on manual/startup trigger.
    1. Scrape viral content
    2. Process through AI
    3. Generate media
    4. Schedule posts for the day
    """
    global _config
    _config = load_config()
    log("INFO", "scheduler", "═══ Daily content pipeline starting ═══")

    posts_per_day = _config.get("schedule", {}).get("posts_per_day", 8)
    max_cap = _config.get("schedule", {}).get("max_queue_cap", 40)
    queue_count = get_queue_count()

    # Enforce 40 post queue size cap
    if queue_count >= max_cap:
        log("INFO", "scheduler", f"Queue reached max cap of {max_cap} posts ({queue_count} in queue) — skipping scrape")
        return

    needed = posts_per_day if force else min(posts_per_day, max_cap - queue_count)
    if needed <= 0:
        log("INFO", "scheduler", f"Queue has sufficient posts ({queue_count}/{max_cap}) — skipping scrape")
        return

    # Step 1: Scrape
    raw_content = run_scrape(_config)
    if not raw_content:
        log("WARN", "scheduler", "No new content found — will retry next cycle")
        return

    # Step 2: AI process
    processed = process_content_batch(raw_content, _config, needed)
    if not processed:
        log("WARN", "scheduler", "AI processing returned no results — check Groq API key")
        return

    # Step 3: Schedule posts throughout the day
    peak_times = _parse_peak_times(_config)
    jitter = _config.get("schedule", {}).get("randomize_minutes", 18)
    now = datetime.now(timezone.utc)
    offset_h = config_timezone_offset()

    for i, post_data in enumerate(processed):
        # Assign a peak time slot (cycle through them)
        slot_hour, slot_minute = peak_times[i % len(peak_times)]

        # Calculate scheduled UTC time
        scheduled_local = now.replace(
            hour=slot_hour, minute=slot_minute, second=0, microsecond=0
        )
        jitter_offset = random.randint(-jitter, jitter)
        scheduled_local += timedelta(minutes=jitter_offset)

        # If the time has already passed today, push to tomorrow
        if scheduled_local <= now + timedelta(hours=offset_h):
            scheduled_local += timedelta(days=1)

        # Step 4: Generate media
        log("INFO", "scheduler", f"Generating media for post {i+1}/{len(processed)}...")
        media = create_media_for_post(
            post_data,
            _config,
        )

        # Step 5: Add to DB queue
        post_id = add_post(
            source_url=post_data.get("source_url"),
            source_title=post_data.get("source_title"),
            source_type=post_data.get("source_type"),
            tweet_text=post_data.get("tweet_text"),
            thread_json=post_data.get("thread_json"),
            is_thread=post_data.get("is_thread", False),
            image_path=media.get("image_path"),
            video_path=media.get("video_path"),
            image_prompt=post_data.get("image_prompt"),
            scheduled_at=scheduled_local.isoformat(),
        )

        log("SUCCESS", "scheduler",
            f"Queued post #{post_id} for {scheduled_local.strftime('%H:%M')} UTC "
            f"({'thread' if post_data.get('is_thread') else 'single'})")

    # Weekly media cleanup
    if datetime.now().weekday() == 0:  # Monday
        cleanup_old_media(days=7)

    log("SUCCESS", "scheduler", f"═══ Pipeline complete: {len(processed)} posts queued ═══")


# ── Publish Check Job ─────────────────────────────────────────

def check_and_publish():
    """
    Runs every minute. Checks if any post is due and publishes it.
    Respects safety caps to avoid over-posting.
    """
    global _config
    _config = load_config()

    # Safety check
    today_stats = get_stats_today()
    daily_cap = _config.get("stealth", {}).get("daily_post_cap", 10)
    if today_stats.get("posts_published", 0) >= daily_cap:
        return  # Hit daily cap

    post = get_next_queued_post()
    if not post:
        return  # Nothing due

    log("INFO", "scheduler", f"Publishing post #{post['id']}: {post['tweet_text'][:50]}...")
    update_post_status(post["id"], "publishing")

    # Check Chrome is connected
    if not check_chrome_connection(_config):
        log("ERROR", "scheduler",
            "Chrome not connected! Start Chrome with --remote-debugging-port=9222")
        update_post_status(post["id"], "queued")  # put back in queue
        return

    # Publish
    success, message = publish_post(post, _config)

    if success:
        update_post_status(post["id"], "published")
        increment_stat("posts_published")
        log("SUCCESS", "scheduler", f"✅ Post #{post['id']} published: {message}")
    else:
        update_post_status(post["id"], "failed", error_msg=message)
        increment_stat("posts_failed")
        log("ERROR", "scheduler", f"❌ Post #{post['id']} failed: {message}")


# ── Manual Trigger ────────────────────────────────────────────

def trigger_scrape_now():
    """Force a scrape + AI cycle immediately (called from dashboard)."""
    run_daily_pipeline(force=True)


def trigger_publish_now(post_id: int = None):
    """
    Force immediate publish of a specific post or the next queued post.
    Called from dashboard 'Publish Now' button.
    """
    global _config
    _config = load_config()

    if post_id:
        from db.models import get_conn
        conn = get_conn()
        row = conn.execute("SELECT * FROM posts WHERE id=?", (post_id,)).fetchone()
        conn.close()
        post = dict(row) if row else None
    else:
        post = get_next_queued_post()

    if not post:
        log("WARN", "scheduler", "No post available to publish")
        return False, "No post found"

    if not check_chrome_connection(_config):
        return False, "Chrome not connected"

    update_post_status(post["id"], "publishing")
    success, message = publish_post(post, _config)

    if success:
        update_post_status(post["id"], "published")
        increment_stat("posts_published")
    else:
        update_post_status(post["id"], "failed", error_msg=message)
        increment_stat("posts_failed")

    return success, message


# ── Startup Overdue Post Handler ─────────────────────────────

def reschedule_overdue_posts():
    """
    Handles overdue posts when starting after being offline.
    - Leaves the single oldest overdue post at scheduled_at <= now() so check_and_publish() publishes it immediately.
    - Reschedules all remaining overdue posts into future time slots spaced by min_gap.
    """
    from db.models import get_conn
    conn = get_conn()
    now = datetime.now(timezone.utc).isoformat()

    rows = conn.execute("""
        SELECT id, scheduled_at FROM posts
        WHERE status = 'queued' AND scheduled_at <= ?
        ORDER BY scheduled_at ASC
    """, (now,)).fetchall()

    if not rows or len(rows) <= 1:
        conn.close()
        return

    # Keep oldest overdue post as-is (will publish on 1st minute check)
    overdue_to_reschedule = rows[1:]

    min_gap = _config.get("stealth", {}).get("min_gap_between_posts_minutes", 45)
    next_slot = datetime.now(timezone.utc) + timedelta(minutes=min_gap)

    for row in overdue_to_reschedule:
        pid = row["id"]
        conn.execute("UPDATE posts SET scheduled_at = ? WHERE id = ?", (next_slot.isoformat(), pid))
        next_slot += timedelta(minutes=min_gap)

    conn.commit()
    conn.close()
    log("SUCCESS", "scheduler",
        f"Startup Check: Publishing 1 oldest overdue post immediately, rescheduled {len(overdue_to_reschedule)} remaining posts into future slots.")


# ── Scheduler Lifecycle ───────────────────────────────────────

def start_scheduler(config: dict = None) -> BackgroundScheduler:
    """Initialize and start the APScheduler background scheduler."""
    global _scheduler, _config

    if config:
        _config = config
    else:
        _config = load_config()

    init_db()

    # 1. Handle overdue posts on startup (publishes 1st immediately, reschedules the rest)
    reschedule_overdue_posts()

    _scheduler = BackgroundScheduler(
        timezone="UTC",
        job_defaults={"coalesce": True, "max_instances": 1, "misfire_grace_time": 300}
    )

    scrape_hour = _config.get("schedule", {}).get("scrape_hour", 21)

    # Daily content pipeline (default 9 PM local → convert to UTC)
    offset = config_timezone_offset()
    utc_scrape_hour = (scrape_hour - offset) % 24
    _scheduler.add_job(
        run_daily_pipeline,
        trigger=CronTrigger(hour=utc_scrape_hour, minute=0),
        id="daily_pipeline",
        replace_existing=True,
    )

    # Publish check — every minute
    _scheduler.add_job(
        check_and_publish,
        trigger="interval",
        minutes=1,
        id="publish_check",
        replace_existing=True,
    )

    _scheduler.start()
    log("SUCCESS", "scheduler",
        f"Scheduler started. Daily pipeline set for {scrape_hour:02d}:00 local time (9 PM). "
        f"Publish check every 60s.")

    # 2. Always run startup pipeline check in background thread
    log("INFO", "scheduler", "Running initial pipeline check on startup...")
    import threading
    t = threading.Thread(target=run_daily_pipeline, daemon=True)
    t.start()

    return _scheduler


def stop_scheduler():
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        log("INFO", "scheduler", "Scheduler stopped")


def get_scheduler_status() -> dict:
    if _scheduler and _scheduler.running:
        jobs = [
            {"id": j.id, "next_run": str(j.next_run_time)}
            for j in _scheduler.get_jobs()
        ]
        return {"running": True, "jobs": jobs}
    return {"running": False, "jobs": []}
