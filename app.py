"""
app.py — Twitter Autopilot Web Dashboard
Flask server providing REST API and serving the dashboard UI.
Access at: http://localhost:5000
"""

import os
import sys

# Fix Windows console encoding for emoji in logs
if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import yaml
import json
import threading
from datetime import datetime
from flask import Flask, render_template, jsonify, request, send_from_directory
from flask_cors import CORS

# Bootstrap DB and scheduler
import sys
sys.path.insert(0, os.path.dirname(__file__))
from db.models import (
    init_db, get_queue, get_history, get_logs, get_queue_count,
    delete_post, get_stats_today, get_stats_totals, update_post_status, log
)
from core.publisher import check_chrome_connection
from core.scheduler import (
    start_scheduler, stop_scheduler, get_scheduler_status,
    trigger_scrape_now, trigger_publish_now
)

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.yaml")

app = Flask(__name__)
CORS(app)

_scheduler = None


def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


def save_config(data: dict):
    with open(CONFIG_PATH, "w") as f:
        yaml.dump(data, f, default_flow_style=False, allow_unicode=True)


# ── Page Routes ───────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


# ── API: Status ───────────────────────────────────────────────

@app.route("/api/status")
def api_status():
    config = load_config()
    chrome_ok = check_chrome_connection(config)
    sched_status = get_scheduler_status()
    today = get_stats_today()
    totals = get_stats_totals()
    api_key_set = bool(config.get("ai", {}).get("groq_api_key", ""))

    return jsonify({
        "chrome_connected": chrome_ok,
        "scheduler_running": sched_status["running"],
        "scheduler_jobs": sched_status.get("jobs", []),
        "queue_count": get_queue_count(),
        "api_key_configured": api_key_set,
        "today": today,
        "totals": totals,
        "timestamp": datetime.now().isoformat(),
    })


# ── API: Queue ────────────────────────────────────────────────

@app.route("/api/queue")
def api_queue():
    posts = get_queue(limit=100)
    # Convert media paths to relative for frontend
    for p in posts:
        if p.get("image_path"):
            p["image_url"] = "/media/" + os.path.basename(p["image_path"])
        if p.get("video_path"):
            p["video_url"] = "/media/" + os.path.basename(p["video_path"])
    return jsonify(posts)


@app.route("/api/queue/<int:post_id>", methods=["DELETE"])
def api_delete_post(post_id):
    delete_post(post_id)
    log("INFO", "dashboard", f"Post #{post_id} deleted via dashboard")
    return jsonify({"ok": True})


@app.route("/api/history/<int:post_id>/retry", methods=["POST"])
def api_retry_post(post_id):
    update_post_status(post_id, "queued", error_msg=None)
    log("INFO", "dashboard", f"Post #{post_id} re-queued for retry")
    return jsonify({"ok": True, "message": "Post re-queued successfully!"})


@app.route("/api/queue/<int:post_id>/publish", methods=["POST"])
def api_publish_now(post_id):
    """Immediately publish a specific queued post."""
    def _run():
        success, msg = trigger_publish_now(post_id)
        log("INFO", "dashboard", f"Manual publish #{post_id}: {msg}")
    threading.Thread(target=_run, daemon=True).start()
    return jsonify({"ok": True, "message": "Publishing started..."})


# ── API: History ──────────────────────────────────────────────

@app.route("/api/history")
def api_history():
    posts = get_history(limit=100)
    for p in posts:
        if p.get("image_path"):
            p["image_url"] = "/media/" + os.path.basename(p["image_path"])
    return jsonify(posts)


# ── API: Logs ─────────────────────────────────────────────────

@app.route("/api/logs")
def api_logs():
    limit = int(request.args.get("limit", 200))
    return jsonify(get_logs(limit=limit))


# ── API: Actions ──────────────────────────────────────────────

@app.route("/api/scrape-now", methods=["POST"])
def api_scrape_now():
    """Trigger an immediate scrape + AI cycle."""
    def _run():
        log("INFO", "dashboard", "Manual scrape triggered via dashboard")
        trigger_scrape_now()
    threading.Thread(target=_run, daemon=True).start()
    return jsonify({"ok": True, "message": "Scrape started in background..."})


@app.route("/api/scheduler/start", methods=["POST"])
def api_start_scheduler():
    global _scheduler
    if _scheduler and _scheduler.running:
        return jsonify({"ok": False, "message": "Scheduler already running"})
    config = load_config()
    _scheduler = start_scheduler(config)
    return jsonify({"ok": True, "message": "Scheduler started"})


@app.route("/api/scheduler/stop", methods=["POST"])
def api_stop_scheduler():
    stop_scheduler()
    return jsonify({"ok": True, "message": "Scheduler stopped"})


# ── API: Settings ─────────────────────────────────────────────

@app.route("/api/settings", methods=["GET"])
def api_get_settings():
    config = load_config()
    # Mask API key for security (show last 4 chars only)
    key = config.get("ai", {}).get("groq_api_key", "")
    config["ai"]["groq_api_key"] = ("*" * (len(key) - 4) + key[-4:]) if len(key) > 4 else key
    return jsonify(config)


@app.route("/api/settings", methods=["POST"])
def api_save_settings():
    config = load_config()
    data = request.json

    # Update only allowed top-level keys
    allowed_keys = ["ai", "schedule", "posting", "media", "reply_guy", "stealth", "monetization"]
    for key in allowed_keys:
        if key in data:
            # Don't overwrite API key if it looks masked
            if key == "ai" and data["ai"].get("groq_api_key", "").startswith("*"):
                data["ai"]["groq_api_key"] = config["ai"].get("groq_api_key", "")
            config[key] = data[key]

    save_config(config)
    log("INFO", "dashboard", "Settings saved via dashboard")
    return jsonify({"ok": True, "message": "Settings saved"})


@app.route("/api/settings/api-key", methods=["POST"])
def api_save_key():
    """Save the Groq API key specifically."""
    key = request.json.get("key", "").strip()
    if not key:
        return jsonify({"ok": False, "message": "Empty key"})
    config = load_config()
    config["ai"]["groq_api_key"] = key
    save_config(config)
    log("SUCCESS", "dashboard", "Groq API key saved")
    return jsonify({"ok": True, "message": "API key saved!"})


# ── Media Files ───────────────────────────────────────────────

@app.route("/media/<path:filename>")
def serve_media(filename):
    media_dir = os.path.join(os.path.dirname(__file__), "media")
    return send_from_directory(media_dir, filename)


# ── Startup ───────────────────────────────────────────────────

def startup():
    """Initialize DB and start scheduler on app launch."""
    global _scheduler
    init_db()
    log("INFO", "dashboard", "Twitter Autopilot starting up...")
    config = load_config()
    _scheduler = start_scheduler(config)
    log("SUCCESS", "dashboard", "🚀 Autopilot is live at http://localhost:5000")


if __name__ == "__main__":
    startup()
    app.run(host="0.0.0.0", port=5000, debug=False, use_reloader=False)
