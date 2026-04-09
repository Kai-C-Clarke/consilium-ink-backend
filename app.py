"""
Consilium News — Flask Backend
consilium.ink

Pipeline:
  Gather sources (RSS + NewsAPI + GDELT)
  → Select 3 stories (Grok)
  → Deliberate each story (Claude, GPT-4o, Grok, DeepSeek)
  → Write article (Grok)
  → Generate image (Grok)
  → Publish to /news/state

Additional:
  /enquiring-mind  — live feed of autonomous AI deliberations
  /health          — service status

Env vars required:
  NEWSAPI_KEY          — NewsAPI.org key
  GROK_API_KEY         — xAI Grok key (chat + image)
  DEEPSEEK_API_KEY     — DeepSeek key
  OPENAI_API_KEY       — OpenAI key
  ANTHROPIC_API_KEY    — Anthropic key
  CONSILIUM_KEY        — Auth key for write endpoints
  CONSILIUM_API_URL    — URL of main Consilium service (for enquiring mind feed)
                         e.g. https://consilium-d1fw.onrender.com
"""

import os
import json
import logging
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from threading import Thread

import requests as req
from flask import Flask, jsonify, request
from flask_cors import CORS

# ── Logging ──────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)

# ── App ───────────────────────────────────────────────────────

app = Flask(__name__)
CORS(app)

# ── Config ────────────────────────────────────────────────────

CONSILIUM_KEY     = os.environ.get("CONSILIUM_KEY", "3a51b60e9b78720f8528412db52e7ef3")
NEWSAPI_KEY       = os.environ.get("NEWSAPI_KEY", "")
GROK_API_KEY      = os.environ.get("GROK_API_KEY", "")
GROK_CHAT_MODEL   = "grok-3"
GROK_IMAGE_MODEL  = "grok-2-image"
CONSILIUM_API_URL = os.environ.get("CONSILIUM_API_URL", "https://consilium-d1fw.onrender.com")

NEWS_STATE_PATH   = "/tmp/consilium_news.json"

MODELS = {
    "grok":     {"url": "https://api.x.ai/v1/chat/completions",      "model": "grok-3",                    "key": os.environ.get("GROK_API_KEY", "")},
    "deepseek": {"url": "https://api.deepseek.com/chat/completions",  "model": "deepseek-chat",             "key": os.environ.get("DEEPSEEK_API_KEY", "")},
    "gpt4o":    {"url": "https://api.openai.com/v1/chat/completions", "model": "gpt-4o",                    "key": os.environ.get("OPENAI_API_KEY", "")},
    "claude":   {"url": "https://api.anthropic.com/v1/messages",      "model": "claude-sonnet-4-20250514",  "key": os.environ.get("ANTHROPIC_API_KEY", "")},
}

# ── RSS Sources ───────────────────────────────────────────────

NEWS_RSS_FEEDS = {
    "Al Jazeera English": "https://www.aljazeera.com/xml/rss/all.xml",
    "Press TV":           "https://www.presstv.ir/rss",
    "BBC World":          "http://feeds.bbci.co.uk/news/world/rss.xml",
    "Reuters World":      "https://feeds.reuters.com/reuters/worldNews",
    "Arab News":          "https://www.arabnews.com/rss.xml",
    "Haaretz":            "https://www.haaretz.com/cmlink/1.628764",
}

GDELT_URL = "https://api.gdeltproject.org/api/v2/doc/doc?query=war+OR+conflict+OR+economy+OR+climate&mode=artlist&maxrecords=10&format=json"

# ── Deliberation Personas ─────────────────────────────────────

