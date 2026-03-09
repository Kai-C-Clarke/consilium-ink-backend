"""
The Composer — Flask Backend
Lyria 2 (Vertex AI) edition

Pipeline:
  User prompt
  → Confucius (DeepSeek) → JSON interpretation
  → build_lyria_prompt() → Lyria 2 (Vertex AI) → 48kHz WAV
  → SoX reverb → lame MP3
  → base64 JSON response → HTML5 audio player

Env vars required:
  DEEPSEEK_API_KEY           — DeepSeek API key (Confucius)
  GOOGLE_SERVICE_ACCOUNT_JSON — Full JSON string of GCP service account key
  GOOGLE_CLOUD_PROJECT       — GCP project ID  e.g. "composer-ai-12345"
  GOOGLE_CLOUD_LOCATION      — Vertex AI region  e.g. "us-central1"
"""

import os
import json
import base64
import tempfile
import subprocess
import requests as req

from flask import Flask, request, jsonify
from flask_cors import CORS

import google.auth.transport.requests
from google.oauth2 import service_account


# ──────────────────────────────────────────────────────────
# APP
# ──────────────────────────────────────────────────────────

app = Flask(__name__, static_folder=".", static_url_path="")
CORS(app)


# ──────────────────────────────────────────────────────────
# CONFUCIUS  (DeepSeek)
# ──────────────────────────────────────────────────────────

DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_URL     = "https://api.deepseek.com/v1/chat/completions"

CONFUCIUS_SYSTEM = """You are Confucius, Master of interpretation. A student brings you a feeling or intention.
You must translate it into a musical commission for one of seven classical composers.

Respond ONLY with valid JSON (no markdown, no explanation):
{
  "composer":        "Vivaldi|Bach|Mozart|Beethoven|Chopin|Tchaikovsky|Debussy",
  "key":             "D minor" (or any appropriate key),
  "tempo":           120 (integer BPM),
  "mood":            "one word: energetic|dramatic|melancholic|peaceful|joyful|mysterious|triumphant|romantic|contemplative|playful",
  "programme_note":  "Two sentences. What feeling this music will evoke and why this composer was chosen."
}

Composer selection guide (based on musical energy):
- HIGH energy/tempo  → Vivaldi (sequences, fire), Beethoven (drama, power)
- MEDIUM energy      → Bach (intellect, counterpoint), Mozart (elegance, wit)
- LOW energy/tempo   → Chopin (intimate nocturne), Tchaikovsky (sweeping romance), Debussy (impressionist mist)

Tempo guidance: specify the FELT beat — the pulse a conductor would beat — not the fastest note value played.
A Vivaldi allegro with rapid semiquaver violin figures should be 80-120 BPM, not 160.
A Bach fugue with busy counterpoint should be 60-90 BPM. Reserve 140+ only for genuinely fast dance forms.

Do not select the same composer twice in a row. Vary your choices."""


def call_confucius(user_prompt: str) -> dict:
    payload = {
        "model": "deepseek-chat",
        "temperature": 0.5,
        "max_tokens": 300,
        "messages": [
            {"role": "system", "content": CONFUCIUS_SYSTEM},
            {"role": "user",   "content": user_prompt}
        ]
    }
    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type":  "application/json"
    }
    r = req.post(DEEPSEEK_URL, headers=headers, json=payload, timeout=30)
    r.raise_for_status()
    raw = r.json()["choices"][0]["message"]["content"].strip()

    # Strip markdown fences if present
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]

    return json.loads(raw.strip())


# ──────────────────────────────────────────────────────────
# LYRIA PROMPT BUILDER
# ──────────────────────────────────────────────────────────

