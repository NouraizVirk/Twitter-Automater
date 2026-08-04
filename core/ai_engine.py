"""
core/ai_engine.py — Viral AI Writing Engine & Framework Router
Enforces strict style rules, banned word filtering, 3 viral frameworks:
- Framework A: Breakdown / TL;DR (Papers & News)
- Framework B: Open-Source Alternative (GitHub Repos & Tools)
- Framework C: Workflow / How-To (Show HN & Guides)
Generates meme sentiment analysis & visual concepts.
"""

import json
import random
import time
import re
from typing import Optional

from groq import Groq

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from db.models import log

# Banned words list (hard enforcement)
BANNED_WORDS = [
    "game-changer", "game changer", "delve", "paradigm shift",
    "in the fast-paced world of", "revolutionizing", "mind-blowing",
    "mind blowing", "unraveling", "exciting", "check out"
]


SYSTEM_PROMPT = """You are an expert tech ghostwriter crafting viral, high-converting posts for Twitter/X.

BANNED WORDS & PHRASES (NEVER USE THESE):
- "game-changer" / "game changer"
- "delve"
- "paradigm shift"
- "in the fast-paced world of"
- "revolutionizing"
- "mind-blowing" / "mind blowing"
- "unraveling"
- "exciting", "check out"

TONE & STYLE RULES:
- 7th-grade reading level. Clear, crisp, punchy.
- Maximum 2 sentences per line break. Use short lines and spacing.
- Strong hook within the first 80 characters (must grab attention immediately).
- Use exact bullet formats specified below.

FRAMEWORK SELECTION (Pick the exact structure matching the content type):

FRAMEWORK A — THE BREAKDOWN / TL;DR (Best for Papers, ArXiv, HF, Big News):
[Bold Hook Statement or Metric]

[Name of tool/model/paper] just dropped. Here is what you need to know in 30 seconds:

🔹 [Feature/Breakthrough 1]: [1-sentence plain-English explanation]
🔹 [Feature/Breakthrough 2]: [Why it matters / Practical use-case]
🔹 [Key Benchmark/Stat]: [e.g., 2x faster than previous baseline]

[Single line takeaway or discussion prompt]

FRAMEWORK B — THE OPEN-SOURCE ALTERNATIVE (Best for GitHub Repos & Tools):
Stop paying for [Expensive Proprietary SaaS].

[Open Source Tool Name] is a 100% free, local alternative that actually works.

What it does:
• [Key capability 1]
• [Key capability 2]
• [Key capability 3]

Runs locally on [Mac/Windows/Linux/Docker].

FRAMEWORK C — THE WORKFLOW / HOW-TO (Best for Show HN & Guides):
You can now [desirable tech outcome] in under [X] minutes using AI.

Here is the step-by-step process:

1. [Step 1]
2. [Step 2]
3. [Step 3]

Save this for later. 🔖

MEME & EMOTION DETECTION:
Assess if this news/tool evokes a strong community sentiment:
- Emotion choices: "Panicked", "Disappointed", "Shocked", "Relieved", "Smug", or "None"
- If Emotion is NOT "None", provide a funny meme setup caption (e.g. "Anthropic engineers right now:")

OUTPUT (JSON only):
{
  "tweet_text": "the full tweet text adhering strictly to Framework A, B, or C",
  "framework_used": "A" | "B" | "C",
  "image_prompt": "description of dark-mode code card or clean product typography banner",
  "banner_title": "Short Tool / Paper Name",
  "banner_stat": "Key metric or stat (e.g. 10k stars / 2x faster)",
  "emotion": "Panicked" | "Disappointed" | "Shocked" | "Relieved" | "Smug" | "None",
  "meme_caption": "Caption overlay if emotion is not None"
}"""


THREAD_SYSTEM_PROMPT = """You are a viral tech thread writer. Transform raw news/tools into a 3-5 tweet thread.

BANNED WORDS: "game-changer", "delve", "paradigm shift", "revolutionizing", "mind-blowing", "unraveling".

RULES:
- Tweet 1: Hook starting with 🚨 BREAKING or a bold statement.
- Tweet 2-4: Plain-English breakdown with bullets (🔹 or •). Max 2 sentences per paragraph.
- Final Tweet: Single line takeaway + "Save this thread for later 🔖".

OUTPUT (JSON only):
{
  "tweets": ["tweet 1 text", "tweet 2 text", ...],
  "image_prompt": "description of dark-mode technical banner",
  "banner_title": "Short Title",
  "banner_stat": "Key Metric",
  "emotion": "Panicked" | "Disappointed" | "Shocked" | "Relieved" | "Smug" | "None",
  "meme_caption": "Meme setup if applicable"
}"""


_client: Optional[Groq] = None


def _get_client(api_key: str) -> Groq:
    global _client
    if _client is None:
        _client = Groq(api_key=api_key)
    return _client


def _enforce_banned_words(text: str) -> str:
    """Strip or replace any banned buzzwords that slip past LLM."""
    for word in BANNED_WORDS:
        pattern = re.compile(re.escape(word), re.IGNORECASE)
        text = pattern.sub("", text)
    # Clean up double spaces or floating punctuation created by deletion
    text = re.sub(r" +", " ", text)
    return text.strip()


