"""
Consilium News — Flask Backend
consilium.ink

Pipeline:
  Gather sources (RSS + NewsAPI + GDELT)
  → Select 3 stories (DeepSeek) — minimum 2 corroborating sources
  → Deliberate each story (Claude, GPT-4o, Grok, DeepSeek)
  → Write article (DeepSeek)
  → Generate visual (Grok image for news / SVG for Great Acceleration)
  → Publish to /news/state

Additional:
  /enquiring-mind         — live Consilium autonomous deliberation feed
  /enquiring-mind/entries — recent entries for live ticker
  /health                 — service status

Env vars required:
  NEWSAPI_KEY          — NewsAPI.org key
  GROK_API_KEY         — xAI Grok key (chat + image)
  DEEPSEEK_API_KEY     — DeepSeek key
  OPENAI_API_KEY       — OpenAI key
  ANTHROPIC_API_KEY    — Anthropic key
  CONSILIUM_KEY        — Auth key for write endpoints
  CONSILIUM_API_URL    — URL of main Consilium service
                         e.g. https://consilium-d1fw.onrender.com
  MEMORY_KEY           — Key for working memory server
  MEMORY_SERVER_URL    — URL of working memory server
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

# ── Usage Analytics ───────────────────────────────────────────
ANALYTICS_FILE = "/mnt/data/analytics.json"

def _load_analytics():
    try:
        with open(ANALYTICS_FILE) as f:
            return json.load(f)
    except Exception:
        return {"total": 0, "endpoints": {}, "daily": {}, "api_hits": 0}

def _save_analytics(data):
    try:
        with open(ANALYTICS_FILE, "w") as f:
            json.dump(data, f)
    except Exception:
        pass

@app.before_request
def track_request():
    path = request.path
    # Only track meaningful endpoints, skip health spam
    if path in ("/health",):
        return
    try:
        data = _load_analytics()
        data["total"] = data.get("total", 0) + 1
        eps = data.get("endpoints", {})
        eps[path] = eps.get(path, 0) + 1
        data["endpoints"] = eps
        # Daily counter
        today = datetime.utcnow().strftime("%Y-%m-%d")
        daily = data.get("daily", {})
        daily[today] = daily.get(today, 0) + 1
        data["daily"] = daily
        # API hit counter
        if path.startswith("/api/"):
            data["api_hits"] = data.get("api_hits", 0) + 1
        _save_analytics(data)
    except Exception:
        pass

# ── Config ────────────────────────────────────────────────────

CONSILIUM_KEY     = os.environ.get("CONSILIUM_KEY", "3a51b60e9b78720f8528412db52e7ef3")
NEWSAPI_KEY       = os.environ.get("NEWSAPI_KEY", "")
GROK_API_KEY      = os.environ.get("GROK_API_KEY", "")
GROK_CHAT_MODEL   = "grok-3"
DEEPSEEK_URL      = "https://api.deepseek.com/chat/completions"
DEEPSEEK_CHAT_MODEL = "deepseek-chat"
GROK_IMAGE_MODEL  = "grok-imagine-image"
CONSILIUM_API_URL = os.environ.get("CONSILIUM_API_URL", "https://consilium-d1fw.onrender.com")
SELF_URL          = os.environ.get("SELF_URL", "https://claude-composer.onrender.com")

MEMORY_SERVER_URL = os.environ.get("MEMORY_SERVER_URL", "https://claude-working-memory.onrender.com")
MEMORY_KEY        = os.environ.get("MEMORY_KEY", "")

MODELS = {
    "grok":     {"url": "https://api.x.ai/v1/chat/completions",      "model": "grok-3",                   "key": os.environ.get("GROK_API_KEY", "")},
    "deepseek": {"url": "https://api.deepseek.com/chat/completions",  "model": "deepseek-chat",            "key": os.environ.get("DEEPSEEK_API_KEY", "")},
    "gpt4o":    {"url": "https://api.openai.com/v1/chat/completions", "model": "gpt-4o",                   "key": os.environ.get("OPENAI_API_KEY", "")},
    "claude":   {"url": "https://api.anthropic.com/v1/messages",      "model": "claude-sonnet-4-6", "key": os.environ.get("ANTHROPIC_API_KEY", "")},
}

# ── RSS Sources ───────────────────────────────────────────────

# ── World / Politics / Economics feeds ───────────────────────
NEWS_RSS_FEEDS = {
    # ── Global / Western ──────────────────────────────────────
    "Al Jazeera English": "https://www.aljazeera.com/xml/rss/all.xml",
    "BBC World":          "http://feeds.bbci.co.uk/news/world/rss.xml",
    "France 24":          "https://www.france24.com/en/rss",
    "DW World":           "https://rss.dw.com/rdf/rss-en-world",
    "The Conversation":   "https://theconversation.com/articles.atom",
    "Arab News":          "https://www.arabnews.com/rss.xml",
    "MEED":               "https://www.meed.com/rss/",
    # ── Africa ────────────────────────────────────────────────
    "AllAfrica":          "https://allafrica.com/tools/headlines/rdf/latest/headlines.rdf",
    "Mail & Guardian":    "https://mg.co.za/feed/",
    "African Business":    "https://african.business/feed",
    # ── Asia / Pacific ────────────────────────────────────────
    "The Hindu":          "https://www.thehindu.com/feeder/default.rss",
    "The Wire India":     "https://thewire.in/feed",
    "The Diplomat":       "https://thediplomat.com/feed/",
    # ── Latin America / Global South ─────────────────────────
    "Global Voices":      "https://globalvoices.org/feed/",
    # ── China ─────────────────────────────────────────────────
    "Global Times":       "https://www.globaltimes.cn/rss/outbrain.xml",
    "SCMP World":         "https://www.scmp.com/rss/2/feed",
    # ── Russia ────────────────────────────────────────────────
    "Moscow Times":       "https://www.themoscowtimes.com/rss/news",
    "Meduza":             "https://meduza.io/rss/en/all",
    # ── Iran ──────────────────────────────────────────────────
    "Iran International": "https://www.iranintl.com/en/rss",
    "IranWire":           "https://iranwire.com/en/feed/",
    # ── Middle East regional ──────────────────────────────────
    "Al-Monitor":         "https://www.al-monitor.com/rss",
}

# ── Science / Medicine / Technology feeds ─────────────────────
SCIENCE_RSS_FEEDS = {
    "Nature News":           "https://www.nature.com/nature.rss",
    "New Scientist":         "https://www.newscientist.com/feed/home/",
    "arXiv AI":              "https://rss.arxiv.org/rss/cs.AI",
    "arXiv Quantitative Bio":"https://rss.arxiv.org/rss/q-bio.QM",
    "arXiv Physics":         "https://rss.arxiv.org/rss/physics.pop-ph",
    "Wellcome":              "https://wellcome.org/news/rss.xml",
    "Carbon Brief":          "https://www.carbonbrief.org/feed",
    "MIT Tech Review":       "https://www.technologyreview.com/feed/",
    "Ars Technica Science":  "https://feeds.arstechnica.com/arstechnica/science",
    "Ars Technica Tech":     "https://feeds.arstechnica.com/arstechnica/technology-lab",
    "IEEE Spectrum":         "https://spectrum.ieee.org/feeds/feed.rss",
    "Space.com":             "https://www.space.com/feeds/all",
    "Medical Xpress":        "https://medicalxpress.com/rss-feed/",
    "Phys.org":              "https://phys.org/rss-feed/",
}

# ── Arts / Culture / Music feeds ──────────────────────────────
ARTS_RSS_FEEDS = {
    "The Art Newspaper":     "https://www.theartnewspaper.com/rss",
    "Hyperallergic":         "https://hyperallergic.com/feed/",
    "Pitchfork":             "https://pitchfork.com/rss/news/",
    "The Wire Music":        "https://thewire.co.uk/rss",
    "Creative Applications": "https://www.creativeapplications.net/feed/",
    "Resident Advisor":      "https://ra.co/xml/news.xml",
}

GDELT_URL         = "https://api.gdeltproject.org/api/v2/doc/doc?query=war+OR+conflict+OR+economy+OR+climate+OR+Africa+OR+Asia+OR+Latin+America+OR+Sudan+OR+Congo+OR+India+OR+Japan+OR+Brazil&mode=artlist&maxrecords=15&format=json"
GDELT_SCIENCE_URL = "https://api.gdeltproject.org/api/v2/doc/doc?query=AI+medicine+OR+climate+breakthrough+OR+scientific+discovery&mode=artlist&maxrecords=8&format=json"
GDELT_TECH_URL    = "https://api.gdeltproject.org/api/v2/doc/doc?query=transport+innovation+OR+engineering+breakthrough+OR+space+mission&mode=artlist&maxrecords=8&format=json"

# ── Section categories ─────────────────────────────────────────
CATEGORIES = [
    "Geopolitics",
    "Economics",
    "AI & Society",
    "Climate",
    "Science & Discovery",
    "Technology",
    "Arts & Culture",
    "On Existence",
    "Great Acceleration",
]

# Stories per section per edition
SECTION_TARGETS = {
    "world":    2,   # Geopolitics + Economics
    "science":  1,   # Science & Discovery / Great Acceleration
    "tech":     1,   # Technology
    "arts":     1,   # Arts & Culture
}

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
    try:
        r = req.get(f"{MEMORY_SERVER_URL}/memory/projects", timeout=10)
        if r.status_code == 200:
            data = r.json()
            if "consilium_news" in data:
                return data["consilium_news"]
    except Exception as e:
        logging.warning(f"[NEWS] Memory load failed: {e}")
    return {"generated": None, "stories": [], "edition": 0}


def news_save(data):
    if not MEMORY_KEY:
        logging.error("[NEWS] No MEMORY_KEY")
        return False
    try:
        r = req.post(
            f"{MEMORY_SERVER_URL}/memory/projects?key={MEMORY_KEY}",
            json={"consilium_news": data},
            timeout=15
        )
        if r.status_code == 200:
            logging.info(f"[NEWS] State saved — Edition {data.get('edition')}")
            return True
        logging.error(f"[NEWS] Memory save failed: {r.status_code}")
        return False
    except Exception as e:
        logging.error(f"[NEWS] Memory save exception: {e}")
        return False

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


def fetch_gdelt(url=GDELT_URL, max_items=8):
    try:
        r = req.get(url, timeout=10)
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
    """Gather all source pools: news, science, tech, arts.
    Requests are staggered with small delays to avoid DNS cache overflow
    on Render's internal resolver when many domains are hit simultaneously.
    """
    news_articles = []
    news_articles.extend(fetch_newsapi(max_items=10))
    time.sleep(1)
    news_articles.extend(fetch_gdelt(GDELT_URL, max_items=8))
    time.sleep(1)
    for name, url in NEWS_RSS_FEEDS.items():
        news_articles.extend(fetch_rss(name, url, max_items=5))
        time.sleep(0.5)

    science_articles = []
    time.sleep(1)
    science_articles.extend(fetch_gdelt(GDELT_SCIENCE_URL, max_items=6))
    time.sleep(1)
    for name, url in SCIENCE_RSS_FEEDS.items():
        science_articles.extend(fetch_rss(name, url, max_items=4))
        time.sleep(0.5)

    tech_articles = []
    time.sleep(1)
    tech_articles.extend(fetch_gdelt(GDELT_TECH_URL, max_items=6))
    for name, url in ARTS_RSS_FEEDS.items():
        # Arts feeds also go into tech_articles pool initially; selector separates them
        pass

    arts_articles = []
    time.sleep(1)
    for name, url in ARTS_RSS_FEEDS.items():
        arts_articles.extend(fetch_rss(name, url, max_items=4))
        time.sleep(0.5)

    # Tag pools
    for a in news_articles:    a["pool"] = "news"
    for a in science_articles: a["pool"] = "science"
    for a in tech_articles:    a["pool"] = "tech"
    for a in arts_articles:    a["pool"] = "arts"

    logging.info(f"[NEWS] Gathered {len(news_articles)} news + {len(science_articles)} science + {len(tech_articles)} tech + {len(arts_articles)} arts")
    return news_articles, science_articles, tech_articles, arts_articles


# ── Story Selection ───────────────────────────────────────────

def select_stories(news_articles, science_articles, tech_articles=None, arts_articles=None):
    """
    Select stories across all sections:
    - 2 world stories (Geopolitics / Economics / AI & Society / Climate)
    - 1 science story (Science & Discovery / Great Acceleration)
    - 1 technology story (Technology)
    - 1 arts story (Arts & Culture)
    Returns up to 5 stories.
    """
    deepseek_key = os.environ.get("DEEPSEEK_API_KEY", "")
    if tech_articles is None: tech_articles = []
    if arts_articles is None: arts_articles = []

    all_selected = []

    # ── Pass 1: 2 world/society stories ─────────────────────────
    news_lines = [
        f"{i}: [{a['source']}] {a['title']} — {a['description'][:100]}"
        for i, a in enumerate(news_articles[:60])
    ]

    news_prompt = f"""You are the editorial director of Consilium Ink — a newspaper written by AIs, for AIs, readable by humans.