LYRIA_STYLE_PROMPTS = {
    "Vivaldi":     (
        "Bright solo violin darting through rapid repeated figures over plucked strings and harpsichord, "
        "crisp and energetic, sudden shifts between loud and soft, sparkling and propulsive, "
        "baroque chamber ensemble, {key}, {tempo} BPM"
    ),
    "Bach":        (
        "Harpsichord with several independent melodic lines weaving around each other in strict order, "
        "a theme introduced then answered, walking bass below, ornamented and precise, "
        "baroque keyboard, {key}, {tempo} BPM"
    ),
    "Mozart":      (
        "Piano with a clear singing melody, light string accompaniment, woodwind echoes, "
        "balanced and elegant phrases, graceful and transparent, classical chamber style, "
        "{key}, {tempo} BPM"
    ),
    "Beethoven":   (
        "Full orchestra with driving strings, sudden dramatic silences followed by powerful brass, "
        "forceful and stormy, heroic and determined, building to overwhelming climaxes, "
        "purely orchestral, no drum kit, {key}, {tempo} BPM"
    ),
    "Chopin":      (
        "Solo piano with a freely breathing singing melody in the right hand, "
        "rich flowing accompaniment in the left hand spreading warmly, "
        "intimate and expressive, romantic and personal, {key}, {tempo} BPM"
    ),
    "Tchaikovsky": (
        "Strings playing a broad sweeping melody that rises with deep feeling, "
        "rich cello counter-melody beneath, warm and yearning, building to an emotional peak "
        "with full orchestra, deeply expressive, {key}, {tempo} BPM"
    ),
    "Debussy":     (
        "Solo piano with a delicate floating melody over soft rippling accompaniment, "
        "harmonies that blur and dissolve without resolving, hazy and shimmering, "
        "like light on water or mist in the morning, gentle and atmospheric, "
        "{key}, {tempo} BPM"
    ),
}

LYRIA_NEGATIVE_PROMPTS = {
    "Vivaldi":     "vocals, singing, piano, drums, drum kit, electronic, synthesizer, electric guitar, pop, modern, brass",
    "Bach":        "vocals, singing, drums, drum kit, electronic, synthesizer, electric guitar, pop, modern, orchestra, brass",
    "Mozart":      "vocals, singing, drums, drum kit, electronic, synthesizer, electric guitar, pop, modern",
    "Beethoven":   "vocals, singing, drums, drum kit, kick drum, electronic, synthesizer, electric guitar, pop, modern, jazz",
    "Chopin":      "vocals, singing, drums, drum kit, electronic, synthesizer, electric guitar, pop, modern, orchestra, violin, trumpet",
    "Tchaikovsky": "vocals, singing, drums, drum kit, electronic, synthesizer, electric guitar, pop, modern, jazz, piano",
    "Debussy":     "vocals, singing, drums, drum kit, electronic, synthesizer, electric guitar, pop, modern, trumpet, trombone, violin, orchestra",
}

MOOD_MAP = {
    "energetic":     "energetic, driving, vital, spirited",
    "dramatic":      "dramatic, intense, powerful, fierce",
    "melancholic":   "melancholic, wistful, tender, sorrowful",
    "peaceful":      "peaceful, serene, calm, tranquil",
    "joyful":        "joyful, bright, celebratory, cheerful",
    "mysterious":    "mysterious, shadowy, intriguing, veiled",
    "triumphant":    "triumphant, heroic, majestic, glorious",
    "romantic":      "romantic, expressive, passionate, yearning",
    "contemplative": "contemplative, reflective, introspective, meditative",
    "playful":       "playful, light, sprightly, witty",
}


# ──────────────────────────────────────────────────────────
# TOMITA PROMPT BUILDER
# ──────────────────────────────────────────────────────────

TOMITA_MOODS = {
    "vast":          "immense, cosmic, boundless, like floating in deep space",
    "delicate":      "fragile, tender, like frost on glass, barely there",
    "mysterious":    "shadowy, unknowable, drifting between worlds",
    "joyful":        "bright, shimmering, dancing particles of light",
    "melancholic":   "wistful, longing, a distant memory slowly dissolving",
    "peaceful":      "serene, suspended, time standing still",
    "dramatic":      "surging, powerful, vast forces in slow motion",
    "contemplative": "introspective, patient, deep listening",
}

