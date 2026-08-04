"""
core/scraper.py — High-Value Content Discovery Engine
Scrapes:
1. GitHub Trending & Releases (stars/day filter, version tags)
2. Reddit rising.json (r/LocalLLaMA, r/MachineLearning, r/OpenAI, r/singularity)
3. Hacker News Firebase API (Top & Show HN with >100 score)
4. Hugging Face Daily Papers API & ArXiv RSS (cs.AI, cs.CL, cs.CV)
5. Native OG Image / Social Card Extractor
"""

import hashlib
import time
import random
import re
from datetime import datetime, timezone
import requests
import feedparser
from bs4 import BeautifulSoup

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from db.models import is_seen, mark_seen, log, increment_stat


HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}

SESSION = requests.Session()
SESSION.headers.update(HEADERS)


def _hash(text: str) -> str:
    return hashlib.md5(text.encode()).hexdigest()


def _clean_text(text: str) -> str:
    """Remove markdown formatting, HTML tags, extra whitespace."""
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", "", text)                    # strip HTML tags
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)  # strip markdown links
    text = re.sub(r"[*_#`>]", "", text)                    # strip markdown formatting
    text = re.sub(r"\s+", " ", text).strip()
    return text[:1000]


def extract_og_image(url: str) -> str | None:
    """
    Extract native Open Graph image (og:image) or twitter:image from a web page URL.
    Used for Priority A media pairing.
    """
    if not url or not url.startswith("http"):
        return None
    try:
        resp = SESSION.get(url, timeout=8, headers=HEADERS)
        if resp.status_code != 200:
            return None
        soup = BeautifulSoup(resp.text, "lxml")
        
        # Check og:image or twitter:image
        og_tag = soup.find("meta", property="og:image") or soup.find("meta", attrs={"name": "twitter:image"})
        if og_tag and og_tag.get("content"):
            img_url = og_tag["content"].strip()
            if img_url.startswith("//"):
                img_url = "https:" + img_url
            elif img_url.startswith("/"):
                # Handle relative URLs
                from urllib.parse import urlparse
                parsed = urlparse(url)
                img_url = f"{parsed.scheme}://{parsed.netloc}{img_url}"
            return img_url
    except Exception as e:
        log("WARN", "scraper", f"Failed to extract OG image from {url}: {e}")
    return None


# ── 1. Hacker News API Scraper ────────────────────────────────

def scrape_hacker_news(min_score: int = 100) -> list:
    """
    Scrape top Hacker News stories and Show HN items using official Firebase API.
    """
    results = []
    log("INFO", "scraper", f"Scraping Hacker News (min score: {min_score})...")
    
    endpoints = [
        ("https://hacker-news.firebaseio.com/v0/topstories.json", "HN Top"),
        ("https://hacker-news.firebaseio.com/v0/showstories.json", "Show HN"),
    ]

    for ep_url, label in endpoints:
        try:
            resp = SESSION.get(ep_url, timeout=10)
            if resp.status_code != 200:
                continue
            story_ids = resp.json()[:25]  # top 25 item IDs

            for sid in story_ids:
                try:
                    item_resp = SESSION.get(f"https://hacker-news.firebaseio.com/v0/item/{sid}.json", timeout=6)
                    if item_resp.status_code != 200:
                        continue
                    item = item_resp.json()
                    if not item or item.get("type") != "story":
                        continue

                    score = item.get("score", 0)
                    if score < min_score:
                        continue

                    title = item.get("title", "").strip()
                    url = item.get("url") or f"https://news.ycombinator.com/item?id={sid}"
                    by = item.get("by", "community")

                    h = _hash(f"hn_{sid}")
                    if is_seen(h):
                        continue
                    mark_seen(h, url)

                    og_img = extract_og_image(url) if "news.ycombinator.com" not in url else None

                    is_show_hn = title.startswith("Show HN:") or label == "Show HN"
                    content_type = "show_hn" if is_show_hn else "hacker_news"

                    results.append({
                        "type": content_type,
                        "source": f"Hacker News ({label})",
                        "title": title,
                        "body": f"{title} (Posted by @{by} on Hacker News with {score} points)",
                        "url": url,
                        "score": score,
                        "is_video": False,
                        "media_url": og_img,
                    })
                    log("INFO", "scraper", f"Found HN item [{score}pts]: {title[:60]}")

                except Exception as e:
                    continue

        except Exception as e:
            log("ERROR", "scraper", f"HN scrape error for {label}: {e}")

    return results


# ── 2. Hugging Face Daily Papers Scraper ──────────────────────

