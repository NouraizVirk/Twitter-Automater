"""
core/reply_guy.py — Automated Reply Engine
Monitors target AI/SaaS accounts on Twitter, generates thoughtful
AI-powered replies, and posts them via the CDP publisher.
Critical for reaching 500 verified followers quickly.
"""

import asyncio
import random
import time
import os
import re
import sys
from datetime import datetime, timezone, timedelta

import requests
from playwright.async_api import async_playwright

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from db.models import (
    add_reply, get_next_queued_reply, update_reply_status,
    log, increment_stat, get_stats_today
)
from core.ai_engine import generate_reply
from core.publisher import _human_delay, _paste_text, _human_scroll, SEL

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/124.0.0.0 Safari/537.36",
}


# ── Tweet Discovery (Twitter Public API) ──────────────────────

def _fetch_recent_tweets_playwright_free(account: str) -> list[dict]:
    """
    Scrape recent tweets from a target account profile page
    using requests (lightweight, no headless browser for scraping).
    Falls back gracefully if blocked.
    """
    # Use nitter.net as a lightweight scraping endpoint (public mirror)
    nitter_instances = [
        "https://nitter.poast.org",
        "https://nitter.privacydev.net",
        "https://nitter.catsarch.com",
    ]

    for base in nitter_instances:
        try:
            url = f"{base}/{account}"
            resp = requests.get(url, headers=HEADERS, timeout=10)
            if resp.status_code != 200:
                continue

            from bs4 import BeautifulSoup
            soup = BeautifulSoup(resp.text, "lxml")

            tweets = []
            for item in soup.select(".timeline-item")[:10]:
                content_div = item.select_one(".tweet-content")
                link_tag = item.select_one("a.tweet-link")

                if not content_div or not link_tag:
                    continue

                tweet_text = content_div.get_text(strip=True)
                tweet_href = link_tag.get("href", "")

                # Convert nitter link to actual Twitter link
                tweet_url = f"https://x.com{tweet_href}" if tweet_href.startswith("/") else tweet_href

                # Skip if too short or a retweet
                if len(tweet_text) < 20 or tweet_text.startswith("RT "):
                    continue

                # Extract tweet ID from URL
                tweet_id = tweet_href.split("/")[-1] if "/" in tweet_href else ""

                tweets.append({
                    "id": tweet_id,
                    "text": tweet_text[:280],
                    "url": tweet_url,
                    "account": account,
                })

            if tweets:
                log("INFO", "reply_guy", f"Found {len(tweets)} recent tweets from @{account}")
                return tweets

        except Exception as e:
            log("WARN", "reply_guy", f"Nitter instance {base} failed: {e}")
            continue

    log("WARN", "reply_guy", f"Could not fetch tweets for @{account} — all instances failed")
    return []


def _is_reply_worthy(tweet_text: str, keywords: list) -> bool:
    """Check if a tweet is worth replying to (AI/SaaS relevant)."""
    text_lower = tweet_text.lower()
    return any(kw.lower() in text_lower for kw in keywords)


# ── Reply Queue Builder ───────────────────────────────────────

def build_reply_queue(config: dict) -> int:
    """
    Scan target accounts for recent tweets and queue AI-generated replies.
    Returns number of replies queued.
    """
    reply_cfg = config.get("reply_guy", {})
    if not reply_cfg.get("enabled", False):
        return 0

    target_accounts = reply_cfg.get("target_accounts", [])
    replies_per_day = reply_cfg.get("replies_per_day", 25)
    niche_keywords = config.get("niche", {}).get("keywords", ["AI", "LLM", "automation"])

    log("INFO", "reply_guy", f"Scanning {len(target_accounts)} target accounts...")

    today_stats = get_stats_today()
    already_replied = today_stats.get("replies_sent", 0)
    budget = max(0, replies_per_day - already_replied)

    if budget <= 0:
        log("INFO", "reply_guy", "Daily reply budget exhausted")
        return 0

    queued = 0
    random.shuffle(target_accounts)  # randomize which accounts we check

    for account in target_accounts:
        if queued >= budget:
            break

        tweets = _fetch_recent_tweets_playwright_free(account)

        for tweet in tweets:
            if queued >= budget:
                break

            # Only reply to relevant content
            if not _is_reply_worthy(tweet["text"], niche_keywords):
                continue

            # Generate AI reply
            reply_text = generate_reply(tweet["text"], config)
            if not reply_text:
                continue

            # Truncate to 240 chars
            reply_text = reply_text[:240]

            # Add to queue
            reply_id = add_reply(
                target_account=account,
                target_tweet_id=tweet["id"],
                target_tweet=tweet["text"],
                reply_text=reply_text,
            )
            queued += 1
            log("INFO", "reply_guy", f"Queued reply #{reply_id} to @{account}: {reply_text[:50]}...")

            time.sleep(random.uniform(2.0, 5.0))  # rate limit

        time.sleep(random.uniform(3.0, 8.0))

    log("SUCCESS", "reply_guy", f"Reply queue built: {queued} replies ready")
    return queued


