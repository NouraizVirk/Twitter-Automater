"""
core/publisher.py — Stealth Twitter Publisher
Connects to your existing logged-in Chrome session via CDP (Chrome DevTools Protocol).
Uses Playwright to publish tweets/threads without triggering bot detection.

SETUP REQUIRED:
  Chrome must be started with: --remote-debugging-port=9222
  (The start.bat launcher does this automatically)
"""

import asyncio
import json
import random
import time
import os
import pyperclip

from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from db.models import log, update_post_status, increment_stat


# ── Twitter Selectors (data-testid based — stable across redesigns) ───

SEL = {
    "compose_btn":   '[data-testid="SideNav_NewTweet_Button"]',
    "tweet_box":     '[data-testid="tweetTextarea_0"]',
    "tweet_box_alt": 'div[role="textbox"][data-testid*="tweetTextarea"]',
    "post_btn":      '[data-testid="tweetButtonInline"]',
    "post_btn_alt":  '[data-testid="tweetButton"]',
    "add_tweet_btn": '[data-testid="addButton"]',
    "file_input":    'input[data-testid="fileInput"]',
    "card_wrapper":  '[data-testid="card.wrapper"]',
    "tweet_confirm": '[data-testid="toast"]',
}

TWITTER_COMPOSE_URL = "https://x.com/compose/post"
TWITTER_HOME_URL    = "https://x.com/home"


# ── Stealth Helpers ───────────────────────────────────────────

async def _human_delay(min_ms: int = 800, max_ms: int = 2500):
    """Random delay to mimic human reaction time."""
    delay = random.randint(min_ms, max_ms) / 1000
    await asyncio.sleep(delay)


async def _paste_text(page, selector: str, text: str):
    """
    Use Playwright's native text insertion. 
    It dispatches the exact same events as pasting, without relying on the OS clipboard.
    """
    await page.click(selector)
    await _human_delay(400, 900)
    await page.keyboard.insert_text(text)
    await _human_delay(300, 700)


async def _human_scroll(page, scrolls: int = 2):
    """Simulate a human scrolling before performing an action."""
    for _ in range(scrolls):
        scroll_amount = random.randint(100, 400)
        await page.mouse.wheel(0, scroll_amount)
        await _human_delay(300, 800)
    await _human_delay(500, 1200)


# ── Core Publisher ────────────────────────────────────────────

async def _publish_post(post: dict, browser_cfg: dict) -> tuple[bool, str]:
    """
    Attach to Chrome via CDP and publish one post (single tweet or thread).
    Returns (success: bool, message: str).
    """
    cdp_url = browser_cfg.get("chrome_debug_url", "http://localhost:9222")
    min_delay = browser_cfg.get("min_action_delay_ms", 800)
    max_delay = browser_cfg.get("max_action_delay_ms", 2500)
    timeout = browser_cfg.get("post_timeout_seconds", 30) * 1000  # ms

    async with async_playwright() as pw:
        try:
            # ── Connect to YOUR existing Chrome session ──────────
            browser = await pw.chromium.connect_over_cdp(cdp_url)
            log("INFO", "publisher", "Connected to Chrome via CDP")
        except Exception as e:
            return False, f"Cannot connect to Chrome. Is it running with --remote-debugging-port=9222? Error: {e}"

        try:
            # Get or create a context/page
            contexts = browser.contexts
            if not contexts:
                return False, "No browser context found. Open Twitter in Chrome first."

            ctx = contexts[0]

            # Find existing Twitter tab or open a new one
            twitter_page = None
            for p in ctx.pages:
                if "x.com" in p.url or "twitter.com" in p.url:
                    twitter_page = p
                    break

            if twitter_page is None:
                twitter_page = await ctx.new_page()

            # Navigate to compose URL
            await twitter_page.bring_to_front()
            await _human_scroll(twitter_page, random.randint(1, 3))

            log("INFO", "publisher", "Navigating to compose...")
            await twitter_page.goto(TWITTER_COMPOSE_URL, wait_until="domcontentloaded", timeout=timeout)
            await _human_delay(min_delay, max_delay)

            # ── Determine if thread or single tweet ──────────────
            is_thread = post.get("is_thread", False)
            thread_data = json.loads(post["thread_json"]) if is_thread and post.get("thread_json") else None

            tweets_to_post = thread_data if is_thread and thread_data else [post["tweet_text"]]

            # ── Type first tweet ──────────────────────────────────
            active_selector = SEL["tweet_box"]
            try:
                await twitter_page.wait_for_selector(SEL["tweet_box"], timeout=timeout)
            except PlaywrightTimeout:
                # Try alternative selector
                await twitter_page.wait_for_selector(SEL["tweet_box_alt"], timeout=timeout)
                active_selector = SEL["tweet_box_alt"]

            first_tweet = tweets_to_post[0]
            await _paste_text(twitter_page, active_selector, first_tweet)
            await _human_delay(min_delay, max_delay)
            log("INFO", "publisher", f"First tweet entered ({len(first_tweet)} chars)")

            # ── Attach media (image or video) to FIRST tweet ──────
            media_path = post.get("video_path") or post.get("image_path")
            if media_path and os.path.exists(media_path):
                try:
                    file_input = await twitter_page.query_selector(SEL["file_input"])
                    if file_input:
                        await file_input.set_input_files(media_path)
                        await _human_delay(2000, 4000)  # wait for upload
                        log("INFO", "publisher", f"Media attached: {os.path.basename(media_path)}")
                    else:
                        log("WARN", "publisher", "File input not found, posting without media")
                except Exception as e:
                    log("WARN", "publisher", f"Media attach failed: {e} — posting text only")

            # ── Add subsequent tweets if thread ───────────────────
            if is_thread and len(tweets_to_post) > 1:
                for i, tweet_text in enumerate(tweets_to_post[1:], 1):
                    # i=1 is the second tweet, i=2 is the third
                    try:
                        add_btn = await twitter_page.wait_for_selector(
                            SEL["add_tweet_btn"], timeout=10000
                        )
                        await add_btn.click(force=True)
                        await _human_delay(min_delay, max_delay)
                    except Exception:
                        log("WARN", "publisher", f"Could not find Add Tweet button for tweet {i+1}")
                        break

                    # Target the exact new text area (tweetTextarea_1, tweetTextarea_2, etc)
                    box_sel = f'[data-testid="tweetTextarea_{i}"]'
                    try:
                        box = await twitter_page.wait_for_selector(box_sel, timeout=10000)
                        await box.focus()
                        await _human_delay(300, 700)
                        await twitter_page.keyboard.insert_text(tweet_text)
                        await _human_delay(min_delay, max_delay)
                        log("INFO", "publisher", f"Thread tweet {i+1} entered")
                    except Exception as e:
                        log("WARN", "publisher", f"Failed to type thread tweet {i+1}: {e}")
                        break

            # (Media attach was moved above the thread loop)

            # ── Click Post button (via Keyboard Shortcut) ─────────
            # Twitter allows Control+Enter to post/post-all from anywhere in the compose box
            await _human_delay(min_delay + 500, max_delay + 1000)
            
            log("INFO", "publisher", "Pressing Control+Enter to publish...")
            await twitter_page.keyboard.press("Control+Enter")
            
            # Wait to see if it worked, if network is slow media might still be uploading
            await _human_delay(2000, 3000)
            if "compose" in twitter_page.url:
                # Try one more time in case the first one was ignored due to upload state
                await twitter_page.keyboard.press("Control+Enter")
                await _human_delay(2000, 3000)

            # ── Verify success (look for toast notification) ──────
            try:
                await twitter_page.wait_for_selector(SEL["tweet_confirm"], timeout=10000)
                log("SUCCESS", "publisher", "✅ Post published successfully!")
                return True, "Published"
            except PlaywrightTimeout:
                # Even without toast, if page navigated away from compose, it likely succeeded
                current_url = twitter_page.url
                if "compose" not in current_url:
                    return True, "Published (no toast confirmation, but compose closed)"
                return False, "Post may not have been published — no confirmation detected"

        except Exception as e:
            return False, f"Publisher error: {e}"

        finally:
            # Don't close the browser — we're attached to the user's Chrome
            pass