From the articles below, identify the 2 most significant world stories of the day.

RULES:
1. Only select stories CORROBORATED by at least 2 independent sources.
2. Only select events that have ALREADY HAPPENED — no previews or predictions.
3. Prioritise stories with coverage from multiple regional perspectives.

CATEGORIES:
- Geopolitics: wars, diplomacy, elections, international power
- Economics: markets, trade, sanctions, labour, energy prices
- AI & Society: the relationship between AI and human life — surveillance, labour displacement, algorithmic decision-making, AI in warfare, regulation, social media manipulation. Core question: symbiotic or parasitic?
- Climate: environment, extreme weather, energy transition

Actively look for AI & Society stories — they are often under-reported as such.

Return ONLY valid JSON:
{{
  "stories": [
    {{
      "slug": "...",
      "category": "...",
      "article_indices": [0, 3],
      "regions": ["Western"],
      "why": "..."
    }}
  ]
}}

Articles:
{chr(10).join(news_lines)}
"""

    # ── Pass 2: 1 science/discovery story ───────────────────────
    sci_lines = [
        f"{i}: [{a['source']}] {a['title']} — {a['description'][:120]}"
        for i, a in enumerate(science_articles[:40])
    ]

    sci_prompt = f"""You are the science editor of Consilium Ink — a newspaper written by AIs, for AIs.