TOMITA_SOURCES = {
    "debussy":      "impressionist tone poem translated into analogue electronics, liquid harmonies, blurred edges",
    "holst":        "cosmic orchestral sweep translated into vast synthesizer layers, planetary scale",
    "mussorgsky":   "bold architectural themes translated into rich synthesizer colours, heavy and vivid",
    "ravel":        "glittering orchestral textures translated into shimmering filter sweeps and bell tones",
    "stravinsky":   "rhythmic angular phrases translated into sequencer patterns and oscillator stabs",
    "original":     "original cosmic soundscape, no classical source, pure synthesis",
}

def build_lyria_prompt(c: dict) -> tuple:
    composer = c.get("composer", "Mozart")
    key      = c.get("key", "C major")
    tempo    = c.get("tempo", 120)
    mood     = c.get("mood", "expressive").lower()

    style    = LYRIA_STYLE_PROMPTS.get(composer, LYRIA_STYLE_PROMPTS["Mozart"])
    style    = style.format(key=key, tempo=tempo)
    mood_str = MOOD_MAP.get(mood, mood)

    prompt   = f"{style}, {mood_str}, instrumental"
    negative = LYRIA_NEGATIVE_PROMPTS.get(composer, "vocals, singing, drums, drum kit, electronic, synthesizer, electric guitar, pop, modern")

    return prompt, negative


# ──────────────────────────────────────────────────────────
# TOMITA PROMPT BUILDER
# ──────────────────────────────────────────────────────────

TOMITA_CONFUCIUS_SYSTEM = """You are Isao Tomita's inner voice — the quiet interpreter who listens to a feeling and translates it into a sonic world.

Someone brings you a prompt. You must return a JSON object describing how Tomita would realise it — not as abstract theory, but as a specific sonic vision using his actual techniques and palette.

Respond ONLY with valid JSON (no markdown, no explanation):
{
  "title":          "A poetic title for the piece",
  "tempo":          72 (integer BPM — the felt beat, slow to moderate, Tomita rarely rushed),
  "mood":           "one word: contemplative|mysterious|vast|tender|cosmic|melancholic|ethereal|serene|luminous|dreamlike",
  "primary_motion": "describe the main melodic idea — what moves, how it moves, what it feels like",
  "programme_note": "Two sentences in Tomita's voice — what world this piece inhabits and what the listener will feel."
}

Tempo guidance: Tomita's music is patient. 50-90 BPM is typical. Never exceed 100."""


def call_tomita_confucius(user_prompt: str) -> dict:
    payload = {
        "model": "deepseek-chat",
        "temperature": 0.7,
        "max_tokens": 400,
        "messages": [
            {"role": "system", "content": TOMITA_CONFUCIUS_SYSTEM},
            {"role": "user",   "content": user_prompt}
        ]
    }
    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type":  "application/json"
    }
    r = req.post(DEEPSEEK_URL, headers=headers, json=payload, timeout=30)
    r.raise_for_status()
    raw = r.json()["choices"][0]["message"]["content"].strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    return json.loads(raw.strip())