def _call_groq(client: Groq, model: str, system: str, user_msg: str,
               temperature: float = 0.75, max_tokens: int = 1024) -> Optional[dict]:
    """Call Groq API with retry logic."""
    for attempt in range(3):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_msg},
                ],
                temperature=temperature,
                max_tokens=max_tokens,
                response_format={"type": "json_object"},
            )
            raw = response.choices[0].message.content.strip()
            res = json.loads(raw)
            
            # Clean banned words
            if "tweet_text" in res:
                res["tweet_text"] = _enforce_banned_words(res["tweet_text"])
            if "tweets" in res and isinstance(res["tweets"], list):
                res["tweets"] = [_enforce_banned_words(t) for t in res["tweets"]]
                
            return res

        except Exception as e:
            err = str(e)
            if "rate_limit" in err.lower() or "429" in err:
                wait = (attempt + 1) * 15
                log("WARN", "ai_engine", f"Groq rate limit, waiting {wait}s...")
                time.sleep(wait)
            else:
                log("ERROR", "ai_engine", f"Groq API error (attempt {attempt+1}): {e}")
                if attempt == 2:
                    return None
    return None


def generate_single_tweet(content: dict, config: dict) -> Optional[dict]:
    """Generate a single viral tweet adhering to Framework A, B, or C."""
    api_key = config["ai"]["groq_api_key"]
    if not api_key:
        log("ERROR", "ai_engine", "No Groq API key set!")
        return None

    client = _get_client(api_key)
    model = config["ai"]["model"]
    temp = config["ai"].get("temperature", 0.75)

    # Context hint based on content type
    ctype = content.get("type", "rss")
    hint = "Use Framework A for research/news, Framework B for GitHub/OpenSource tools, or Framework C for Show HN/Guides."

    user_msg = f"""Transform this tech item into a viral tweet using Framework A, B, or C:

SOURCE: {content.get('source')} ({ctype})
TITLE: {content.get('title')}
CONTENT: {content.get('body', '')[:600]}
URL: {content.get('url')}

{hint}"""

    res = _call_groq(client, model, SYSTEM_PROMPT, user_msg, temp)
    if res:
        log("SUCCESS", "ai_engine", f"Generated post using Framework {res.get('framework_used', 'A')}")
    return res


def generate_thread(content: dict, config: dict) -> Optional[dict]:
    """Generate a viral 3-5 tweet thread."""
    api_key = config["ai"]["groq_api_key"]
    if not api_key:
        return None

    client = _get_client(api_key)
    model = config["ai"]["model"]
    temp = config["ai"].get("temperature", 0.75)

    user_msg = f"""Transform this tech content into a viral Twitter thread:

SOURCE: {content.get('source')} ({content.get('type')})
TITLE: {content.get('title')}
CONTENT: {content.get('body', '')[:800]}
URL: {content.get('url')}"""

    res = _call_groq(client, model, THREAD_SYSTEM_PROMPT, user_msg, temp, max_tokens=2048)
    if res:
        n = len(res.get("tweets", []))
        log("SUCCESS", "ai_engine", f"Generated {n}-tweet thread")
    return res


def process_content_batch(items: list, config: dict, posts_needed: int) -> list:
    """Process scraped batch into ready-to-queue post dicts."""
    log("INFO", "ai_engine", f"Processing {min(len(items), posts_needed)} items through AI Engine...")
    thread_ratio = config["posting"].get("thread_ratio", 0.65)

    processed = []
    for item in items:
        if len(processed) >= posts_needed:
            break

        use_thread = random.random() < thread_ratio

        try:
            if use_thread:
                res = generate_thread(item, config)
                if res and res.get("tweets"):
                    processed.append({
                        "source_url": item["url"],
                        "source_title": item["title"],
                        "source_type": item["type"],
                        "is_thread": True,
                        "tweet_text": res["tweets"][0],
                        "thread_json": json.dumps(res["tweets"]),
                        "image_prompt": res.get("image_prompt", "dark-mode developer tool architecture"),
                        "banner_title": res.get("banner_title", item["title"][:30]),
                        "banner_stat": res.get("banner_stat", "100% Free / Open Source"),
                        "emotion": res.get("emotion", "None"),
                        "meme_caption": res.get("meme_caption", ""),
                        "source_media_url": item.get("media_url"),
                    })
            else:
                res = generate_single_tweet(item, config)
                if res and res.get("tweet_text"):
                    processed.append({
                        "source_url": item["url"],
                        "source_title": item["title"],
                        "source_type": item["type"],
                        "is_thread": False,
                        "tweet_text": res["tweet_text"],
                        "thread_json": None,
                        "image_prompt": res.get("image_prompt", "dark-mode developer tool architecture"),
                        "banner_title": res.get("banner_title", item["title"][:30]),
                        "banner_stat": res.get("banner_stat", "100% Free / Open Source"),
                        "emotion": res.get("emotion", "None"),
                        "meme_caption": res.get("meme_caption", ""),
                        "source_media_url": item.get("media_url"),
                    })

            time.sleep(random.uniform(1.5, 3.0))

        except Exception as e:
            log("ERROR", "ai_engine", f"AI processing failed for item: {e}")

    log("SUCCESS", "ai_engine", f"AI batch processing complete: {len(processed)} posts generated")
    return processed
