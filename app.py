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

app = Flask(__name__)
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
    "Vivaldi": (
        "Baroque orchestral concerto, Antonio Vivaldi style, key of {key}, {tempo} BPM, "
        "solo violin lead over string orchestra and harpsichord continuo, "
        "rapid sequences ascending and descending, driving eighth-note rhythm, "
        "bright and energetic, Baroque period, concerto grosso"
    ),
    "Bach": (
        "Baroque keyboard music, Johann Sebastian Bach style, key of {key}, {tempo} BPM, "
        "harpsichord or pipe organ, intricate polyphonic counterpoint, "
        "multiple independent voices weaving together, fugue-like, "
        "steady rhythmic pulse, ornamental trills, Lutheran church gravitas"
    ),
    "Mozart": (
        "Classical period piano concerto, Wolfgang Amadeus Mozart style, key of {key}, {tempo} BPM, "
        "elegant piano melody with light string accompaniment, Alberti bass, "
        "balanced phrasing and graceful ornamentation, Viennese Classical, "
        "witty and refined, chamber orchestra"
    ),
    "Beethoven": (
        "Early Romantic orchestral, Ludwig van Beethoven style, key of {key}, {tempo} BPM, "
        "full symphony orchestra, dramatic dynamic contrasts, powerful brass and timpani, "
        "heroic and stormy, motivic development, intense and passionate, "
        "Romantic grandeur, fortissimo climaxes"
    ),
    "Chopin": (
        "Romantic solo piano nocturne, Frédéric Chopin style, key of {key}, {tempo} BPM, "
        "lyrical singing melody in right hand, flowing arpeggios in left hand, "
        "intimate and emotional, expressive rubato, rich Romantic harmonies, "
        "tender and introspective, bel canto influenced"
    ),
    "Tchaikovsky": (
        "Romantic orchestral, Pyotr Ilyich Tchaikovsky style, key of {key}, {tempo} BPM, "
        "full symphony orchestra, sweeping string melodies, lush and emotional, "
        "Russian Romantic character, nostalgic and yearning, "
        "rich orchestration with warm brass and woodwinds, big lyrical climax"
    ),
    "Debussy": (
        "French Impressionist piano, Claude Debussy style, key of {key}, {tempo} BPM, "
        "solo piano or small ensemble, whole-tone scales and parallel chords, "
        "shimmering atmospheric harmonies, dreamlike and evocative, "
        "colour and texture over melody, fluid and floating, gentle and mysterious"
    ),
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


def build_lyria_prompt(c: dict) -> tuple:
    composer = c.get("composer", "Mozart")
    key      = c.get("key", "C major")
    tempo    = c.get("tempo", 120)
    mood     = c.get("mood", "expressive").lower()

    style    = LYRIA_STYLE_PROMPTS.get(composer, LYRIA_STYLE_PROMPTS["Mozart"])
    style    = style.format(key=key, tempo=tempo)
    mood_str = MOOD_MAP.get(mood, mood)

    prompt = (
        f"{style}, {mood_str}, "
        "instrumental only, no vocals, "
        "professional classical music recording, high fidelity"
    )

    negative = (
        "drums, drum kit, electronic beats, synthesizer, electric guitar, "
        "distortion, bass guitar, vocals, singing, lyrics, rap, hip hop, "
        "jazz, pop, modern music, ambient noise, low quality"
    )

    return prompt, negative


# ──────────────────────────────────────────────────────────
# LYRIA API
# ──────────────────────────────────────────────────────────

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

    token = _get_access_token()
    r = req.post(url, headers={
        "Authorization": f"Bearer {token}",
        "Content-Type":  "application/json",
    }, json=payload, timeout=120)

    if r.status_code != 200:
        raise RuntimeError(f"Lyria API {r.status_code}: {r.text[:400]}")

    audio_b64 = r.json()["predictions"][0]["audioContent"]
    return base64.b64decode(audio_b64)


# ──────────────────────────────────────────────────────────
# AUDIO POST-PROCESSING
# ──────────────────────────────────────────────────────────

def wav_to_mp3(wav_bytes: bytes) -> bytes:
    with tempfile.TemporaryDirectory() as tmp:
        wav_in   = os.path.join(tmp, "in.wav")
        wav_verb = os.path.join(tmp, "verb.wav")
        mp3_out  = os.path.join(tmp, "out.mp3")

        with open(wav_in, "wb") as f:
            f.write(wav_bytes)

        # SoX reverb
        sox = subprocess.run(
            ["sox", wav_in, wav_verb, "reverb", "28", "55", "85", "100", "0.1"],
            capture_output=True, timeout=60
        )
        src = wav_verb if sox.returncode == 0 else wav_in

        # lame encode
        lame = subprocess.run(
            ["lame", "-b", "192", "-q", "2", src, mp3_out],
            capture_output=True, timeout=60
        )
        if lame.returncode != 0:
            raise RuntimeError(f"lame: {lame.stderr.decode()}")

        with open(mp3_out, "rb") as f:
            return f.read()


# ──────────────────────────────────────────────────────────
# ROUTES
# ──────────────────────────────────────────────────────────

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
        mp3_bytes = wav_to_mp3(wav_bytes)
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


if __name__ == "__main__":
    app.run(debug=True, port=5000)