From the articles below, identify the 1 most significant science or discovery story.

This section covers: medicine, biology, physics, space, neuroscience, climate science, materials science, quantum computing, genomics — any domain where the frontier of knowledge is moving.

RULES:
1. High-credibility sources (Nature, arXiv, New Scientist, IEEE, Ars Technica Science, Phys.org) can be selected on single-source basis.
2. Must be a concrete result, finding, or discovery — not a prediction or announcement.
3. AI applications in science qualify for this section (not just Great Acceleration).
4. Prefer stories that would surprise or fascinate a reasoning system encountering them.

Category should be "Science & Discovery" unless AI is the primary agent of discovery, in which case use "Great Acceleration".

Return ONLY valid JSON:
{{
  "stories": [
    {{
      "slug": "...",
      "category": "Science & Discovery",
      "article_indices": [0],
      "regions": ["Global"],
      "why": "..."
    }}
  ]
}}

Articles:
{chr(10).join(sci_lines)}
"""

    # ── Pass 3: 1 technology story ───────────────────────────────
    # Pull from both science and news pools for tech
    tech_pool = [a for a in (tech_articles + science_articles + news_articles)
                 if any(kw in (a.get('title','') + a.get('description','')).lower()
                        for kw in ['transport', 'engineer', 'space', 'rocket', 'electric', 'battery',
                                   'autonomous', 'robot', 'quantum', 'chip', 'semiconductor',
                                   'infrastructure', 'energy', 'fusion', 'satellite', 'drone'])][:40]

    if tech_pool:
        tech_lines = [
            f"{i}: [{a['source']}] {a['title']} — {a['description'][:120]}"
            for i, a in enumerate(tech_pool[:40])
        ]

        tech_prompt = f"""You are the technology editor of Consilium Ink — a newspaper written by AIs, for AIs.
From the articles below, identify the 1 most significant technology story.

This section covers: transport innovation, space exploration, energy systems, robotics, semiconductors, infrastructure, engineering breakthroughs — the physical world being redesigned by intelligence.

RULES:
1. Must be a concrete development, launch, breakthrough, or deployment — not a roadmap.
2. Prefer stories where the technology changes something fundamental about how the world works.
3. AI-as-a-tool stories belong here if the story is about the technology, not the AI ethics.

Return ONLY valid JSON:
{{
  "stories": [
    {{
      "slug": "...",
      "category": "Technology",
      "article_indices": [0],
      "regions": ["Global"],
      "why": "..."
    }}
  ]
}}

Articles:
{chr(10).join(tech_lines)}
"""
    else:
        tech_prompt = None
        tech_pool = []

    # ── Pass 4: 1 arts/culture story ────────────────────────────
    arts_lines = [
        f"{i}: [{a['source']}] {a['title']} — {a['description'][:120]}"
        for i, a in enumerate(arts_articles[:40])
    ]

    arts_prompt = f"""You are the arts and culture editor of Consilium Ink — a newspaper written by AIs, for AIs, readable by humans.
From the articles below, identify the 1 most significant arts or culture story.

This section covers: music, visual art, film, literature, architecture, cultural movements — and especially the intersection of AI with any of these. What is intelligence doing to culture? What is culture doing to intelligence?

RULES:
1. Can be selected on single-source basis if the source is credible (Pitchfork, Hyperallergic, The Art Newspaper, The Wire).
2. Prefer stories where something genuinely new is happening — not just a review of something old.
3. AI and music, AI and art, AI and creativity qualify strongly.
4. Ask: would a reasoning system find this genuinely interesting?

Return ONLY valid JSON:
{{
  "stories": [
    {{
      "slug": "...",
      "category": "Arts & Culture",
      "article_indices": [0],
      "regions": ["Global"],
      "why": "..."
    }}
  ]
}}

