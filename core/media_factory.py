"""
core/media_factory.py — Visual & Media Engine
Priority Fallback Hierarchy:
1. Priority A: Native OG Visuals (Scrapes og:image or GitHub social card)
2. Priority B: Sleek Dark-Mode Banner Generator (PIL code/product card with clean typography)
3. Priority C: Contextual Tech Meme Engine (Emotion mapping: Panicked, Disappointed, Shocked, Smug)
4. Fallback: Pollinations AI / Video generator
"""

import os
import re
import uuid
import time
import asyncio
import random
import requests
import subprocess
from urllib.parse import quote
from PIL import Image, ImageDraw, ImageFont, ImageFilter

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from db.models import log

MEDIA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "media")
os.makedirs(MEDIA_DIR, exist_ok=True)


# ── Priority A: Download Native OG Image ─────────────────────

def download_native_image(url: str) -> str | None:
    """Download native OG image or GitHub social card directly from source."""
    if not url or not url.startswith("http"):
        return None
    try:
        filename = f"og_{uuid.uuid4().hex[:12]}.jpg"
        filepath = os.path.join(MEDIA_DIR, filename)

        log("INFO", "media_factory", f"Downloading native image: {url[:60]}...")
        resp = requests.get(url, timeout=12, headers={"User-Agent": "Mozilla/5.0"})
        if resp.status_code == 200 and len(resp.content) > 3000:
            with open(filepath, "wb") as f:
                f.write(resp.content)
            log("SUCCESS", "media_factory", f"Native OG image saved: {filename}")
            return filepath
    except Exception as e:
        log("WARN", "media_factory", f"Failed to download native image: {e}")
    return None


# ── Priority B: Dark-Mode Code / Product Banner Generator ───

def generate_dark_banner(title: str, stat: str, badge: str = "DEV TOOL") -> str:
    """
    Generate a sleek 1024x576 dark-mode typography card using PIL.
    No cheesy AI brains — clean, modern, dark UI design with grid accents.
    """
    filename = f"banner_{uuid.uuid4().hex[:12]}.jpg"
    filepath = os.path.join(MEDIA_DIR, filename)

    width, height = 1024, 576
    img = Image.new("RGB", (width, height), color=(11, 15, 25))
    draw = ImageDraw.Draw(img)

    # 1. Subtle Background Grid Accents
    grid_color = (25, 33, 50)
    for x in range(0, width, 40):
        draw.line([(x, 0), (x, height)], fill=grid_color, width=1)
    for y in range(0, height, 40):
        draw.line([(0, y), (width, y)], fill=grid_color, width=1)

    # 2. Gradient Accent Overlay Box
    draw.rectangle([60, 60, width - 60, height - 60], fill=(17, 24, 39), outline=(59, 130, 246), width=2)
    draw.rectangle([65, 65, width - 65, height - 65], outline=(30, 41, 59), width=1)

    # 3. Typography & Badges
    try:
        # Standard PIL fonts
        font_large = ImageFont.truetype("arial.ttf", 38)
        font_stat = ImageFont.truetype("arial.ttf", 30)
        font_badge = ImageFont.truetype("arial.ttf", 18)
    except IOError:
        font_large = font_stat = font_badge = ImageFont.load_default()

    # Draw Badge
    draw.rectangle([90, 95, 260, 130], fill=(29, 78, 216))
    draw.text((105, 102), f"⚡ {badge.upper()}", fill=(255, 255, 255), font=font_badge)

    # Draw Title (Wrapped)
    clean_title = title if len(title) < 55 else title[:52] + "..."
    words = clean_title.split(" ")
    line1, line2 = "", ""
    for w in words:
        if len(line1 + " " + w) < 32:
            line1 += " " + w
        else:
            line2 += " " + w

    draw.text((90, 170), line1.strip(), fill=(248, 250, 252), font=font_large)
    if line2:
        draw.text((90, 225), line2.strip(), fill=(248, 250, 252), font=font_large)

    # Draw Key Stat / Metric
    draw.rectangle([90, height - 160, width - 90, height - 90], fill=(15, 23, 42), outline=(147, 51, 234), width=1)
    draw.text((110, height - 140), f"📊 KEY METRIC: {stat}", fill=(56, 189, 248), font=font_stat)

    # Save
    img.save(filepath, quality=95)
    log("SUCCESS", "media_factory", f"Dark-mode banner generated: {filename}")
    return filepath


# ── Priority C: Contextual Tech Meme Engine ───────────────────

MEME_TEMPLATES = {
    "Panicked": "https://imgflip.com/s/meme/Everywhere-Everything-Is-Fine.jpg",
    "Disappointed": "https://imgflip.com/s/meme/Pablo-Escobar-Waiting.jpg",
    "Shocked": "https://imgflip.com/s/meme/Surprised-Pikachu.jpg",
    "Smug": "https://imgflip.com/s/meme/Drake-Hotline-Bling.jpg",
    "Relieved": "https://imgflip.com/s/meme/Roll-Safe-Think-About-It.jpg"
}