# ── Reply Publisher ───────────────────────────────────────────

async def _send_reply_via_cdp(reply: dict, browser_cfg: dict) -> tuple[bool, str]:
    """Send a queued reply via Playwright CDP connection."""
    cdp_url = browser_cfg.get("chrome_debug_url", "http://localhost:9222")
    min_d = browser_cfg.get("min_action_delay_ms", 800)
    max_d = browser_cfg.get("max_action_delay_ms", 2500)

    tweet_url = reply.get("target_tweet_id", "")
    account = reply.get("target_account", "")

    # Reconstruct Twitter URL if we only have the tweet ID
    if not tweet_url.startswith("http"):
        tweet_url = f"https://x.com/{account}/status/{tweet_url}"

    async with async_playwright() as pw:
        try:
            browser = await pw.chromium.connect_over_cdp(cdp_url)
        except Exception as e:
            return False, f"Cannot connect to Chrome: {e}"

        try:
            ctx = browser.contexts[0]
            page = await ctx.new_page()

            # Navigate to the tweet
            await page.goto(tweet_url, wait_until="networkidle", timeout=30000)
            await _human_delay(min_d * 2, max_d * 2)
            await _human_scroll(page, random.randint(1, 2))

            # Find and click the reply button on the tweet
            reply_btn_sel = '[data-testid="reply"]'
            try:
                await page.click(reply_btn_sel, timeout=8000)
                await _human_delay(min_d, max_d)
            except Exception:
                pass  # reply input might already be focused

            # Find the reply textarea
            reply_box_sel = '[data-testid="tweetTextarea_0"]'
            await page.wait_for_selector(reply_box_sel, timeout=15000)
            await _paste_text(page, reply_box_sel, reply["reply_text"])
            await _human_delay(min_d, max_d)

            # Click post
            post_btn = await page.wait_for_selector(SEL["post_btn"], timeout=8000)
            await post_btn.click()
            await _human_delay(2000, 4000)

            await page.close()
            return True, f"Reply sent to @{account}"

        except Exception as e:
            return False, f"Reply error: {e}"


def send_queued_reply(config: dict) -> bool:
    """Send the next queued reply. Called by scheduler."""
    reply_cfg = config.get("reply_guy", {})
    if not reply_cfg.get("enabled", False):
        return False

    today_stats = get_stats_today()
    daily_limit = reply_cfg.get("replies_per_day", 25)
    if today_stats.get("replies_sent", 0) >= daily_limit:
        return False

    reply = get_next_queued_reply()
    if not reply:
        return False

    log("INFO", "reply_guy", f"Sending reply to @{reply['target_account']}...")
    success, msg = asyncio.run(
        _send_reply_via_cdp(reply, config.get("browser", {}))
    )

    if success:
        update_reply_status(reply["id"], "sent")
        increment_stat("replies_sent")
        log("SUCCESS", "reply_guy", f"✅ {msg}")
    else:
        update_reply_status(reply["id"], "failed")
        log("ERROR", "reply_guy", f"❌ Reply failed: {msg}")

    return success


if __name__ == "__main__":
    import yaml
    with open(os.path.join(os.path.dirname(os.path.dirname(__file__)), "config.yaml")) as f:
        cfg = yaml.safe_load(f)
    from db.models import init_db
    init_db()
    n = build_reply_queue(cfg)
    print(f"Queued {n} replies")