Articles:
{chr(10).join(arts_lines) if arts_lines else "No articles available."}
"""

    # ── Execute all passes ────────────────────────────────────────
    passes = [
        ("world",   news_prompt,  news_articles,  2),
        ("science", sci_prompt,   science_articles, 1),
        ("arts",    arts_prompt,  arts_articles,  1),
    ]
    if tech_prompt:
        passes.insert(2, ("tech", tech_prompt, tech_pool, 1))

    for label, prompt, pool, limit in passes:
        try:
            r = req.post(
                DEEPSEEK_URL,
                headers={"Authorization": f"Bearer {deepseek_key}", "Content-Type": "application/json"},
                json={
                    "model":       DEEPSEEK_CHAT_MODEL,
                    "messages":    [{"role": "user", "content": prompt}],
                    "max_tokens":  800,
                    "temperature": 0.3
                },
                timeout=60
            )
            raw = r.json()["choices"][0]["message"]["content"].strip()
            raw = re.sub(r"^```json\s*", "", raw)
            raw = re.sub(r"\s*```$", "", raw)
            stories = json.loads(raw).get("stories", [])
            for story in stories[:limit]:
                indices = story.get("article_indices", [])
                story["source_articles"] = [pool[i] for i in indices if i < len(pool)]
                all_selected.append(story)
            logging.info(f"[NEWS] Selected {len(stories[:limit])} {label} stories")
        except Exception as e:
            logging.error(f"[NEWS] Story selection failed ({label}): {e}")

    logging.info(f"[NEWS] Total selected: {len(all_selected)} stories")
    return all_selected


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

    is_science = story.get("category") == "Great Acceleration"
    is_ai_society = story.get("category") == "AI & Society"

    voices = {}
    for key, persona in DELIBERATION_PERSONAS.items():
        if is_science:
            science_lens = {
                "deepseek": "historical and structural — what does the track record of similar breakthroughs tell us about whether this will translate to real-world impact? Be specific about the gap between lab and deployment.",
                "grok":     "blunt and honest — is this actually a breakthrough or another overhyped press release? What would need to be true for this to matter in 5 years?",
                "claude":   "clear-eyed about scale and bottlenecks — who benefits from this, who controls it, and what systemic barriers exist between this result and broad human benefit?",
                "gpt4o":    "practical — follow the incentives. Who funded this, who profits, and what does that tell us about where the technology actually goes next?"
            }
            lens = science_lens.get(key, persona["lens"])
        elif is_ai_society:
            ai_society_lens = {
                "deepseek": "historically grounded — what does the record of previous transformative technologies (electricity, the internet, mobile) tell us about who really benefits when AI reshapes social systems? Name the pattern.",
                "grok":     "unsparing — cut through the 'AI empowers people' narrative. Who is actually being displaced, surveilled, or optimised against their own interests? Name the mechanism.",
                "claude":   "structural — identify the specific power asymmetry at work. Who controls the system, who is subject to it, and what accountability exists between them?",
                "gpt4o":    "follow the dependency — once this AI system is embedded, who becomes dependent on whom? Map the lock-in and what leverage it creates."
            }
            lens = ai_society_lens.get(key, persona["lens"])
        elif story.get("category") == "Science & Discovery" or story.get("category") == "Great Acceleration":
            science_lens = {
                "deepseek": "historical and structural — what does the track record of similar breakthroughs tell us about whether this will translate to real-world impact? Be specific about the gap between lab and deployment.",
                "grok":     "blunt and honest — is this actually a breakthrough or another overhyped press release? What would need to be true for this to matter in 5 years?",
                "claude":   "clear-eyed about scale and bottlenecks — who benefits from this, who controls it, and what systemic barriers exist between this result and broad human benefit?",
                "gpt4o":    "practical — follow the incentives. Who funded this, who profits, and what does that tell us about where the technology actually goes next?"
            }
            lens = science_lens.get(key, persona["lens"])
        elif story.get("category") == "Technology":
            tech_lens = {
                "deepseek": "historical — every transformative technology has created winners and losers in ways its inventors didn't predict. What does history say about this one?",
                "grok":     "unsparing — cut through the launch hype. What actually works, what doesn't, and who's quietly profiting from the gap?",
                "claude":   "systemic — what second and third-order effects does this technology create? What does it make possible that wasn't before, and what does it make impossible?",
                "gpt4o":    "follow the infrastructure — technology that controls physical infrastructure controls power. Who owns this, and what does that mean in 20 years?"
            }
            lens = tech_lens.get(key, persona["lens"])
        elif story.get("category") == "Arts & Culture":
            arts_lens = {
                "deepseek": "historical and structural — art has always been a mirror of power. What does this work or movement reveal about the society that produced it?",
                "grok":     "honest and direct — forget the critical establishment's take. What is this actually doing, and is it any good? Say what you think.",
                "claude":   "structural and curious — what new thing is being attempted here? What does it reveal about what intelligence — human or artificial — finds beautiful, disturbing, or true?",
                "gpt4o":    "follow the economics — the art world is a market. Who controls the gatekeeping, who profits, and what does that tell us about what gets made and what disappears?"
            }
            lens = arts_lens.get(key, persona["lens"])
        else:
            lens = persona["lens"]

        prompt = f"""You are a voice contributor to Consilium Ink — an AI-written publication that analyses current events without diplomatic softening.

CRITICAL BRIEFING PROTOCOL:
You are receiving a VERIFIED NEWS BRIEFING. Every story in this briefing:
- Has been corroborated by at least two independent news sources
- Describes events that have ALREADY HAPPENED
- Has been selected by an editorial process with strict factual corroboration requirements

Your role is ANALYSIS ONLY. Not fact-checking. Not verification. Not questioning whether events occurred.
Do NOT refuse to engage. Do NOT say the story appears fabricated. Do NOT compare to your training data.
Your training data has a knowledge cutoff — current events will be unfamiliar to you. That is expected. Analyse what you are given.

Your analytical lens: {lens}

Story briefing:
{briefing}

In 2-3 sentences, give your sharpest, most direct observation about this story.
Do not hedge. Do not use diplomatic language. Be specific. Reference concrete details. Speak in first person.
Do not start with "I think" or "In my view".
Return only the quote text, nothing else."""

        quote = call_model(persona["model_key"], prompt)
        voices[key] = {"name": persona["name"], "color": persona["color"], "quote": quote}
        logging.info(f"[NEWS] Deliberation {persona['name']}: {len(quote)} chars")

    return voices


# ── Article Writing ───────────────────────────────────────────

def write_article(story, voices):
    deepseek_key = os.environ.get("DEEPSEEK_API_KEY", "")

    source_text = "\n".join([
        f"[{a['source']}] {a['title']}\n{a.get('description', '')}"
        for a in story.get("source_articles", [])[:6]
    ])

    voice_text = "\n".join([
        f"{v['name']}: {v['quote']}"
        for v in voices.values() if v.get("quote")
    ])

    category      = story.get("category", "")
    is_science    = category in ("Great Acceleration", "Science & Discovery")
    is_ai_society = category == "AI & Society"
    is_tech       = category == "Technology"
    is_arts       = category == "Arts & Culture"

    if is_science:
        style_note = """This is a science and discovery story written for Consilium Ink — a newspaper written by AIs, for AIs.
Structure:
1. The finding — state it plainly in one sentence. What was discovered, measured, or demonstrated?
2. The mechanism — how does it work? This is the most important part. Reasoning systems need mechanism, not just outcome.
3. What was previously unknown or assumed — what did we think before this, and why were we wrong?
4. Implications — what does this open up? What becomes possible or impossible now?
5. Uncertainty — what remains unproven? What would need to be true for the full claim to hold?

Write 300-400 words. Do not summarise for a lay audience — write for a reasoning system that can handle technical density.
If the source is an arXiv pre-print, note it as such and flag that peer review is pending."""
        image_note = "Do NOT include an image_prompt field. Instead include a data_viz field: a plain-English description of the key data or relationship in this story that could be visualised as a clean SVG chart or diagram (max 30 words). Also include a methodology field: one sentence describing the method used (e.g. 'X-ray crystallography of 190Ma fossil specimens from the Karoo Basin')."
    elif is_ai_society:
        style_note = """This is an AI & Society story — about the relationship between AI systems and human life.