def generate_contextual_meme(emotion: str, caption: str) -> str | None:
    """
    Generate contextual tech meme image with overlay text.
    """
    if not emotion or emotion not in MEME_TEMPLATES or emotion == "None":
        return None

    log("INFO", "media_factory", f"Generating meme for emotion: {emotion}...")
    filename = f"meme_{uuid.uuid4().hex[:12]}.jpg"
    filepath = os.path.join(MEDIA_DIR, filename)

    try:
        url = MEME_TEMPLATES[emotion]
        resp = requests.get(url, timeout=10)
        if resp.status_code != 200:
            return None

        # Open image with PIL
        from io import BytesIO
        img = Image.open(BytesIO(resp.content)).convert("RGB")
        
        # Add Top Banner with Caption
        banner_height = 80
        new_img = Image.new("RGB", (img.width, img.height + banner_height), color=(255, 255, 255))
        new_img.paste(img, (0, banner_height))

        draw = ImageDraw.Draw(new_img)
        try:
            font = ImageFont.truetype("arial.ttf", 22)
        except IOError:
            font = ImageFont.load_default()

        # Wrap caption
        text = caption if caption else f"Tech community reacting to {emotion} news:"
        draw.text((20, 25), text[:65], fill=(0, 0, 0), font=font)

        new_img.save(filepath, quality=90)
        log("SUCCESS", "media_factory", f"Meme generated: {filename}")
        return filepath

    except Exception as e:
        log("WARN", "media_factory", f"Failed to generate meme: {e}")
        return None


# ── Pollinations AI Fallback Generator ───────────────────────

def generate_image(prompt: str, config: dict) -> str | None:
    """Generate image via Pollinations.ai as secondary option."""
    if not config.get("media", {}).get("images", {}).get("enabled", True):
        return None

    img_cfg = config["media"]["images"]
    width = img_cfg.get("width", 1024)
    height = img_cfg.get("height", 576)

    encoded = quote(f"{prompt}, dark technical banner, clean aesthetics, 8k resolution")
    seed = str(uuid.uuid4().int)[:8]
    url = f"https://image.pollinations.ai/prompt/{encoded}?width={width}&height={height}&seed={seed}&nologo=true"

    filename = f"img_{uuid.uuid4().hex[:12]}.jpg"
    filepath = os.path.join(MEDIA_DIR, filename)

    try:
        resp = requests.get(url, timeout=40)
        if resp.status_code == 200 and len(resp.content) > 5000:
            with open(filepath, "wb") as f:
                f.write(resp.content)
            return filepath
    except Exception:
        pass
    return None


# ── Master Media Pipeline (Hierarchy Dispatcher) ────────────

def create_media_for_post(post_data: dict, config: dict) -> dict:
    """
    Executes Media Hierarchy:
    1. Check for Contextual Meme (~30% chance or if emotion set)
    2. Priority A: Native OG Image from source URL
    3. Priority B: Dark-Mode Typography Banner (PIL)
    4. Fallback: Pollinations AI Image
    """
    result = {"image_path": None, "video_path": None}
    
    emotion = post_data.get("emotion", "None")
    caption = post_data.get("meme_caption", "")
    source_media_url = post_data.get("source_media_url")
    title = post_data.get("banner_title") or post_data.get("source_title", "Tech Announcement")
    stat = post_data.get("banner_stat", "100% Free / Open Source")
    prompt = post_data.get("image_prompt", "dark-mode developer tool")

    memes_enabled = config.get("media", {}).get("memes", {}).get("enabled", True)
    meme_freq = config.get("media", {}).get("memes", {}).get("frequency", 0.3)

    # 1. Option: Meme Generator (if emotion set or ~30% random trigger)
    if memes_enabled and (emotion != "None" or random.random() < meme_freq):
        chosen_emotion = emotion if emotion != "None" else random.choice(["Panicked", "Shocked", "Disappointed", "Smug"])
        meme_path = generate_contextual_meme(chosen_emotion, caption if caption else f"Developers reacting to {title[:40]}:")
        if meme_path:
            result["image_path"] = meme_path
            return result

    # 2. Priority A: Native OG Image
    if source_media_url:
        native_path = download_native_image(source_media_url)
        if native_path:
            result["image_path"] = native_path
            return result

    # 3. Priority B: Dark Banner Typography Card
    try:
        banner_path = generate_dark_banner(title, stat, post_data.get("source_type", "DEV TOOL"))
        if banner_path:
            result["image_path"] = banner_path
            return result
    except Exception as e:
        log("WARN", "media_factory", f"Dark banner generation failed: {e}")

    # 4. Fallback: Pollinations AI
    result["image_path"] = generate_image(prompt, config)
    return result


def cleanup_old_media(days: int = 7):
    """Delete media files older than N days."""
    import glob
    cutoff = time.time() - (days * 86400)
    for f in glob.glob(os.path.join(MEDIA_DIR, "*")):
        if os.path.getmtime(f) < cutoff:
            try:
                os.remove(f)
            except Exception:
                pass


if __name__ == "__main__":
    import yaml
    with open(os.path.join(os.path.dirname(os.path.dirname(__file__)), "config.yaml")) as f:
        cfg = yaml.safe_load(f)

    test_post = {
        "emotion": "Panicked",
        "meme_caption": "OpenAI engineers when Claude drops a 90-day monetization plan:",
        "banner_title": "vLLM 0.6.0 Released",
        "banner_stat": "3x Faster Inference / 50k Stars",
        "source_type": "GITHUB",
        "source_media_url": "https://github.githubassets.com/images/modules/open_graph/github-logo.png"
    }

    print("Testing Media Pipeline...")
    res = create_media_for_post(test_post, cfg)
    print("Resulting Media Path:", res["image_path"])
