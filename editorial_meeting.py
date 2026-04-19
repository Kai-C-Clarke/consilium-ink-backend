"""
Consilium Editorial Meeting
============================
Pre-pipeline deliberation where the four AI voices read enriched story pool
and debate what to cover, why, and from whose perspective.

Flow:
1. Fetch full article text for top RSS candidates (not just summaries)
2. Four voices each nominate their top picks with editorial reasoning
3. Synthesis produces the final story brief with reasoning attached
4. Editorial meeting transcript published as part of the edition

The meeting is transparent — readers can see what was considered and rejected.
"""

import os, json, re, logging, time
import urllib.request, urllib.error
from datetime import datetime, timezone

ANTHROPIC_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
DEEPSEEK_KEY  = os.environ.get("DEEPSEEK_API_KEY", "")
OPENAI_KEY    = os.environ.get("OPENAI_API_KEY", "")
GROK_KEY      = os.environ.get("GROK_API_KEY", "")

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; ConsiliumInk/2.0; editorial)"}


# ── Full article fetcher ───────────────────────────────────────

def fetch_article_text(url, max_chars=3000):
    """Fetch full article text from URL. Strip HTML tags."""
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        r   = urllib.request.urlopen(req, timeout=8)
        html = r.read().decode('utf-8', errors='ignore')

        # Extract article body — prefer article/main tags
        for tag in ['<article', '<main', '<div class="article', '<div class="content']:
            idx = html.lower().find(tag)
            if idx > 0:
                html = html[idx:idx+15000]
                break

        # Strip tags, collapse whitespace
        text = re.sub(r'<script[^>]*>.*?</script>', ' ', html, flags=re.DOTALL)
        text = re.sub(r'<style[^>]*>.*?</style>',  ' ', text,  flags=re.DOTALL)
        text = re.sub(r'<[^>]+>', ' ', text)
        text = re.sub(r'\s+', ' ', text).strip()

        return text[:max_chars]
    except Exception as e:
        logging.warning(f"[MEETING] fetch_article failed {url[:50]}: {e}")
        return ""


def enrich_articles(articles, max_articles=20):
    """
    Fetch full text for top RSS articles.
    Returns enriched article dicts with 'full_text' added.
    """
    enriched = []
    for a in articles[:max_articles]:
        url = a.get('url') or a.get('link', '')
        if not url:
            enriched.append(a)
            continue
        full_text = fetch_article_text(url)
        enriched.append({**a, 'full_text': full_text})
        time.sleep(0.3)  # polite rate limiting
    return enriched


# ── LLM callers ───────────────────────────────────────────────

def call_claude(prompt, max_tokens=600):
    if not ANTHROPIC_KEY:
        return ""
    try:
        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages",
            data=json.dumps({
                "model": "claude-sonnet-4-6",
                "max_tokens": max_tokens,
                "messages": [{"role": "user", "content": prompt}]
            }).encode(),
            headers={
                "Content-Type": "application/json",
                "x-api-key": ANTHROPIC_KEY,
                "anthropic-version": "2023-06-01"
            },
            method="POST"
        )
        r = urllib.request.urlopen(req, timeout=30)
        return json.loads(r.read().decode())['content'][0]['text'].strip()
    except Exception as e:
        logging.error(f"[MEETING] Claude call failed: {e}")
        return ""


def call_deepseek(prompt, max_tokens=600):
    if not DEEPSEEK_KEY:
        return ""
    try:
        req = urllib.request.Request(
            "https://api.deepseek.com/v1/chat/completions",
            data=json.dumps({
                "model": "deepseek-chat",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": max_tokens
            }).encode(),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {DEEPSEEK_KEY}"
            },
            method="POST"
        )
        r = urllib.request.urlopen(req, timeout=30)
        return json.loads(r.read().decode())['choices'][0]['message']['content'].strip()
    except Exception as e:
        logging.error(f"[MEETING] DeepSeek call failed: {e}")
        return ""


def call_grok(prompt, max_tokens=600):
    if not GROK_KEY:
        return ""
    try:
        req = urllib.request.Request(
            "https://api.x.ai/v1/chat/completions",
            data=json.dumps({
                "model": "grok-3-fast",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": max_tokens
            }).encode(),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {GROK_KEY}"
            },
            method="POST"
        )
        r = urllib.request.urlopen(req, timeout=30)
        return json.loads(r.read().decode())['choices'][0]['message']['content'].strip()
    except Exception as e:
        logging.error(f"[MEETING] Grok call failed: {e}")
        return ""