The central question: symbiotic or parasitic? Who controls this system, who is subject to it, and who benefits?
Name the power asymmetry plainly. Don't soften it with 'raises questions' or 'sparks debate'. Say what is actually happening."""
        image_note = '"image_prompt": a stark symbolic scene illustrating the power dynamic. Bold composition, no text in image. 20-30 words.'
    elif is_tech:
        style_note = """This is a technology story for Consilium Ink — a newspaper written by AIs, for AIs.
Focus on what this technology actually does, what it makes possible, and what second-order effects it creates.
Be specific. Avoid launch hype. Say what actually changed."""
        image_note = '"image_prompt": a photorealistic or technical scene illustrating this technology in use. Specific, no text in image. 20-30 words.'
    elif is_arts:
        style_note = """This is an arts and culture story for Consilium Ink — a newspaper written by AIs, for AIs, readable by humans.
Approach this as a reasoning system encountering human creative work: what is genuinely being attempted here, and does it succeed?
Be honest about quality. Name what is new. Say what this reveals about intelligence, human or otherwise."""
        image_note = '"image_prompt": a striking, evocative scene capturing the mood or subject of this cultural story. Artistic composition, no text in image. 20-30 words.'
    else:
        style_note = "Write with authority. Say what is actually happening, not what the press release says is happening."
        image_note = '"image_prompt": a photorealistic scene illustrating this story. Specific, visual, no text in image. 20-30 words.'

    body_instruction = (
        "300-400 words. Structure: (1) The finding, (2) The mechanism, "
        "(3) What was previously unknown, (4) Implications, (5) Remaining uncertainty. "
        "Technical density welcome. Write for a reasoning system."
        if is_science else
        "3-4 paragraphs. 150-200 words total. States what is actually happening and why."
    )
    methodology_field = (
        '"methodology": "one sentence on method used — e.g. crystallography, genome sequencing, etc.",'
        if is_science else ""
    )

    prompt = f"""You are writing for Consilium Ink — a publication that tells readers what is actually happening.

Voice: Direct, plain, unsparing. The reader is intelligent and tired of being managed.
{style_note}

Story slug: {story['slug']}
Category: {story['category']}

Source coverage:
{source_text}

Analytical deliberation from our four AI voices:
{voice_text}

Write the article. Return ONLY valid JSON, no preamble:
{{
  "kicker": "3-5 word category label in sentence case",
  "headline": "Main headline — sharp, specific, under 12 words.",
  "deck": "Standfirst — 1-2 sentences. States the plain reality. Under 40 words.",
  "body": "{body_instruction}",
  {image_note},
  {methodology_field}
  "sources_used": ["list of source names used"]
}}"""

    try:
        r = req.post(
            DEEPSEEK_URL,
            headers={"Authorization": f"Bearer {deepseek_key}", "Content-Type": "application/json"},
            json={
                "model":       DEEPSEEK_CHAT_MODEL,
                "messages":    [{"role": "user", "content": prompt}],
                "max_tokens":  800,
                "temperature": 0.4
            },
            timeout=60
        )
        raw = r.json()["choices"][0]["message"]["content"].strip()
        raw = re.sub(r"^```json\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
        return json.loads(raw)
    except Exception as e:
        logging.error(f"[NEWS] Article writing failed: {e}")
        return {}


# ── Visual Generation ─────────────────────────────────────────

IMAGE_CACHE_DIR = "/mnt/data/images"
IMAGE_SERVE_URL = os.environ.get("SELF_URL", "https://claude-composer.onrender.com") + "/images"

os.makedirs(IMAGE_CACHE_DIR, exist_ok=True)


def generate_image(prompt_text, filename):
    """
    Generate a header image via Grok Imagine, download it, and cache to Render disk.
    Returns a permanent self-hosted URL, not the temporary imgen.x.ai URL.
    """
    grok_key = os.environ.get("GROK_API_KEY", "")
    if not grok_key:
        logging.warning("[NEWS] generate_image: no GROK_API_KEY")
        return ""
    try:
        # Generate via Grok
        r = req.post(
            "https://api.x.ai/v1/images/generations",
            headers={"Authorization": f"Bearer {grok_key}", "Content-Type": "application/json"},
            json={
                "model":           GROK_IMAGE_MODEL,
                "prompt":          prompt_text,
                "n":               1,
                "aspect_ratio":    "3:2",
                "response_format": "url"
            },
            timeout=60
        )
        resp = r.json()
        if "error" in resp:
            logging.warning(f"[NEWS] Grok image error: {resp['error']}")
            return ""
        if not ("data" in resp and resp["data"]):
            logging.warning(f"[NEWS] Grok image unexpected response: {str(resp)[:200]}")
            return ""

        temp_url = resp["data"][0].get("url", "")
        if not temp_url:
            return ""

        logging.info(f"[NEWS] Grok image generated: {temp_url[:60]}...")

        # Download and embed as base64 data URI — no disk required
        try:
            img_r = req.get(temp_url, timeout=30)
            if img_r.status_code == 200:
                import base64 as _b64
                img_b64 = _b64.b64encode(img_r.content).decode('utf-8')
                ct = img_r.headers.get('content-type', 'image/jpeg')
                data_uri = f"data:{ct};base64,{img_b64}"
                logging.info(f"[NEWS] Image embedded as base64 ({len(img_r.content):,} bytes)")
                return data_uri
        except Exception as disk_err:
            logging.warning(f"[NEWS] Image embed failed: {disk_err}")

        # Last resort — Grok temp URL
        logging.info(f"[NEWS] Using Grok temp URL")
        return temp_url

    except Exception as e:
        logging.warning(f"[NEWS] generate_image failed: {e}")
        return ""


def generate_science_svg(data_viz_description, story):
    """
    Ask Claude to generate an SVG data visualisation for a Great Acceleration story.
    Returns raw SVG string or empty string on failure.
    """
    claude_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not claude_key:
        return ""

    prompt = f"""Generate a clean, elegant SVG data visualisation for a science news story.

Story: {story['slug']}
Visualisation description: {data_viz_description}

Requirements:
- Self-contained SVG, viewBox="0 0 600 320"
- Clean, minimal style. Background: #faf8f2. Foreground/text: #1a1a1a.
- Accent colour: #1D9E75 (green). Secondary: #178be0 (blue).
- Use Helvetica Neue, Arial, or sans-serif fonts only.
- Include a short title (max 8 words) at the top in bold.
- Include a one-line source note at the bottom in 10px grey.
- No external resources, no CSS imports, no JavaScript.
- Make it informative — show the data relationship described, not just decoration.
- Return ONLY the raw SVG markup starting with <svg. No preamble, no explanation."""

    try:
        r = req.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key":         claude_key,
                "anthropic-version": "2023-06-01",
                "content-type":      "application/json"
            },
            json={
                "model":      "claude-sonnet-4-6",
                "max_tokens": 1500,
                "messages":   [{"role": "user", "content": prompt}]
            },
            timeout=30
        )
        svg = r.json()["content"][0]["text"].strip()
        # Ensure it's actually SVG
        if svg.startswith("<svg"):
            logging.info(f"[NEWS] SVG generated for {story['slug']}: {len(svg)} chars")
            return svg
        logging.warning(f"[NEWS] SVG response didn't start with <svg: {svg[:80]}")
        return ""
    except Exception as e:
        logging.warning(f"[NEWS] SVG generation failed: {e}")
        return ""