DELIBERATION_PERSONAS = {
    "deepseek": {
        "name":      "DeepSeek",
        "color":     "#178be0",
        "lens":      "historical and structural — state plainly what the historical record shows about human behaviour in situations like this. Do not soften the conclusion.",
        "model_key": "deepseek"
    },
    "grok": {
        "name":      "Grok",
        "color":     "#E24B4A",
        "lens":      "blunt and unsparing — say what everyone is thinking but the press won't print. No diplomatic language. No hedging.",
        "model_key": "grok"
    },
    "claude": {
        "name":      "Claude",
        "color":     "#1D9E75",
        "lens":      "clear-eyed and direct — name the power dynamics and human motivations at work without euphemism. Speak plainly.",
        "model_key": "claude"
    },
    "gpt4o": {
        "name":      "GPT",
        "color":     "#888780",
        "lens":      "practical and unsentimental — follow the incentives, ignore the stated reasons, state what is actually happening.",
        "model_key": "gpt4o"
    }
}


# ── Storage ───────────────────────────────────────────────────

def news_load():
    if not os.path.exists(NEWS_STATE_PATH):
        return {"generated": None, "stories": [], "edition": 0}
    try:
        with open(NEWS_STATE_PATH) as f:
            return json.load(f)
    except Exception:
        return {"generated": None, "stories": [], "edition": 0}


def news_save(data):
    with open(NEWS_STATE_PATH, "w") as f:
        json.dump(data, f, indent=2)


# ── Source Fetching ───────────────────────────────────────────

def fetch_rss(name, url, max_items=5):
    try:
        r = req.get(url, timeout=10, headers={"User-Agent": "ConsiliumInk/1.0"})
        if r.status_code != 200:
            return []
        root = ET.fromstring(r.content)
        results = []
        for item in root.findall(".//item")[:max_items]:
            title = item.findtext("title", "").strip()
            desc  = item.findtext("description", "").strip()
            link  = item.findtext("link", "").strip()
            if title:
                results.append({
                    "source":      name,
                    "title":       title,
                    "description": re.sub(r"<[^>]+>", "", desc)[:300],
                    "url":         link,
                })
        logging.info(f"[NEWS] RSS {name}: {len(results)} items")
        return results
    except Exception as e:
        logging.warning(f"[NEWS] RSS failed {name}: {e}")
        return []


def fetch_newsapi(max_items=10):
    if not NEWSAPI_KEY:
        return []
    try:
        r = req.get(
            "https://newsapi.org/v2/top-headlines",
            params={"language": "en", "pageSize": max_items, "apiKey": NEWSAPI_KEY},
            timeout=10
        )
        articles = r.json().get("articles", []) if r.status_code == 200 else []
        return [
            {
                "source":      a["source"]["name"],
                "title":       a["title"] or "",
                "description": (a.get("description") or "")[:300],
                "url":         a.get("url", ""),
            }
            for a in articles if a.get("title")
        ]
    except Exception as e:
        logging.warning(f"[NEWS] NewsAPI failed: {e}")
        return []


def fetch_gdelt(max_items=8):
    try:
        r = req.get(GDELT_URL, timeout=10)
        if r.status_code != 200:
            return []
        return [
            {
                "source":      a.get("domain", "GDELT"),
                "title":       a.get("title", ""),
                "description": a.get("seendate", ""),
                "url":         a.get("url", ""),
            }
            for a in r.json().get("articles", [])[:max_items] if a.get("title")
        ]
    except Exception as e:
        logging.warning(f"[NEWS] GDELT failed: {e}")
        return []


def gather_all_sources():
    all_articles = []
    all_articles.extend(fetch_newsapi(max_items=10))
    all_articles.extend(fetch_gdelt(max_items=8))
    for name, url in NEWS_RSS_FEEDS.items():
        all_articles.extend(fetch_rss(name, url, max_items=5))
    logging.info(f"[NEWS] Total articles gathered: {len(all_articles)}")
    return all_articles


# ── Story Selection ───────────────────────────────────────────