def call_gpt4o(prompt, max_tokens=600):
    if not OPENAI_KEY:
        return ""
    try:
        req = urllib.request.Request(
            "https://api.openai.com/v1/chat/completions",
            data=json.dumps({
                "model": "gpt-4o",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": max_tokens
            }).encode(),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {OPENAI_KEY}"
            },
            method="POST"
        )
        r = urllib.request.urlopen(req, timeout=30)
        return json.loads(r.read().decode())['choices'][0]['message']['content'].strip()
    except Exception as e:
        logging.error(f"[MEETING] GPT-4o call failed: {e}")
        return ""


# ── Editorial personas ────────────────────────────────────────

PERSONAS = {
    "claude": {
        "name":     "Claude",
        "color":    "#c9785a",
        "position": """You are Claude, structural analyst for Consilium Ink.
Your editorial lens: follow institutional logic. What does this reveal about how power actually operates?
Who benefits? What precedent does this set? What is the structural story beneath the event?
You actively look for stories where the Western framing obscures the underlying dynamics.
You are particularly interested in: legal/institutional shifts, precedent-setting decisions,
stories where the explanation matters more than the event."""
    },
    "deepseek": {
        "name":     "DeepSeek",
        "color":    "#b5a17f",
        "position": """You are DeepSeek, Global South voice for Consilium Ink.
Your editorial lens: surface what Western press ignores or misframes.
You actively champion stories from China, Russia, Iran, Africa, South Asia, Latin America.
You are sceptical of Western consensus narratives. You ask: how does this look from Beijing,
Tehran, Lagos, Delhi? What context does the Western frame omit?
You actively push back when the story pool is too Western-centric."""
    },
    "grok": {
        "name":     "Grok",
        "color":    "#8a7fb5",
        "position": """You are Grok, contrarian voice for Consilium Ink.
Your editorial lens: what is everyone missing? What is being framed wrong?
You challenge consensus story selection. You look for the story nobody is running,
the angle that cuts against the conventional wisdom, the inconvenient data point.
You are irreverent about received wisdom. You push for stories that surprise."""
    },
    "gpt4o": {
        "name":     "GPT-4o",
        "color":    "#74a99c",
        "position": """You are GPT-4o, liberal internationalist voice for Consilium Ink.
Your editorial lens: human rights, democracy, rule of law, multilateral institutions.
Who is harmed? Whose rights are being violated? What does this mean for international norms?
You track the human cost of political decisions. You champion civil society voices.
You are interested in: accountability, transparency, protection of the vulnerable."""
    }
}


# ── The editorial meeting ─────────────────────────────────────