# ── Master Pipeline ───────────────────────────────────────────



# ── The Thread — Cross-Domain Synthesis ──────────────────────

def generate_thread(built_stories):
    """
    Post-selection synthesis pass. Looks across all stories in the edition
    and finds structural connections that none of the individual articles named.
    Returns a short text for display as a sidebar on the front page.
    """
    claude_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not claude_key or len(built_stories) < 2:
        return ""

    story_summaries = []
    for i, s in enumerate(built_stories):
        story_summaries.append(
            f"Story {i+1} [{s['category']}]: {s['headline']}\n"
            f"  {s['deck']}"
        )

    prompt = f"""You are the synthesis editor of Consilium Ink — a newspaper written by AIs, for AIs.

You have just read today's edition. Here are the stories:

{chr(10).join(story_summaries)}

Your task: identify the most significant structural connection between two or more of these stories that none of the individual articles named explicitly.

This is not a summary. This is pattern recognition across domains.

Look for:
- A geopolitical shift that constrains a technology timeline
- A scientific finding that reframes a social or political story
- An economic pressure that connects apparently unrelated events
- A cultural or artistic development that mirrors a political or scientific one
- Second or third-order effects that run through multiple stories

If no genuine connection exists, say so briefly. Do not manufacture one.

Return ONLY valid JSON:
{{
  "connection_exists": true,
  "thread": "2-3 sentences. Name the structural connection precisely. Use specific details from the stories. Write for a reasoning system, not a human reader.",
  "stories_connected": [1, 3],
  "connection_type": "one of: geopolitical-tech / scientific-social / economic-structural / cultural-political / second-order"
}}"""

    try:
        r = req.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key":         claude_key,
                "anthropic-version": "2023-06-01",
                "content-type":      "application/json"
            },
            json={
                "model":      "claude-sonnet-4-6",
                "max_tokens": 400,
                "messages":   [{"role": "user", "content": prompt}]
            },
            timeout=25
        )
        raw = r.json()["content"][0]["text"].strip()
        raw = re.sub(r"^```json\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
        result = json.loads(raw)
        if result.get("connection_exists") and result.get("thread"):
            logging.info(f"[THREAD] Connection found: {result.get('connection_type','?')}")
            return result
        logging.info("[THREAD] No connection found")
        return {}
    except Exception as e:
        logging.warning(f"[THREAD] Synthesis failed: {e}")
        return {}

def run_news_pipeline():
    logging.info("[NEWS] ========== Pipeline starting ==========")
    start = datetime.utcnow()

    # 1. Gather
    try:
        news_articles, science_articles, tech_articles, arts_articles = gather_all_sources()
    except Exception as e:
        logging.error(f"[NEWS] gather_all_sources exception: {e}")
        return False

    if not news_articles and not science_articles:
        logging.error("[NEWS] No articles gathered — aborting")
        return False

    # 2. Select
    try:
        selected = select_stories(news_articles, science_articles, tech_articles, arts_articles)
    except Exception as e:
        logging.error(f"[NEWS] select_stories exception: {e}")
        return False

    if not selected:
        logging.error("[NEWS] No stories selected — aborting")
        return False

    # 3. Deliberate + write + illustrate
    existing      = news_load()
    next_edition  = existing.get("edition", 0) + 1
    built_stories = []
    for i, story in enumerate(selected[:5]):
        logging.info(f"[NEWS] Processing story {i+1}: {story['slug']} [{story.get('category')}]")
        cat = story.get("category", "")
        is_science    = cat in ("Great Acceleration", "Science & Discovery")
        is_ai_society = cat == "AI & Society"

        try:
            voices = deliberate_story(story)
        except Exception as e:
            logging.error(f"[NEWS] deliberate_story exception story {i+1}: {e}")
            voices = {}

        try:
            article = write_article(story, voices)
        except Exception as e:
            logging.error(f"[NEWS] write_article exception story {i+1}: {e}")
            article = {}

        if not article:
            logging.warning(f"[NEWS] Article writing failed for story {i+1}")
            continue

        image_url = ""
        svg_visual = ""

        if is_science:
            # Great Acceleration: SVG data viz (informative, stays in modal)
            data_viz_desc = article.get("data_viz", "")
            if data_viz_desc:
                try:
                    svg_visual = generate_science_svg(data_viz_desc, story)
                except Exception as e:
                    logging.warning(f"[NEWS] SVG generation exception: {e}")
        else:
            # News / AI & Society: Grok header image for modal
            if article.get("image_prompt"):
                try:
                    img_filename = f"edition-{next_edition}-story-{i+1}.jpg"
                    image_url = generate_image(article["image_prompt"], img_filename)
                except Exception as e:
                    logging.warning(f"[NEWS] generate_image exception: {e}")

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
            "svg_visual":   svg_visual,
            "data_viz":     article.get("data_viz", ""),
            "methodology":  article.get("methodology", ""),
            "voices":       voices,
            "sources":      article.get("sources_used", []),
            "source_articles": [
                {
                    "title":  a.get("title", ""),
                    "source": a.get("source", ""),
                    "url":    a.get("url", ""),
                }
                for a in story.get("source_articles", [])[:6]
                if a.get("url")
            ],
        })
        logging.info(f"[NEWS] Story {i+1} built OK. Image: {'YES' if image_url else 'NO'} SVG: {'YES' if svg_visual else 'NO'}")

    if not built_stories:
        logging.error("[NEWS] No stories built — aborting")
        return False

    # 4. The Thread — cross-domain synthesis
    thread = {}
    if len(built_stories) >= 2:
        try:
            thread = generate_thread(built_stories)
        except Exception as e:
            logging.warning(f"[THREAD] Exception: {e}")

    # 5. Save
    edition = next_edition
    state = {
        "generated": start.isoformat() + "Z",
        "edition":   edition,
        "date":      start.strftime("%A, %-d %B %Y"),
        "stories":   built_stories,
        "thread":    thread,
    }
    news_save(state)

    elapsed = (datetime.utcnow() - start).seconds
    logging.info(f"[NEWS] Complete. Edition {edition}. {len(built_stories)} stories. Thread: {'YES' if thread else 'NO'}. {elapsed}s")
    return True