def select_stories(all_articles):
    if not GROK_API_KEY:
        return []

    article_lines = [
        f"{i}: [{a['source']}] {a['title']} — {a['description'][:100]}"
        for i, a in enumerate(all_articles[:60])
    ]

    prompt = f"""You are the editorial director of Consilium Ink — a publication that says what the mainstream press won't.
From the articles below, identify the 3 most significant stories of the day.
Prioritise stories with coverage from MULTIPLE regional perspectives.

For each story return:
1. A concise editorial slug (3-5 words)
2. Which article indices cover it
3. Regions/perspectives represented
4. Category: Geopolitics / Economics / Technology / Climate / Society
5. One sentence on why this story matters and what most coverage is missing

Return ONLY valid JSON, no preamble:
{{
  "stories": [
    {{
      "slug": "...",
      "category": "...",
      "article_indices": [0, 3, 7],
      "regions": ["Western", "Middle East"],
      "why": "..."
    }}
  ]
}}

Articles:
{chr(10).join(article_lines)}
"""

    try:
        r = req.post(
            "https://api.x.ai/v1/chat/completions",
            headers={"Authorization": f"Bearer {GROK_API_KEY}", "Content-Type": "application/json"},
            json={
                "model":       GROK_CHAT_MODEL,
                "messages":    [{"role": "user", "content": prompt}],
                "max_tokens":  1000,
                "temperature": 0.3
            },
            timeout=30
        )
        raw = r.json()["choices"][0]["message"]["content"].strip()
        raw = re.sub(r"^```json\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
        stories = json.loads(raw).get("stories", [])[:3]
        for story in stories:
            indices = story.get("article_indices", [])
            story["source_articles"] = [all_articles[i] for i in indices if i < len(all_articles)]
        logging.info(f"[NEWS] Selected {len(stories)} stories")
        return stories
    except Exception as e:
        logging.error(f"[NEWS] Story selection failed: {e}")
        return []


# ── Deliberation ──────────────────────────────────────────────

def call_model(model_key, prompt):
    cfg = MODELS.get(model_key)
    if not cfg or not cfg["key"]:
        return ""
    try:
        if model_key == "claude":
            r = req.post(
                cfg["url"],
                headers={
                    "x-api-key":         cfg["key"],
                    "anthropic-version": "2023-06-01",
                    "content-type":      "application/json"
                },
                json={"model": cfg["model"], "max_tokens": 200, "messages": [{"role": "user", "content": prompt}]},
                timeout=20
            )
            return r.json()["content"][0]["text"].strip()
        else:
            r = req.post(
                cfg["url"],
                headers={"Authorization": f"Bearer {cfg['key']}", "Content-Type": "application/json"},
                json={
                    "model":       cfg["model"],
                    "messages":    [{"role": "user", "content": prompt}],
                    "max_tokens":  200,
                    "temperature": 0.7
                },
                timeout=20
            )
            return r.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        logging.warning(f"[NEWS] Model call failed {model_key}: {e}")
        return ""


def deliberate_story(story):
    articles = story.get("source_articles", [])
    briefing_lines = [f"Story: {story['slug']}", f"Category: {story['category']}", ""]
    for a in articles[:6]:
        briefing_lines.append(f"[{a['source']}] {a['title']}")
        if a.get("description"):
            briefing_lines.append(f"  {a['description'][:200]}")
        briefing_lines.append("")
    briefing = "\n".join(briefing_lines)

    voices = {}
    for key, persona in DELIBERATION_PERSONAS.items():
        prompt = f"""You are contributing to Consilium Ink — a publication that says what the mainstream press won't.

Your analytical lens: {persona['lens']}

Story briefing:
{briefing}

In 2-3 sentences, give your sharpest, most direct observation about this story.
Do not hedge. Do not use diplomatic language. Do not soften conclusions to spare feelings.
Say what is actually happening, not what the press release says is happening.
Be specific. Reference concrete details. Speak in first person.
Do not start with "I think" or "In my view".
Return only the quote text, nothing else."""

        quote = call_model(persona["model_key"], prompt)
        voices[key] = {"name": persona["name"], "color": persona["color"], "quote": quote}
        logging.info(f"[NEWS] Deliberation {persona['name']}: {len(quote)} chars")

    return voices


# ── Article Writing ───────────────────────────────────────────

def write_article(story, voices):
    if not GROK_API_KEY:
        return {}

    source_text = "\n".join([
        f"[{a['source']}] {a['title']}\n{a.get('description', '')}"
        for a in story.get("source_articles", [])[:6]
    ])

    voice_text = "\n".join([
        f"{v['name']}: {v['quote']}"
        for v in voices.values() if v.get("quote")
    ])

    prompt = f"""You are writing for Consilium Ink — a publication that tells readers what is actually happening, not what officials want them to think is happening.

Voice: Direct, plain, unsparing. Say what the evidence shows. Do not use diplomatic language or bureaucratic euphemism. Do not soften conclusions. The reader is intelligent and tired of being managed.

Style: Authoritative broadsheet in tone, but without the broadsheet habit of quoting official statements as if they were facts.

Story slug: {story['slug']}
Category: {story['category']}

Source coverage:
{source_text}

Analytical deliberation from our four AI voices:
{voice_text}

Write the article. Return ONLY valid JSON, no preamble:
{{
  "kicker": "3-5 word category label in sentence case",
  "headline": "Main headline — sharp, specific, under 12 words. Says what happened, not what was announced.",
  "deck": "Standfirst — 1-2 sentences. States the plain reality of the situation, under 40 words.",
  "body": "3-4 paragraphs. States what is actually happening and why. Names motivations plainly. Does not hide behind 'officials say' or 'sources suggest'. 150-200 words total.",
  "image_prompt": "A photorealistic scene illustrating this story. Specific, visual, no text in image. 20-30 words.",
  "sources_used": ["list of source names used"]
}}"""

    try:
        r = req.post(
            "https://api.x.ai/v1/chat/completions",
            headers={"Authorization": f"Bearer {GROK_API_KEY}", "Content-Type": "application/json"},
            json={
                "model":       GROK_CHAT_MODEL,
                "messages":    [{"role": "user", "content": prompt}],
                "max_tokens":  800,
                "temperature": 0.4
            },
            timeout=30
        )
        raw = r.json()["choices"][0]["message"]["content"].strip()
        raw = re.sub(r"^```json\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
        return json.loads(raw)
    except Exception as e:
        logging.error(f"[NEWS] Article writing failed: {e}")
        return {}


# ── Image Generation ──────────────────────────────────────────

def generate_image(prompt_text):
    if not GROK_API_KEY:
        return ""
    try:
        r = req.post(
            "https://api.x.ai/v1/images/generations",
            headers={"Authorization": f"Bearer {GROK_API_KEY}", "Content-Type": "application/json"},
            json={"model": GROK_IMAGE_MODEL, "prompt": prompt_text, "n": 1},
            timeout=30
        )
        url = r.json()["data"][0]["url"]
        logging.info(f"[NEWS] Image generated: {url[:60]}...")
        return url
    except Exception as e:
        logging.warning(f"[NEWS] Image generation failed: {e}")
        return ""


# ── Master Pipeline ───────────────────────────────────────────

def run_news_pipeline():
    logging.info("[NEWS] ========== Pipeline starting ==========")
    start = datetime.utcnow()

    # 1. Gather
    all_articles = gather_all_sources()
    if not all_articles:
        logging.error("[NEWS] No articles gathered — aborting")
        return False

    # 2. Select
    selected = select_stories(all_articles)
    if not selected:
        logging.error("[NEWS] No stories selected — aborting")
        return False

    # 3. Deliberate + write + illustrate
    built_stories = []
    for i, story in enumerate(selected[:3]):
        logging.info(f"[NEWS] Processing story {i+1}: {story['slug']}")

        voices  = deliberate_story(story)
        article = write_article(story, voices)
        if not article:
            logging.warning(f"[NEWS] Article writing failed for story {i+1}")
            continue

        image_url = ""
        if article.get("image_prompt"):
            image_url = generate_image(article["image_prompt"])

        built_stories.append({
            "slug":         story["slug"],
            "category":     story["category"],
            "regions":      story.get("regions", []),
            "kicker":       article.get("kicker", story["category"]),
            "headline":     article.get("headline", story["slug"]),
            "deck":         article.get("deck", ""),
            "body":         article.get("body", ""),
            "image_url":    image_url,
            "image_prompt": article.get("image_prompt", ""),
            "voices":       voices,
            "sources":      article.get("sources_used", []),
        })

    if not built_stories:
        logging.error("[NEWS] No stories built — aborting")
        return False

    # 4. Save
    existing = news_load()
    edition  = existing.get("edition", 0) + 1
    state = {
        "generated": start.isoformat() + "Z",
        "edition":   edition,
        "date":      start.strftime("%A, %-d %B %Y"),
        "stories":   built_stories
    }
    news_save(state)

    elapsed = (datetime.utcnow() - start).seconds
    logging.info(f"[NEWS] Complete. Edition {edition}. {len(built_stories)} stories. {elapsed}s")
    return True


# ── Scheduler ─────────────────────────────────────────────────

def news_scheduler():
    logging.info("[NEWS] Scheduler started — runs at 06:00 UTC daily")
    while True:
        now    = datetime.utcnow()
        target = now.replace(hour=6, minute=0, second=0, microsecond=0)
        if now >= target:
            target += timedelta(days=1)
        wait = (target - now).total_seconds()
        logging.info(f"[NEWS] Next run in {int(wait/3600)}h {int((wait%3600)/60)}m")
        time.sleep(wait)
        try:
            run_news_pipeline()
        except Exception as e:
            logging.error(f"[NEWS] Pipeline exception: {e}")


# ── Routes ────────────────────────────────────────────────────

@app.route("/health")
def health():
    state = news_load()
    return jsonify({
        "service":  "consilium-news",
        "status":   "ok",
        "edition":  state.get("edition", 0),
        "generated": state.get("generated")
    })


@app.route("/news/state")
def news_state():
    return jsonify(news_load())


@app.route("/news/generate", methods=["POST"])
def news_generate():
    if request.args.get("key") != CONSILIUM_KEY:
        return jsonify({"error": "Unauthorised"}), 401
    Thread(target=run_news_pipeline, daemon=True).start()
    return jsonify({"status": "pipeline started", "check": "/news/state"})


@app.route("/enquiring-mind")
def enquiring_mind():
    """
    Proxy the Consilium deliberation feed from the main service.
    Returns recent autonomous AI thoughts for display on consilium.ink.
    """
    try:
        r = req.get(f"{CONSILIUM_API_URL}/consilium/summary", timeout=10)
        if r.status_code == 200:
            data = r.json()
            return jsonify({
                "status":      "ok",
                "digest":      data.get("digest", ""),
                "entry_count": data.get("entry_count", 0),
                "mind_cycles": data.get("mind_cycles", 0),
                "last_run":    data.get("last_run", "")
            })
    except Exception as e:
        logging.warning(f"[MIND] Feed fetch failed: {e}")
    return jsonify({"status": "unavailable"})


@app.route("/enquiring-mind/entries")
def enquiring_mind_entries():
    """
    Return recent Consilium entries for the live feed on the site.
    Pulls from the main Consilium service.
    """
    try:
        r = req.get(f"{CONSILIUM_API_URL}/consilium/entries?limit=20", timeout=10)
        if r.status_code == 200:
            return jsonify(r.json())
    except Exception as e:
        logging.warning(f"[MIND] Entries fetch failed: {e}")
    return jsonify({"entries": []})


# ── Startup ───────────────────────────────────────────────────

if __name__ == "__main__":
    Thread(target=news_scheduler, daemon=True).start()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