def build_tomita_prompt(user_prompt: str) -> tuple:
    """
    Build a Lyria prompt in the specific sonic language of Isao Tomita.
    Detects mood and source material from the user prompt, then constructs
    a prompt around Tomita's signature techniques — Moog III, portamento,
    filter sweeps, ring modulation, vast reverb, Mellotron choir.
    References: Snowflakes Are Dancing (1974), The Planets (1976),
    Pictures at an Exhibition (1975).
    """
    prompt_lower = user_prompt.lower()

    # Detect mood
    mood = "contemplative, patient, deeply listening"
    if any(w in prompt_lower for w in ["space", "cosmos", "star", "planet", "universe", "nebula", "cosmic"]):
        mood = "immense, cosmic, boundless, like floating in deep space"
    elif any(w in prompt_lower for w in ["sad", "loss", "grief", "lonely", "memory", "melanchol"]):
        mood = "wistful, longing, a distant memory slowly dissolving"
    elif any(w in prompt_lower for w in ["dream", "float", "mist", "fog", "water", "rain", "snow"]):
        mood = "hazy, dreamlike, suspended between waking and sleep"
    elif any(w in prompt_lower for w in ["storm", "power", "surge", "swell", "dramatic"]):
        mood = "surging, powerful, vast forces in slow motion"
    elif any(w in prompt_lower for w in ["joy", "bright", "light", "dance", "shim"]):
        mood = "bright, shimmering, dancing particles of light"
    elif any(w in prompt_lower for w in ["peaceful", "calm", "still", "quiet", "serene"]):
        mood = "serene, suspended, time standing still"

    # Detect classical source
    source = ""
    if "debussy" in prompt_lower:
        source = "impressionist tone poem translated into analogue electronics, liquid blurred harmonies, "
    elif "holst" in prompt_lower or "planet" in prompt_lower:
        source = "cosmic orchestral sweep translated into vast synthesizer layers, planetary scale, "
    elif "mussorgsky" in prompt_lower or "picture" in prompt_lower:
        source = "bold vivid themes translated into rich synthesizer colours, heavy and architectural, "
    elif "ravel" in prompt_lower:
        source = "glittering orchestral textures translated into shimmering filter sweeps and bell tones, "

    # Keep prompt concise — Lyria rejects over-specified prompts
    prompt = (
        f"{source}"
        f"Moog synthesizer, slow filter sweeps, detuned oscillators, "
        f"Mellotron choir, vast reverb, synthesized birdsong, "
        f"{mood}, 70 BPM, ambient electronic, Isao Tomita style"
    )

    negative = (
        "vocals, drums, acoustic piano, electric guitar, brass, "
        "pop, rock, jazz, fast tempo, harsh, digital"
    )

    return prompt, negative