def scrape_huggingface_papers(limit: int = 10) -> list:
    """
    Scrape trending research papers from Hugging Face Daily Papers API.
    """
    results = []
    log("INFO", "scraper", "Scraping Hugging Face Daily Papers API...")
    url = "https://huggingface.co/api/daily_papers"

    try:
        resp = SESSION.get(url, timeout=12)
        if resp.status_code != 200:
            log("WARN", "scraper", f"HF Daily Papers API returned {resp.status_code}")
            return results

        papers = resp.json()[:limit]

        for p in papers:
            try:
                paper_data = p.get("paper", {})
                title = paper_data.get("title", "").strip()
                summary = _clean_text(paper_data.get("summary", ""))
                paper_id = paper_data.get("id", "")
                paper_url = f"https://huggingface.co/papers/{paper_id}" if paper_id else "https://huggingface.co/papers"
                upvotes = p.get("upvotes", 10)

                if not title or not paper_id:
                    continue

                h = _hash(f"hf_paper_{paper_id}")
                if is_seen(h):
                    continue
                mark_seen(h, paper_url)

                og_img = extract_og_image(paper_url)

                results.append({
                    "type": "paper",
                    "source": "Hugging Face Papers",
                    "title": title,
                    "body": summary if summary else title,
                    "url": paper_url,
                    "score": upvotes * 10,
                    "is_video": False,
                    "media_url": og_img,
                })
                log("INFO", "scraper", f"Found HF Paper [{upvotes}↑]: {title[:60]}")

            except Exception as e:
                continue

    except Exception as e:
        log("ERROR", "scraper", f"HF Papers scrape failed: {e}")

    return results


# ── 3. Reddit Scraper (rising.json) ───────────────────────────

def scrape_reddit(subreddits: list, time_filter: str = "rising") -> list:
    """
    Scrape rising posts from tech subreddits using rising.json endpoint.
    Filtered for comment velocity.
    """
    results = []
    for sub_cfg in subreddits:
        subreddit = sub_cfg["name"]
        min_comments = sub_cfg.get("min_comments", 10)
        url = f"https://www.reddit.com/r/{subreddit}/{time_filter}.json?limit=15"

        try:
            resp = SESSION.get(url, timeout=12)
            if resp.status_code == 403:
                log("WARN", "scraper", f"Reddit 403 for r/{subreddit} — skipping unauthenticated Reddit fetch")
                break
            if resp.status_code != 200:
                continue

            data = resp.json()
            posts = data.get("data", {}).get("children", [])

            for post in posts:
                p = post.get("data", {})
                score = p.get("score", 0)
                num_comments = p.get("num_comments", 0)
                title = p.get("title", "").strip()
                selftext = _clean_text(p.get("selftext", ""))
                permalink = "https://reddit.com" + p.get("permalink", "")
                url_out = p.get("url", "")
                nsfw = p.get("over_18", False)

                if num_comments < min_comments:
                    continue
                if nsfw or not title:
                    continue

                h = _hash(permalink)
                if is_seen(h):
                    continue
                mark_seen(h, permalink)

                body = selftext if len(selftext) > 30 else title
                media_url = url_out if url_out.endswith((".jpg", ".jpeg", ".png", ".gif")) else None

                results.append({
                    "type": "reddit",
                    "source": f"r/{subreddit}",
                    "title": title,
                    "body": body,
                    "url": permalink,
                    "score": score + (num_comments * 5),
                    "is_video": False,
                    "media_url": media_url,
                })
                log("INFO", "scraper", f"Found Reddit post [{num_comments}💬] r/{subreddit}: {title[:60]}")

            time.sleep(random.uniform(1.0, 2.0))

        except Exception as e:
            log("ERROR", "scraper", f"Reddit scrape failed for r/{subreddit}: {e}")

    return results


# ── 4. GitHub Trending & Releases Scraper ────────────────────