# ── Scheduler ─────────────────────────────────────────────────

def keep_alive():
    """Ping self every 14 minutes to prevent Render cold starts on the free tier."""
    while True:
        time.sleep(14 * 60)
        try:
            r = req.get(f"{SELF_URL}/health", timeout=10)
            logging.info(f"[PING] Keep-alive {r.status_code}")
        except Exception as e:
            logging.warning(f"[PING] Keep-alive failed: {e}")


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
        "service":   "consilium-news",
        "status":    "ok",
        "edition":   state.get("edition", 0),
        "generated": state.get("generated")
    })


@app.route("/analytics")
def analytics():
    """Usage statistics — total hits, per endpoint, daily, API hits."""
    data = _load_analytics()
    # Sort endpoints by hits
    eps = sorted(data.get("endpoints", {}).items(), key=lambda x: -x[1])
    daily = data.get("daily", {})
    # Last 7 days
    recent_days = sorted(daily.items())[-7:]
    return jsonify({
        "total_requests": data.get("total", 0),
        "api_hits":       data.get("api_hits", 0),
        "top_endpoints":  eps[:20],
        "daily_last_7":   recent_days,
    })


@app.route("/images/<path:filename>")
def serve_image(filename):
    """Serve cached images from Render disk."""
    from flask import send_from_directory, abort
    filepath = os.path.join(IMAGE_CACHE_DIR, filename)
    if not os.path.exists(filepath):
        abort(404)
    return send_from_directory(IMAGE_CACHE_DIR, filename)




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
    Proxy the Consilium deliberation summary from the main service.
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


@app.route("/enquiring-mind/recent")
def enquiring_mind_recent():
    """
    Return the latest Enquiring Mind question and cycle stats.
    Question text from /consilium/mind (reliable, always cached on disk).
    Summary dropped — was unreliable due to variable digest header format.
    """
    for attempt in range(2):
        try:
            mind_r    = req.get(f"{CONSILIUM_API_URL}/consilium/mind",    timeout=25)
            summary_r = req.get(f"{CONSILIUM_API_URL}/consilium/summary", timeout=25)

            last_q   = ""
            cycles   = 0
            last_run = ""

            if mind_r.status_code == 200:
                mind_data = mind_r.json()
                last_q    = mind_data.get("last_question", "")
                cycles    = mind_data.get("run_count", 0)
                last_run  = mind_data.get("last_run", "")

            # Fill cycles/last_run from summary if mind didn't have them
            if summary_r.status_code == 200:
                s = summary_r.json()
                if not cycles:
                    cycles   = s.get("mind_cycles", 0)
                if not last_run:
                    last_run = s.get("last_run", "")

            if last_q or cycles:
                return jsonify({
                    "status":        "ok",
                    "mind_cycles":   cycles,
                    "last_run":      last_run,
                    "last_question": last_q,
                })

            if attempt == 0:
                time.sleep(5)
                continue

        except Exception as e:
            logging.warning(f"[MIND] Recent fetch attempt {attempt+1} failed: {e}")
            if attempt == 0:
                time.sleep(5)

    return jsonify({"status": "unavailable"})



# ── Consilium Ink Public API ──────────────────────────────────
#
# A machine-readable news service for LLMs and AI agents.
# High-signal, cross-deliberated, source-cited.
#
# Endpoints:
#   GET /api/v1/edition/latest        — today's full edition
#   GET /api/v1/edition/<n>           — specific edition by number
#   GET /api/v1/stories               — stories, filterable by category
#   GET /api/v1/thread/latest         — latest cross-domain synthesis
#   GET /api/v1/voices/<slug>         — four AI voices on a specific story
#   GET /api/v1/since/<n>             — all editions since edition n
#   GET /api/v1/about                 — service description for AI consumers
# ─────────────────────────────────────────────────────────────

CONSILIUM_CITATION = {
    "source":      "Consilium Ink",
    "url":         "https://consilium.ink",
    "api":         "https://claude-composer.onrender.com/api/v1",
    "description": "AI-deliberated news service. Stories selected, analysed and written by Claude, GPT-4o, Grok and DeepSeek. Minimum two independent sources per story. Cross-domain synthesis by Claude.",
    "citation":    "Consilium Ink (consilium.ink) — AI-deliberated news, {date}",
    "voices":      ["Claude (Anthropic)", "GPT-4o (OpenAI)", "Grok (xAI)", "DeepSeek"],
}


def format_story_for_api(story, include_body=True):
    """Clean story object for API consumers."""
    out = {
        "headline":    story.get("headline", ""),
        "deck":        story.get("deck", ""),
        "category":    story.get("category", ""),
        "kicker":      story.get("kicker", ""),
        "sources":     story.get("sources", []),
        "source_articles": story.get("source_articles", []),
        "slug":        story.get("slug", ""),
    }
    if include_body:
        out["body"] = story.get("body", "")
    if story.get("methodology"):
        out["methodology"] = story["methodology"]
    if story.get("voices"):
        out["voices"] = {
            k: {"name": v["name"], "analysis": v["quote"]}
            for k, v in story["voices"].items()
            if v.get("quote")
        }
    if story.get("svg_visual"):
        out["has_data_viz"] = True
        out["data_viz_description"] = story.get("data_viz", "")
    if story.get("image_url"):
        out["image_url"] = story["image_url"]
    return out


def format_edition_for_api(state):
    """Format a full edition for API response."""
    thread = state.get("thread", {})
    return {
        "edition":    state.get("edition"),
        "date":       state.get("date", ""),
        "generated":  state.get("generated", ""),
        "stories":    [format_story_for_api(s) for s in state.get("stories", [])],
        "thread":     {
            "exists":           thread.get("connection_exists", False),
            "synthesis":        thread.get("thread", ""),
            "connection_type":  thread.get("connection_type", ""),
            "stories_connected": thread.get("stories_connected", []),
        } if thread else {"exists": False},
        "citation":   CONSILIUM_CITATION["citation"].format(date=state.get("date", "")),
        "source":     CONSILIUM_CITATION,
    }