# ── Sync Wrapper ──────────────────────────────────────────────

def publish_post(post: dict, config: dict) -> tuple[bool, str]:
    """Synchronous entry point for the scheduler to call."""
    browser_cfg = config.get("browser", {})
    return asyncio.run(_publish_post(post, browser_cfg))


# ── Reply Publisher ───────────────────────────────────────────

async def _publish_reply(tweet_url: str, reply_text: str, browser_cfg: dict) -> tuple[bool, str]:
    """Navigate to a specific tweet and post a reply."""
    cdp_url = browser_cfg.get("chrome_debug_url", "http://localhost:9222")
    min_d = browser_cfg.get("min_action_delay_ms", 800)
    max_d = browser_cfg.get("max_action_delay_ms", 2500)

    async with async_playwright() as pw:
        try:
            browser = await pw.chromium.connect_over_cdp(cdp_url)
        except Exception as e:
            return False, f"Cannot connect to Chrome: {e}"

        try:
            ctx = browser.contexts[0]
            page = await ctx.new_page()

            # Navigate to the tweet
            await page.goto(tweet_url, wait_until="domcontentloaded", timeout=30000)
            await _human_delay(min_d * 2, max_d)
            await _human_scroll(page, random.randint(1, 2))

            # Click the reply input area
            reply_box_sel = '[data-testid="tweetTextarea_0"]'
            try:
                await page.click('[data-testid="reply"]', timeout=8000)
                await _human_delay(min_d, max_d)
            except Exception:
                pass  # Sometimes the reply box is already visible

            await page.wait_for_selector(reply_box_sel, timeout=15000)
            await _paste_text(page, reply_box_sel, reply_text)
            await _human_delay(min_d, max_d)

            # Post the reply
            await _human_delay(min_d + 500, max_d + 1000)
            await page.keyboard.press("Control+Enter")
            await _human_delay(2000, 4000)

            await page.close()
            return True, "Reply sent"

        except Exception as e:
            return False, f"Reply error: {e}"


def publish_reply(tweet_url: str, reply_text: str, config: dict) -> tuple[bool, str]:
    """Synchronous wrapper for publishing a reply."""
    return asyncio.run(_publish_reply(tweet_url, reply_text, config.get("browser", {})))


# ── Chrome Connection Check ───────────────────────────────────

def check_chrome_connection(config: dict) -> bool:
    """Check if Chrome is running with remote debugging enabled."""
    import requests as req
    cdp_url = config.get("browser", {}).get("chrome_debug_url", "http://localhost:9222")
    try:
        resp = req.get(f"{cdp_url}/json/version", timeout=3)
        return resp.status_code == 200
    except Exception:
        return False