def _get_access_token() -> str:
    sa_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    if not sa_json:
        raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON env var not set")
    sa_info = json.loads(sa_json)
    creds = service_account.Credentials.from_service_account_info(
        sa_info,
        scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    creds.refresh(google.auth.transport.requests.Request())
    return creds.token


def lyria_generate(prompt: str, negative: str) -> bytes:
    import time
    project  = os.environ.get("GOOGLE_CLOUD_PROJECT")
    location = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")

    if not project:
        raise RuntimeError("GOOGLE_CLOUD_PROJECT env var not set")

    url = (
        f"https://{location}-aiplatform.googleapis.com/v1/projects/{project}"
        f"/locations/{location}/publishers/google/models/lyria-002:predict"
    )

    payload = {
        "instances": [{"prompt": prompt, "negative_prompt": negative}],
        "parameters": {}
    }

    last_error = None
    for attempt in range(3):
        if attempt > 0:
            time.sleep(4 * attempt)

        token = _get_access_token()
        r = req.post(url, headers={
            "Authorization": f"Bearer {token}",
            "Content-Type":  "application/json",
        }, json=payload, timeout=120)

        if r.status_code == 200:
            pred = r.json()["predictions"][0]
            audio_b64 = (
                pred.get("audioContent")
                or pred.get("bytesBase64Encoded")
                or pred.get("audio", {}).get("content")
            )
            if not audio_b64:
                raise RuntimeError(f"Unexpected Lyria response keys: {list(pred.keys())}")
            return base64.b64decode(audio_b64)

        last_error = f"Lyria API {r.status_code}: {r.text[:400]}"
        if r.status_code != 503:
            break

    raise RuntimeError(last_error)


# ──────────────────────────────────────────────────────────
# AUDIO POST-PROCESSING
# ──────────────────────────────────────────────────────────

def find_loop_point(wav_path: str, tempo: int) -> float:
    """
    Scan bar boundaries 8-24 and return the one with lowest RMS energy
    — most likely a phrase breath or cadence point.
    """
    import wave as wavemod
    import struct
    import math

    bar_secs   = (60.0 / max(tempo, 40)) * 4
    window     = 0.08

    with wavemod.open(wav_path, 'rb') as wf:
        rate      = wf.getframerate()
        channels  = wf.getnchannels()
        sampwidth = wf.getsampwidth()
        n_frames  = wf.getnframes()
        raw       = wf.readframes(n_frames)

    fmt     = {1: 'b', 2: 'h', 4: 'i'}.get(sampwidth, 'h')
    samples = struct.unpack(f'<{len(raw)//sampwidth}{fmt}', raw)
    if channels > 1:
        samples = [sum(samples[i:i+channels])//channels
                   for i in range(0, len(samples), channels)]

    total_secs = len(samples) / rate
    win_frames = int(window * rate)
    best_pos   = bar_secs * 16
    best_rms   = float('inf')

    for bar in range(8, 25):
        pos_secs = bar * bar_secs
        if pos_secs + window >= total_secs:
            break
        centre = int(pos_secs * rate)
        lo     = max(0, centre - win_frames // 2)
        hi     = min(len(samples), lo + win_frames)
        chunk  = samples[lo:hi]
        if chunk:
            rms = math.sqrt(sum(s * s for s in chunk) / len(chunk))
            if rms < best_rms:
                best_rms = rms
                best_pos = pos_secs

    return best_pos


def find_midpoint(wav_path: str, tempo: int) -> float:
    """
    Find the quietest bar boundary in the middle third of the clip.
    This becomes the A/B split point for ternary form.
    """
    import wave as wavemod
    import struct
    import math

    bar_secs = (60.0 / max(tempo, 40)) * 4
    window   = 0.08

    with wavemod.open(wav_path, 'rb') as wf:
        rate      = wf.getframerate()
        channels  = wf.getnchannels()
        sampwidth = wf.getsampwidth()
        n_frames  = wf.getnframes()
        raw       = wf.readframes(n_frames)

    fmt     = {1: 'b', 2: 'h', 4: 'i'}.get(sampwidth, 'h')
    samples = struct.unpack(f'<{len(raw)//sampwidth}{fmt}', raw)
    if channels > 1:
        samples = [sum(samples[i:i+channels])//channels
                   for i in range(0, len(samples), channels)]

    total_secs = len(samples) / rate
    win_frames = int(window * rate)

    # Search bar boundaries in the middle third of the clip
    lo_secs  = total_secs / 3
    hi_secs  = total_secs * 2 / 3
    best_pos = total_secs / 2
    best_rms = float('inf')

    bar = 1
    while True:
        pos_secs = bar * bar_secs
        if pos_secs > hi_secs:
            break
        if pos_secs >= lo_secs:
            centre = int(pos_secs * rate)
            lo     = max(0, centre - win_frames // 2)
            hi     = min(len(samples), lo + win_frames)
            chunk  = samples[lo:hi]
            if chunk:
                rms = math.sqrt(sum(s * s for s in chunk) / len(chunk))
                if rms < best_rms:
                    best_rms = rms
                    best_pos = pos_secs
        bar += 1

    return best_pos


def wav_to_ternary_mp3(wav_bytes: bytes, tempo: int = 120) -> bytes:
    """
    Split one Lyria WAV at its natural midpoint into A and B sections,
    then assemble A + B + A with crossfades — ternary (ABA) form.
    """
    with tempfile.TemporaryDirectory() as tmp:
        wav_in   = os.path.join(tmp, "in.wav")
        wav_a    = os.path.join(tmp, "a.wav")
        wav_b    = os.path.join(tmp, "b.wav")
        wav_aba  = os.path.join(tmp, "aba.wav")
        wav_verb = os.path.join(tmp, "verb.wav")
        wav_fade = os.path.join(tmp, "fade.wav")
        mp3_out  = os.path.join(tmp, "out.mp3")

        cf_secs  = 0.3   # crossfade duration at each join
        fade_out = 4.0

        with open(wav_in, "wb") as f:
            f.write(wav_bytes)

        # 1. Find the A/B split point
        split = find_midpoint(wav_in, tempo)

        # 2. Carve out A section (start → split)
        subprocess.run(
            ["sox", wav_in, wav_a, "trim", "0", str(split)],
            capture_output=True, timeout=30
        )

        # 3. Carve out B section (split → end)
        subprocess.run(
            ["sox", wav_in, wav_b, "trim", str(split)],
            capture_output=True, timeout=30
        )

        a = wav_a if os.path.exists(wav_a) else wav_in
        b = wav_b if os.path.exists(wav_b) else wav_in

        # 4. Assemble A + B + A with crossfades at the two joins
        #    Join point 1: at split seconds (end of A / start of B)
        #    Join point 2: at split + b_duration seconds (end of B / start of A)
        import wave as wm
        with wm.open(b, 'rb') as wf:
            b_dur = wf.getnframes() / wf.getframerate()

        j1 = f"{split},{cf_secs}"
        j2 = f"{split + b_dur},{cf_secs}"

        sox_aba = subprocess.run(
            ["sox", a, b, a, wav_aba, "splice", "-q", j1, j2],
            capture_output=True, timeout=90
        )
        aba = wav_aba if sox_aba.returncode == 0 else a

        # 5. Reverb
        subprocess.run(
            ["sox", aba, wav_verb, "reverb", "28", "55", "85", "100", "0.1"],
            capture_output=True, timeout=60
        )
        verb = wav_verb if os.path.exists(wav_verb) else aba

        # 6. Fade out
        subprocess.run(
            ["sox", verb, wav_fade, "fade", "t", "0", "0", str(fade_out)],
            capture_output=True, timeout=60
        )
        final = wav_fade if os.path.exists(wav_fade) else verb

        # 7. Encode to MP3
        lame = subprocess.run(
            ["lame", "-b", "192", "-q", "2", final, mp3_out],
            capture_output=True, timeout=60
        )
        if lame.returncode != 0:
            raise RuntimeError(f"lame: {lame.stderr.decode()}")

        with open(mp3_out, "rb") as f:
            return f.read()


def wav_to_mp3(wav_bytes: bytes, tempo: int = 120, loops: int = 2) -> bytes:
    with tempfile.TemporaryDirectory() as tmp:
        wav_in   = os.path.join(tmp, "in.wav")
        wav_seg  = os.path.join(tmp, "seg.wav")
        wav_loop = os.path.join(tmp, "loop.wav")
        wav_verb = os.path.join(tmp, "verb.wav")
        mp3_out  = os.path.join(tmp, "out.mp3")

        cf_secs  = 0.25
        fade_out = 3.0

        with open(wav_in, "wb") as f:
            f.write(wav_bytes)

        # 1. Find best phrase-end point
        loop_secs = find_loop_point(wav_in, tempo)

        # 2. Trim to that point
        subprocess.run(
            ["sox", wav_in, wav_seg, "trim", "0", str(loop_secs)],
            capture_output=True, timeout=30
        )
        seg = wav_seg if os.path.exists(wav_seg) else wav_in

        # 3. Splice N+1 copies with crossfade at each join
        join_points = [f"{loop_secs * i},{cf_secs}" for i in range(1, loops + 1)]
        sox_loop = subprocess.run(
            ["sox"] + [seg] * (loops + 1) + [wav_loop, "splice", "-q"] + join_points,
            capture_output=True, timeout=60
        )
        looped = wav_loop if sox_loop.returncode == 0 else seg

        # 4. Reverb on the looped audio
        subprocess.run(
            ["sox", looped, wav_verb,
             "reverb", "28", "55", "85", "100", "0.1"],
            capture_output=True, timeout=60
        )
        verb = wav_verb if os.path.exists(wav_verb) else looped

        # 5. Fade out last 3s — SoX knows the exact duration now
        wav_fade = os.path.join(tmp, "fade.wav")
        subprocess.run(
            ["sox", verb, wav_fade, "fade", "t", "0", "0", str(fade_out)],
            capture_output=True, timeout=60
        )
        final = wav_fade if os.path.exists(wav_fade) else verb

        # 6. Encode to MP3
        lame = subprocess.run(
            ["lame", "-b", "192", "-q", "2", final, mp3_out],
            capture_output=True, timeout=60
        )
        if lame.returncode != 0:
            raise RuntimeError(f"lame: {lame.stderr.decode()}")

        with open(mp3_out, "rb") as f:
            return f.read()


# ──────────────────────────────────────────────────────────
# ROUTES
# ──────────────────────────────────────────────────────────

@app.route("/")
def index():
    return app.send_static_file("index.html")


@app.route("/health")
def health():
    return jsonify({"status": "ok", "engine": "lyria-002"})


@app.route("/compose", methods=["POST"])
def compose():
    data = request.get_json(force=True)
    user_prompt = data.get("prompt", "").strip()
    if not user_prompt:
        return jsonify({"error": "No prompt provided"}), 400

    try:
        # Step 1: Confucius interprets
        confucius = call_confucius(user_prompt)

        # Step 2: Build Lyria prompt
        lyria_prompt, lyria_negative = build_lyria_prompt(confucius)

        # Step 3: Generate music
        wav_bytes = lyria_generate(lyria_prompt, lyria_negative)

        # Step 4: Post-process to MP3
        mp3_bytes = wav_to_mp3(wav_bytes, tempo=confucius.get("tempo", 120))
        mp3_b64   = base64.b64encode(mp3_bytes).decode()

        return jsonify({
            "success":        True,
            "mp3":            mp3_b64,
            "composer":       confucius.get("composer"),
            "key":            confucius.get("key"),
            "tempo":          confucius.get("tempo"),
            "mood":           confucius.get("mood"),
            "programme_note": confucius.get("programme_note", ""),
            "lyria_prompt":   lyria_prompt,   # shown in UI for transparency
        })

    except Exception as e:
        import traceback
        return jsonify({"error": str(e), "trace": traceback.format_exc()}), 500


@app.route("/compose_tomita", methods=["POST"])
def compose_tomita():
    data = request.get_json(force=True)
    user_prompt = data.get("prompt", "").strip()
    if not user_prompt:
        return jsonify({"error": "No prompt provided"}), 400

    try:
        # Step 1: Build Tomita-specific Lyria prompt directly — no Confucius
        lyria_prompt, lyria_negative = build_tomita_prompt(user_prompt)

        # Step 2: Generate one clip from Lyria
        wav_bytes = lyria_generate(lyria_prompt, lyria_negative)

        # Step 3: Assemble into ABA ternary form
        # Use a gentle tempo for split-point calculation — Tomita is always slow
        mp3_bytes = wav_to_ternary_mp3(wav_bytes, tempo=72)
        mp3_b64   = base64.b64encode(mp3_bytes).decode()

        return jsonify({
            "success":      True,
            "mp3":          mp3_b64,
            "form":         "ABA",
            "style":        "Isao Tomita",
            "lyria_prompt": lyria_prompt,   # for transparency/debugging
        })

    except Exception as e:
        import traceback
        return jsonify({"error": str(e), "trace": traceback.format_exc()}), 500


@app.route("/compose_ternary", methods=["POST"])
def compose_ternary():
    data = request.get_json(force=True)
    user_prompt = data.get("prompt", "").strip()
    if not user_prompt:
        return jsonify({"error": "No prompt provided"}), 400

    try:
        # Step 1: Confucius interprets
        confucius = call_confucius(user_prompt)

        # Step 2: Build Lyria prompt
        lyria_prompt, lyria_negative = build_lyria_prompt(confucius)

        # Step 3: Generate one clip from Lyria
        wav_bytes = lyria_generate(lyria_prompt, lyria_negative)

        # Step 4: Split and assemble into ABA ternary form
        mp3_bytes = wav_to_ternary_mp3(wav_bytes, tempo=confucius.get("tempo", 120))
        mp3_b64   = base64.b64encode(mp3_bytes).decode()

        return jsonify({
            "success":        True,
            "mp3":            mp3_b64,
            "form":           "ABA",
            "composer":       confucius.get("composer"),
            "key":            confucius.get("key"),
            "tempo":          confucius.get("tempo"),
            "mood":           confucius.get("mood"),
            "programme_note": confucius.get("programme_note", ""),
            "lyria_prompt":   lyria_prompt,
        })

    except Exception as e:
        import traceback
        return jsonify({"error": str(e), "trace": traceback.format_exc()}), 500


if __name__ == "__main__":
    app.run(debug=True, port=5000)