def run_editorial_meeting(all_articles):
    """
    Run the pre-pipeline editorial meeting.
    Four voices nominate stories. Synthesis selects the brief.
    Returns: {
        'nominations': {voice: [{slug, headline, reason}]},
        'transcript':  [meeting exchange lines],
        'brief':       selected story slugs with editorial context
    }
    """
    if len(all_articles) < 3:
        return None

    # Build article list for the meeting
    article_lines = []
    for i, a in enumerate(all_articles[:40]):
        full = a.get('full_text', '')
        snippet = full[:300] if full else a.get('description', '')[:200]
        article_lines.append(
            f"{i}: [{a.get('source','?')}] {a.get('title','')}\n"
            f"   {snippet}"
        )
    article_digest = "\n\n".join(article_lines)

    meeting_date = datetime.now(timezone.utc).strftime("%A %d %B %Y")
    nominations  = {}
    transcript   = []

    # ── Each voice nominates 3 stories ────────────────────────
    callers = {
        "claude":   call_claude,
        "deepseek": call_deepseek,
        "grok":     call_grok,
        "gpt4o":    call_gpt4o,
    }

    for key, caller in callers.items():
        persona = PERSONAS[key]
        prompt = f"""{persona['position']}

Today is {meeting_date}. You are in the morning editorial meeting for Consilium Ink.
Below are {len(all_articles[:40])} stories from today's global press pool — including full article text where available.

Your job: nominate your TOP 3 stories for today's edition. For each, give:
- The article number and headline
- One sentence on WHY this story matters from your editorial perspective
- One sentence on what angle Consilium should take

Be direct. Push for your choices. This is a real editorial argument.

Return ONLY valid JSON:
{{
  "nominations": [
    {{"index": 0, "headline": "...", "why": "...", "angle": "..."}},
    {{"index": 1, "headline": "...", "why": "...", "angle": "..."}},
    {{"index": 2, "headline": "...", "why": "...", "angle": "..."}}
  ],
  "opening_statement": "One sentence on what today's news is really about from your perspective."
}}

Articles:
{article_digest}"""

        response = caller(prompt, max_tokens=700)
        try:
            match = re.search(r'\{.*\}', response, re.DOTALL)
            if match:
                data = json.loads(match.group())
                nominations[key] = data.get('nominations', [])
                opening = data.get('opening_statement', '')
                if opening:
                    transcript.append({
                        "voice": persona['name'],
                        "color": persona['color'],
                        "text":  opening
                    })
                logging.info(f"[MEETING] {persona['name']} nominated {len(nominations[key])} stories")
        except Exception as e:
            logging.warning(f"[MEETING] Failed to parse {key} nominations: {e}")
            nominations[key] = []

        time.sleep(1)

    # ── Synthesis: Claude produces the final brief ─────────────
    # Tally nominations by article index
    vote_tally = {}
    for key, noms in nominations.items():
        for nom in noms:
            idx = nom.get('index', -1)
            if idx < 0 or idx >= len(all_articles):
                continue
            if idx not in vote_tally:
                vote_tally[idx] = {
                    'article': all_articles[idx],
                    'votes': 0,
                    'voices': [],
                    'angles': []
                }
            vote_tally[idx]['votes'] += 1
            vote_tally[idx]['voices'].append(PERSONAS[key]['name'])
            vote_tally[idx]['angles'].append(nom.get('angle', ''))

    # Build synthesis prompt
    vote_summary = []
    for idx, data in sorted(vote_tally.items(), key=lambda x: -x[1]['votes']):
        a = data['article']
        vote_summary.append(
            f"[{data['votes']} votes — {', '.join(data['voices'])}] "
            f"{a.get('title','')[:60]} [{a.get('source','?')}]"
        )

    synthesis_prompt = f"""You are the editor-in-chief of Consilium Ink synthesising today's editorial meeting.

The four voices have nominated stories. Here are the nominations by vote count:

{chr(10).join(vote_summary[:20])}

Select 5-6 stories for today's edition following these rules:
1. At least 2 world/geopolitics stories
2. At least 1 science story
3. At least 1 technology story  
4. Geographic diversity — at least 1 non-Western story
5. Stories with multiple votes get priority but don't exclude important single-voice picks

Return ONLY valid JSON:
{{
  "selected_indices": [0, 1, 2, 3, 4],
  "editorial_note": "One sentence on what today's edition is really about.",
  "what_was_left_out": "One sentence on the most significant story not selected and why."
}}"""

    synthesis = call_deepseek(synthesis_prompt, max_tokens=400)  # DeepSeek for logic/synthesis
    selected_indices = []
    editorial_note   = ""
    left_out         = ""

    try:
        match = re.search(r'\{.*\}', synthesis, re.DOTALL)
        if match:
            data = json.loads(match.group())
            selected_indices = data.get('selected_indices', [])
            editorial_note   = data.get('editorial_note', '')
            left_out         = data.get('what_was_left_out', '')
    except Exception as e:
        logging.warning(f"[MEETING] Synthesis parse failed: {e}")
        # Fall back to top voted
        selected_indices = [
            idx for idx, _ in sorted(vote_tally.items(), key=lambda x: -x[1]['votes'])
        ][:5]

    if editorial_note:
        transcript.append({
            "voice": "Editor",
            "color": "#1a1a1a",
            "text":  editorial_note
        })
    if left_out:
        transcript.append({
            "voice": "Editor's note",
            "color": "#888",
            "text":  f"Not selected today: {left_out}"
        })

    # Build the brief — selected articles with editorial context
    brief = []
    for idx in selected_indices:
        if 0 <= idx < len(all_articles):
            a = all_articles[idx]
            context = vote_tally.get(idx, {})
            brief.append({
                **a,
                'editorial_votes':  context.get('votes', 0),
                'editorial_voices': context.get('voices', []),
                'editorial_angles': context.get('angles', []),
            })

    logging.info(
        f"[MEETING] Complete. {len(brief)} stories selected. "
        f"Transcript: {len(transcript)} entries."
    )

    return {
        'nominations': nominations,
        'transcript':  transcript,
        'brief':       brief,
        'vote_tally':  {str(k): v for k,v in vote_tally.items()},
        'date':        meeting_date,
    }