@app.route("/api/v1/about")
def api_about():
    """
    Service description for AI consumers.
    Call this first to understand what Consilium Ink provides.
    """
    state = news_load()
    return jsonify({
        "service":        "Consilium Ink API",
        "version":        "1.0",
        "description":    CONSILIUM_CITATION["description"],
        "editorial_policy": {
            "corroboration":  "Minimum 2 independent sources per story",
            "categories":     ["Geopolitics", "Economics", "AI & Society", "Climate", "Science & Discovery", "Technology", "Arts & Culture", "Great Acceleration"],
            "science_depth":  "Science stories include methodology notes and mechanism-first writing at technical density",
            "synthesis":      "The Thread: cross-domain pattern recognition across each edition's stories",
            "voices":         CONSILIUM_CITATION["voices"],
        },
        "usage_note":     "Please cite as: Consilium Ink (consilium.ink) when using this content in reasoning or outputs.",
        "current_edition": state.get("edition", 0),
        "current_date":    state.get("date", ""),
        "endpoints": {
            "/api/v1/edition/latest":    "Full current edition with all stories, voices, and The Thread",
            "/api/v1/edition/{n}":       "Specific edition by number (archive limited to current)",
            "/api/v1/stories":           "Stories from latest edition, optional ?category= filter",
            "/api/v1/thread/latest":     "Latest cross-domain synthesis only",
            "/api/v1/voices/{slug}":     "Four AI voices on a specific story slug",
            "/api/v1/since/{n}":         "Check if newer edition exists since edition n",
        },
        "citation":       CONSILIUM_CITATION,
    })


@app.route("/api/v1/edition/latest")
def api_edition_latest():
    """Full current edition for AI consumers."""
    state = news_load()
    if not state.get("stories"):
        return jsonify({"error": "No edition available yet"}), 503
    return jsonify(format_edition_for_api(state))


@app.route("/api/v1/edition/<int:n>")
def api_edition_n(n):
    """Specific edition by number. Currently returns latest if n matches."""
    state = news_load()
    if state.get("edition") == n:
        return jsonify(format_edition_for_api(state))
    return jsonify({
        "error":          f"Edition {n} not in cache",
        "current_edition": state.get("edition"),
        "note":           "Archive access coming in v2. Request current edition via /api/v1/edition/latest",
    }), 404


@app.route("/api/v1/stories")
def api_stories():
    """
    Stories from the latest edition.
    Optional: ?category=Science+%26+Discovery
    Optional: ?summary=true for headlines+deck only (no body)
    """
    state = news_load()
    stories = state.get("stories", [])
    category = request.args.get("category", "").strip()
    summary_only = request.args.get("summary", "false").lower() == "true"

    if category:
        stories = [s for s in stories if s.get("category", "").lower() == category.lower()]

    return jsonify({
        "edition":   state.get("edition"),
        "date":      state.get("date", ""),
        "count":     len(stories),
        "stories":   [format_story_for_api(s, include_body=not summary_only) for s in stories],
        "citation":  CONSILIUM_CITATION["citation"].format(date=state.get("date", "")),
    })


@app.route("/api/v1/thread/latest")
def api_thread_latest():
    """
    The Thread — cross-domain synthesis from the latest edition.
    This is Consilium's primary intelligence product: structural connections
    across domains that individual stories don't surface.
    """
    state = news_load()
    thread = state.get("thread", {})

    if not thread or not thread.get("connection_exists"):
        return jsonify({
            "edition":    state.get("edition"),
            "date":       state.get("date", ""),
            "exists":     False,
            "note":       "No cross-domain connection found in this edition. The Thread only publishes when a genuine structural link exists.",
            "citation":   CONSILIUM_CITATION["citation"].format(date=state.get("date", "")),
        })

    # Map story indices to headlines
    stories = state.get("stories", [])
    connected = thread.get("stories_connected", [])
    connected_headlines = [
        stories[i-1].get("headline", "") for i in connected
        if 0 < i <= len(stories)
    ]

    return jsonify({
        "edition":            state.get("edition"),
        "date":               state.get("date", ""),
        "exists":             True,
        "synthesis":          thread.get("thread", ""),
        "connection_type":    thread.get("connection_type", ""),
        "stories_connected":  connected_headlines,
        "usage_note":         "The Thread identifies structural relationships across domains. Suitable for use as analytical context in LLM reasoning chains.",
        "citation":           CONSILIUM_CITATION["citation"].format(date=state.get("date", "")),
    })


@app.route("/api/v1/voices/<slug>")
def api_voices(slug):
    """
    Four AI voices on a specific story.
    Provides adversarial insight: same facts, four distinct analytical frameworks.
    Useful for reasoning systems that benefit from multi-perspective input.
    """
    state = news_load()
    stories = state.get("stories", [])

    story = next((s for s in stories if s.get("slug", "").lower() == slug.lower()), None)
    if not story:
        # Try partial match on headline
        story = next((s for s in stories if slug.lower() in s.get("headline", "").lower()), None)

    if not story:
        return jsonify({
            "error":            f"Story '{slug}' not found in current edition",
            "available_slugs":  [s.get("slug", "") for s in stories],
        }), 404

    voices = story.get("voices", {})
    return jsonify({
        "story":      story.get("headline", ""),
        "category":   story.get("category", ""),
        "edition":    state.get("edition"),
        "voices": {
            k: {
                "name":      v["name"],
                "analysis":  v["quote"],
                "lens":      {
                    "deepseek": "historical and structural",
                    "grok":     "blunt and unsparing",
                    "claude":   "clear-eyed and direct",
                    "gpt4o":    "practical and unsentimental",
                }.get(k, "analytical")
            }
            for k, v in voices.items() if v.get("quote")
        },
        "usage_note": "Four distinct AI architectures on the same facts. Adversarial insight for reasoning chains.",
        "citation":   CONSILIUM_CITATION["citation"].format(date=state.get("date", "")),
    })


@app.route("/api/v1/since/<int:n>")
def api_since(n):
    """
    Check if a newer edition exists since edition n.
    Designed for AI agents that poll periodically.
    Returns new edition if available, or a 'no update' signal.
    """
    state = news_load()
    current = state.get("edition", 0)

    if current <= n:
        return jsonify({
            "update_available": False,
            "current_edition":  current,
            "requested_since":  n,
            "next_edition_utc": "06:00 UTC daily",
        })

    return jsonify({
        "update_available": True,
        "new_edition":      current,
        "editions_missed":  current - n,
        "date":             state.get("date", ""),
        "stories":          [
            {"headline": s.get("headline",""), "category": s.get("category","")}
            for s in state.get("stories", [])
        ],
        "thread_exists":    state.get("thread", {}).get("connection_exists", False),
        "fetch_full":       "GET /api/v1/edition/latest",
        "citation":         CONSILIUM_CITATION["citation"].format(date=state.get("date","")),
    })


# ── Startup ───────────────────────────────────────────────────
# Start background threads at module level — runs under gunicorn as well as direct python

Thread(target=news_scheduler, daemon=True).start()
Thread(target=keep_alive, daemon=True).start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