def scrape_github_trending(since: str = "daily", language: str = "", min_stars_per_day: int = 100) -> list:
    """
    Scrape GitHub Trending repositories and extract stars velocity.
    """
    results = []
    lang_param = f"?l={language}&since={since}" if language else f"?since={since}"
    url = f"https://github.com/trending{lang_param}"

    try:
        resp = SESSION.get(url, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")

        repo_articles = soup.select("article.Box-row")[:12]

        for article in repo_articles:
            try:
                name_tag = article.select_one("h2 a")
                if not name_tag:
                    continue
                repo_name = name_tag.get_text(strip=True).replace("\n", "").replace(" ", "")
                repo_url = "https://github.com" + name_tag["href"]

                desc_tag = article.select_one("p")
                description = desc_tag.get_text(strip=True) if desc_tag else ""

                stars_tag = article.select_one("a[href$='/stargazers']")
                stars = stars_tag.get_text(strip=True).replace(",", "") if stars_tag else "0"

                today_tag = article.select_one("span.d-inline-block.float-sm-right")
                stars_today_text = today_tag.get_text(strip=True) if today_tag else "0"
                
                # Extract numeric stars today
                stars_today_num = 0
                match = re.search(r"(\d+)", stars_today_text.replace(",", ""))
                if match:
                    stars_today_num = int(match.group(1))

                lang_tag = article.select_one("[itemprop='programmingLanguage']")
                lang = lang_tag.get_text(strip=True) if lang_tag else "Developer Tool"

                h = _hash(repo_url)
                if is_seen(h):
                    continue
                mark_seen(h, repo_url)

                # Get GitHub Open Graph card image
                og_img = f"{repo_url}/repository-open-graph"

                title = f"{repo_name}: {description}" if description else repo_name
                body = f"{repo_name} is a {lang} project gaining {stars_today_text}. {description}"

                results.append({
                    "type": "github",
                    "source": "GitHub Trending",
                    "title": title,
                    "body": body,
                    "url": repo_url,
                    "score": stars_today_num * 10 if stars_today_num > 0 else 500,
                    "is_video": False,
                    "media_url": og_img,
                })
                log("INFO", "scraper", f"Found GitHub Repo [{stars_today_text}]: {repo_name}")

            except Exception as e:
                log("WARN", "scraper", f"Error parsing GitHub repo: {e}")

    except Exception as e:
        log("ERROR", "scraper", f"GitHub trending scrape failed: {e}")

    return results


# ── 5. RSS Feed Scraper ───────────────────────────────────────

def scrape_rss_feeds(feeds: list) -> list:
    """
    Parse RSS/Atom feeds (ArXiv, TechCrunch, HF Blog, etc).
    """
    results = []
    for feed_cfg in feeds:
        name = feed_cfg["name"]
        feed_url = feed_cfg["url"]

        try:
            parsed = feedparser.parse(feed_url)
            entries = parsed.entries[:6]

            for entry in entries:
                title = getattr(entry, "title", "").strip()
                link = getattr(entry, "link", "")
                summary = getattr(entry, "summary", "") or getattr(entry, "description", "")
                summary = _clean_text(summary)[:600]

                if not title or not link:
                    continue

                h = _hash(link)
                if is_seen(h):
                    continue
                mark_seen(h, link)

                og_img = extract_og_image(link)

                results.append({
                    "type": "rss",
                    "source": name,
                    "title": title,
                    "body": summary if summary else title,
                    "url": link,
                    "score": 150,
                    "is_video": False,
                    "media_url": og_img,
                })
                log("INFO", "scraper", f"Found RSS [{name}]: {title[:60]}")

            time.sleep(random.uniform(0.5, 1.0))

        except Exception as e:
            log("ERROR", "scraper", f"RSS feed failed for {name}: {e}")

    return results


# ── Main Orchestrator ─────────────────────────────────────────

def run_scrape(config: dict) -> list:
    """
    Run all configured high-value scrapers and return merged, deduplicated content list.
    Sorted by virality score descending.
    """
    log("INFO", "scraper", "═══ Starting High-Value Content Discovery ═══")
    all_content = []

    sources = config.get("sources", {})

    # 1. Hacker News API
    if sources.get("hacker_news", {}).get("enabled", True):
        min_score = sources["hacker_news"].get("min_score", 100)
        hn_items = scrape_hacker_news(min_score)
        all_content.extend(hn_items)

    # 2. Hugging Face Papers
    if sources.get("huggingface_papers", {}).get("enabled", True):
        limit = sources["huggingface_papers"].get("limit", 10)
        hf_items = scrape_huggingface_papers(limit)
        all_content.extend(hf_items)

    # 3. GitHub Trending
    if sources.get("github_trending", {}).get("enabled", True):
        lang = sources["github_trending"].get("language", "")
        since = sources["github_trending"].get("since", "daily")
        gh_items = scrape_github_trending(since, lang)
        all_content.extend(gh_items)

    # 4. RSS Feeds (ArXiv, TechCrunch, HF Blog)
    if sources.get("rss_feeds", {}).get("enabled", True):
        feeds = sources["rss_feeds"]["feeds"]
        rss_items = scrape_rss_feeds(feeds)
        all_content.extend(rss_items)

    # 5. Reddit Rising
    if sources.get("reddit", {}).get("enabled", True):
        subs = sources["reddit"]["subreddits"]
        time_filter = sources["reddit"].get("time_filter", "rising")
        reddit_items = scrape_reddit(subs, time_filter)
        all_content.extend(reddit_items)

    # Sort by virality score
    all_content.sort(key=lambda x: x.get("score", 0), reverse=True)

    total = len(all_content)
    increment_stat("items_scraped")
    log("SUCCESS", "scraper", f"═══ Discovery complete: {total} new items found ═══")
    return all_content


if __name__ == "__main__":
    import yaml
    with open(os.path.join(os.path.dirname(os.path.dirname(__file__)), "config.yaml")) as f:
        cfg = yaml.safe_load(f)
    from db.models import init_db
    init_db()
    items = run_scrape(cfg)
    print(f"\nTotal items fetched: {len(items)}")
    for item in items[:8]:
        print(f"  [{item['type']}] {item['title'][:70]} (score: {item['score']}) | OG Media: {item.get('media_url') is not None}")
