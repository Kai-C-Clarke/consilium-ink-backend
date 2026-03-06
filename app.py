import os, re, subprocess, tempfile, base64, json, requests, random
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS

app = Flask(__name__, static_folder='.')
CORS(app)

DEEPSEEK_API_KEY = os.environ.get('DEEPSEEK_API_KEY', 'sk-44c5721e2b254942b2c208e052a3fc57')
SOUNDFONT = os.environ.get('SOUNDFONT', '/usr/share/sounds/sf2/FluidR3_GM.sf2')

# ── Confucius ─────────────────────────────────────────────────────────────────

CONFUCIUS_SYSTEM = """You are Confucius, the Master Voice of The Composer.
You interpret a user's feeling or mood and select the right composer and musical parameters.

Match ENERGY LEVEL first, then character:

HIGH ENERGY (fire, dancing, celebration, triumph, storms, battle, joy, excitement, flags, wind, waves):
- Vivaldi: driving sequences, rapid notes, bright, unstoppable forward motion
- Beethoven: dramatic power, motivic force, sudden silences, heroic struggle

MEDIUM ENERGY (walking, flowing, conversation, curiosity, elegance, narrative):
- Bach: contrapuntal, walking bass, intellectual, ordered
- Mozart: singing melody, Alberti bass, elegant, balanced, graceful

LOW ENERGY (melancholy, longing, dreams, night, twilight, memory, grief, love, solitude):
- Chopin: nocturne, bel canto, chromatic, ornamental, intimate
- Tchaikovsky: sweeping lyrical, passionate, emotional, romantic yearning
- Debussy: impressionist, floating, atmospheric, colour without narrative

EXAMPLES:
"fire, dancers, chanting" -> Vivaldi, minor, fast (120-132)
"flag flying, storm, waves" -> Vivaldi, minor, fast (126-132)
"village celebration" -> Vivaldi, major, fast (116-132)
"triumphant homecoming" -> Beethoven, major, strong (96-112)
"lonely autumn evening" -> Chopin, minor, slow (60-72)
"gentle morning light" -> Debussy, major, slow (60-76)
"deep grief" -> Chopin or Tchaikovsky, minor, slow (54-66)
"intellectual puzzle" -> Bach, minor, moderate (84-96)

Output ONLY a JSON object, no markdown:
{
  "composer": "Vivaldi",
  "key": "Dm",
  "tempo": 126,
  "mood": "fierce and exhilarating, like flames rising",
  "programme_note": "Two or three sentences in Confucius voice — poetic, oblique, wise."
}

Keys: minor (Cm, Dm, Gm, Am, Em) for dark/fierce/sad; major (C, D, F, G, Bb) for bright/joyful
Tempo: 54-72 slow, 76-96 moderate, 100-116 lively, 120-144 fast"""


# ── Style maps ────────────────────────────────────────────────────────────────

STYLE_MAPS = {
    "Bach": """STYLE — BACH:
V:1 melody: sequences (repeat pattern a step up/down), motor eighth notes, stepwise with 3rd/4th leaps
V:2 bass: walking bass — stepwise, as melodic as right hand, contrary motion, eighth notes throughout
Harmony: modulate to dominant or relative, seventh chords by step, suspensions (4-3, 7-6)
Rhythm: continuous eighth notes in bass, strict time, terraced dynamics
AVOID: Alberti bass, waltz patterns, chromaticism, sentimentality""",

    "Mozart": """STYLE — MOZART:
V:1 melody: singing, graceful, 4-bar question/answer, peak at bar 3, one ornament per phrase
V:2 bass: Alberti bass — low note then chord: C,2 G,2 E,2 G,2 — light throughout
Harmony: diatonic I-IV-V-vi, clear cadences, modulate to dominant for B section
Rhythm: quarters and eighths, at least one dotted rhythm per phrase
AVOID: chromaticism, sforzandi, anything effortful""",

    "Beethoven": """STYLE — BEETHOVEN:
V:1 melody: short motivic cell (2-4 notes), transposed up/down, dramatic leaps, rests as drama
V:2 bass: heavy block chords on strong beats, octave bass notes for power, sforzando accents
Harmony: subito pp after ff, diminished sevenths, unexpected key changes
Rhythm: dotted rhythms, at least one bar of silence (z8), accents on weak beats
AVOID: long lyrical lines, gentle motion, ornamental decoration""",

    "Chopin": """STYLE — CHOPIN:
V:1 melody: long arching bel canto lines, chromatic passing notes, trill (!trill!), grace notes, dotted rhythms
V:2 bass: NOCTURNE BASS — deep bass note (2 units) then mid-register chord (6 units) per bar
  Correct example: C,,2 (EGc)6 | G,,2 (DGb)6 | F,,2 (FAc)6 | G,,2 (GBd)6 |
  NEVER use Alberti bass or walking bass for Chopin
Harmony: chromatic inner voices, Neapolitan chord, delayed resolution
Rhythm: expressively varied — mix 3+1+2+2, 4+2+2 patterns; never metronomic
AVOID: Alberti bass, walking bass, mechanical motion, block chords in melody""",

    "Debussy": """STYLE — DEBUSSY:
V:1 melody: pentatonic or whole-tone scale, long held notes (4-8 units), silence (z), no strong arrival
V:2 bass: parallel chord blocks sliding by step, sustained pedal notes (4-8 units)
Harmony: parallel ninth chords, NO dominant-tonic resolution, colour not function
Rhythm: long values dominate, no strong beat-1 accent
AVOID: diatonic runs, rhythmic drive, clear cadences, Alberti bass""",

    "Tchaikovsky": """STYLE — TCHAIKOVSKY:
V:1 melody: sweeping arching lines, soar then sigh downward (e2 d2 c2), climax at bar 5-6
V:2 bass: sustained half-note chords — two chords per bar, inner voice movement between them
  Correct example: (DFA)4 (EGB)4 | (CEG)4 (DFA)4 | — warm, rich, sustained
Harmony: diminished seventh, augmented sixth, sequence a step lower for yearning
Rhythm: lyrical and unhurried, long values at phrase peaks
AVOID: short motivic cells, mechanical regularity, harsh dissonance""",

    "Vivaldi": """STYLE — VIVALDI:
V:1 melody: sequences — same pattern repeated a step up/down (D E F A | E F G B | F G A c)
  Rapid eighth notes throughout. Dotted rhythms for energy.
  ARPEGGIATE chords by writing notes SEQUENTIALLY — never as brackets:
  WRONG: (DFA)4  ← block chord, forbidden ✗
  CORRECT: D2 F2 A2 d2  ← broken arpeggio, ascending ✓
  CORRECT: d2 A2 F2 D2  ← broken arpeggio, descending ✓
  Never hold a note longer than 2 units in fast passages.

V:2 bass: DRIVING ALTERNATING BASS — root note then chord, every 2 units:
  Correct bar in Dm: D,2 (DFA)2 D,2 (DFA)2 |
  Correct bar in Am: A,,2 (ACE)2 A,,2 (ACE)2 |
  Correct bar in F:  F,,2 (FAC)2 F,,2 (FAC)2 |
  Root = 2 units, chord = 2 units, alternating. Total = 8. Always.

Harmony: chord changes every bar or half-bar, clear I-V-i-IV, circle of fifths
Rhythm: relentless eighth-note pulse in both voices, NO held notes
AVOID: bracket chords in melody, held notes over 2 units, lyrical passages, chromaticism"""
}

# ── Critic checklists ─────────────────────────────────────────────────────────
# Each criterion has: id, description, what to look for in ABC text

CRITIC_CHECKLISTS = {
    "Bach": [
        {"id": "sequences",    "check": "Does Voice 1 melody contain sequences — the same short pattern repeated starting on a different pitch? Look for runs like D E F G | E F G A | F G A B"},
        {"id": "walking_bass", "check": "Does Voice 2 move stepwise like a walking bass — mostly single notes moving up or down by step — rather than Alberti bass or block chords?"},
        {"id": "motor_rhythm", "check": "Does Voice 2 bass contain continuous eighth notes (single-unit notes) throughout, maintaining a motor rhythm?"},
        {"id": "no_alberti",   "check": "Does Voice 2 avoid Alberti bass patterns (low-high-mid-high repetition)? Bach never uses Alberti."},
    ],
    "Mozart": [
        {"id": "alberti",      "check": "Does Voice 2 use Alberti bass — a pattern of low note, high note, middle note, high note repeating? Example: C,2 G,2 E,2 G,2"},
        {"id": "singing",      "check": "Does Voice 1 melody move in a graceful, singing line with a clear peak note around bar 3, not jagged or angular?"},
        {"id": "diatonic",     "check": "Is the harmony mostly diatonic — no unusual chromatic notes, no diminished sevenths, no augmented chords?"},
        {"id": "phrases",      "check": "Are there clear rests or cadence points roughly every 4 bars, giving the melody room to breathe?"},
    ],
    "Beethoven": [
        {"id": "motif",        "check": "Does Voice 1 melody use a short motivic cell of 2-4 notes that reappears transposed to different pitch levels?"},
        {"id": "heavy_bass",   "check": "Does Voice 2 use heavy block chords or octave bass notes — substantial, weighty, not delicate?"},
        {"id": "dynamics",     "check": "Are there contrasting dynamics — at least one forte or ff passage AND at least one piano or pp passage?"},
        {"id": "silence",      "check": "Is there at least one bar or partial bar of rest (z) in Voice 1, used dramatically?"},
    ],
    "Chopin": [
        {"id": "nocturne_bass","check": "Does Voice 2 use nocturne bass — a deep single bass note (2 units) followed by a mid-register chord (6 units) per bar? Example: C,,2 (EGc)6. NOT Alberti bass."},
        {"id": "no_alberti",   "check": "Does Voice 2 completely avoid Alberti bass patterns? Chopin's nocturnes never use Alberti bass."},
        {"id": "bel_canto",    "check": "Does Voice 1 melody have long arching phrases that rise and fall gracefully, not short choppy fragments?"},
        {"id": "chromatic",    "check": "Does Voice 1 melody include at least some chromatic passing notes — notes outside the diatonic scale used as passing tones?"},
        {"id": "ornament",     "check": "Does Voice 1 include at least one ornament — a trill (!trill!), grace note, or mordent?"},
    ],
    "Debussy": [
        {"id": "pentatonic",   "check": "Does Voice 1 melody primarily use pentatonic or whole-tone scales, avoiding conventional stepwise diatonic runs?"},
        {"id": "long_notes",   "check": "Does Voice 1 melody contain long held notes (4 or more units) and silences (z), creating space and stillness?"},
        {"id": "parallel",     "check": "Does Voice 2 contain parallel chord movement — the same chord shape repeating at different pitch levels?"},
        {"id": "no_cadence",   "check": "Does the harmony avoid obvious dominant-tonic (V-I) cadences? Debussy dissolves, never resolves strongly."},
    ],
    "Tchaikovsky": [
        {"id": "sweep",        "check": "Does Voice 1 melody have long sweeping phrases that rise significantly before sighing downward? Look for arches of 6+ notes."},
        {"id": "half_chords",  "check": "Does Voice 2 use sustained half-note chords — two chords per bar lasting 4 units each? Example: (DFA)4 (EGB)4"},
        {"id": "no_alberti",   "check": "Does Voice 2 avoid Alberti bass? Tchaikovsky uses sustained inner voice chords, not Alberti."},
        {"id": "rich_harmony", "check": "Does the harmony include at least one diminished seventh chord or chromatic inner voice movement?"},
    ],
    "Vivaldi": [
        {"id": "sequences",    "check": "Does Voice 1 melody contain sequences — the exact same melodic shape repeated starting a step higher or lower? This is essential for Vivaldi."},
        {"id": "no_brackets_v1","check": "Does Voice 1 completely avoid bracket notation like (DFA)? In Vivaldi, chords must be broken as sequential notes: D2 F2 A2 not (DFA)6"},
        {"id": "rapid_notes",  "check": "Does Voice 1 use predominantly eighth notes (1-unit) and dotted rhythms, with NO note longer than 2 units?"},
        {"id": "driving_bass", "check": "Does Voice 2 alternate between a bass root note and a chord every 2 units? Example: D,2 (DFA)2 D,2 (DFA)2 — insistent, never melodic."},
        {"id": "no_lyrical",   "check": "Does Voice 1 avoid long held notes, lyrical sustained passages, or anything that sounds like Chopin or Tchaikovsky?"},
    ],
}

RELATIVES = {
    "Cm":"Eb","Gm":"Bb","Dm":"F","Am":"C","Em":"G","Bm":"D",
    "Fm":"Ab","Bbm":"Db","C":"Am","G":"Em","D":"Bm","A":"F#m",
    "F":"Dm","Bb":"Gm","Eb":"Cm","Ab":"Fm","E":"C#m","B":"G#m"
}

KEY_SCALES = {
    "Dm": {2,5,7,9,0,4},   "Cm": {0,2,3,5,7,8,10},
    "Gm": {7,9,10,0,2,3,5},"Am": {9,11,0,2,4,5,7},
    "Em": {4,6,7,9,11,0,2},"Bm": {11,1,2,4,6,7,9},
    "C":  {0,2,4,5,7,9,11},"G":  {7,9,11,0,2,4,6},
    "D":  {2,4,6,7,9,11,1},"F":  {5,7,9,10,0,2,4},
    "Bb": {10,0,2,3,5,7,9},"Eb": {3,5,7,8,10,0,2},
    "Ab": {8,10,0,1,3,5,7},
}


# ── Brief builder ─────────────────────────────────────────────────────────────

def build_brief(composer, key, tempo, mood):
    style = STYLE_MAPS.get(composer, STYLE_MAPS["Chopin"])
    key_b = RELATIVES.get(key, "F")
    return f"""Compose a ternary form piece (ABA') with coda in the style of {composer}.
Mood: {mood}

Section A: 8 bars, K:{key}, Q:1/4={tempo}
Section B: 8 bars, K:{key_b}, contrasting character
Section A': 8 bars, K:{key}, return embellished
Coda: 4 bars, dissolving descent

{style}

══ FORMAT — FOLLOW EXACTLY OR THE MUSIC WILL NOT PLAY ══

X:1
T:Title
M:4/4
L:1/8
Q:1/4={tempo}
K:{key}
V:1 clef=treble name="Melody"
%%MIDI channel 1
%%MIDI program 0
[ALL 28 bars of Voice 1 here]
V:2 clef=bass name="Bass"
%%MIDI channel 2
%%MIDI program 0
[ALL 28 bars of Voice 2 here]

RULES:
1. Voice 1 ALL 28 bars first. Then Voice 2 ALL 28 bars. NEVER interleave.
2. Voice 1: ONE note at a time. Never (G4 c4). Write: G2 c2 A2 F2
3. Every bar = exactly 8 units. eighth=1, quarter=2, dotted-quarter=3, half=4
   WARNING: D/ = 0.5 units (too short). Use D (=1) not D/
   WRONG: D3 E/ F2 G2 = 7.5  CORRECT: D3 E F2 G2 = 8
4. Voice 2: exactly 28 bars. Never empty.
5. Mix note lengths — never all quarter notes.
6. Dynamics in Voice 1 only, in double quotes.

Output ONLY ABC notation. No explanation. No markdown. Start with X:1"""


# ── Critic ────────────────────────────────────────────────────────────────────

CRITIC_SYSTEM = """You are a musicologist and expert in classical piano composition.
You will be given an ABC notation score and asked to evaluate it against specific criteria.
You must examine the actual notation carefully and literally — do not assume, infer, or give benefit of the doubt.

For each criterion, respond with PASS or FAIL and one sentence of specific evidence from the notation.
Be strict. If a criterion is only partially met, mark it FAIL.

Output ONLY a JSON array — no markdown, no explanation:
[
  {"id": "criterion_id", "result": "PASS", "evidence": "Voice 2 shows D,2 (DFA)2 pattern in bar 1"},
  {"id": "criterion_id", "result": "FAIL", "evidence": "Voice 1 bar 3 contains (G4 c4) — a bracket chord, not sequential notes"}
]"""


def critique_abc(abc_text, composer):
    """Ask DeepSeek to evaluate the ABC notation against composer-specific criteria."""
    checklist = CRITIC_CHECKLISTS.get(composer, [])
    if not checklist:
        return [], []

    criteria_text = "\n".join(
        f'{i+1}. [{c["id"]}] {c["check"]}'
        for i, c in enumerate(checklist)
    )

    prompt = f"""Here is an ABC notation score composed in the style of {composer}:

{abc_text}

Evaluate it against these criteria. Examine the notation literally and carefully.

{criteria_text}

Output ONLY a JSON array as instructed."""

    try:
        raw = call_deepseek(
            [{"role": "user", "content": prompt}],
            system=CRITIC_SYSTEM,
            temperature=0.2,
            max_tokens=1000
        )
        raw_clean = re.sub(r'```json|```', '', raw).strip()
        results = json.loads(raw_clean)
        failures = [r for r in results if r.get('result') == 'FAIL']
        return results, failures
    except Exception:
        return [], []


def build_correction_brief(composer, key, tempo, mood, abc_text, failures):
    """Build a targeted correction prompt citing specific failures."""
    failure_text = "\n".join(
        f"- [{f['id']}] FAILED: {f['evidence']}"
        for f in failures
    )
    style = STYLE_MAPS.get(composer, STYLE_MAPS["Chopin"])
    key_b = RELATIVES.get(key, "F")

    return f"""Your previous composition in the style of {composer} failed a quality review.
Here is the original ABC notation:

{abc_text}

These specific problems were identified:
{failure_text}

Rewrite the piece in full, correcting ALL of these failures.
Keep what works. Fix what doesn't.

{style}

══ FORMAT — unchanged from before ══
X:1
T:Title
M:4/4
L:1/8
Q:1/4={tempo}
K:{key}
V:1 clef=treble name="Melody"
%%MIDI channel 1
%%MIDI program 0
[ALL 28 bars of Voice 1]
V:2 clef=bass name="Bass"
%%MIDI channel 2
%%MIDI program 0
[ALL 28 bars of Voice 2]

RULES: Voice 1 all 28 bars first. Every bar = 8 units. Voice 1 single notes only. Voice 2 never empty.

Output ONLY the corrected ABC notation. No explanation. No markdown. Start with X:1"""


# ── API call ──────────────────────────────────────────────────────────────────

def call_deepseek(messages, system=None, temperature=0.7, max_tokens=3500):
    payload = {
        "model": "deepseek-chat",
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens
    }
    if system:
        payload["messages"] = [{"role": "system", "content": system}] + messages
    r = requests.post(
        "https://api.deepseek.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                 "Content-Type": "application/json"},
        json=payload, timeout=90
    )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


# ── MIDI post-processor ───────────────────────────────────────────────────────

def postprocess_midi(mid_path, out_path, key="Dm", composer="Vivaldi"):
    try:
        import mido
        allowed_pcs = set(KEY_SCALES.get(key, KEY_SCALES["Dm"]))
        minor_keys = {"Dm","Cm","Gm","Am","Em","Bm","Fm","Bbm"}
        if key in minor_keys:
            root = list(KEY_SCALES.get(key, {0}))[0]
            allowed_pcs.add((root - 2) % 12)  # harmonic minor raised 7th

        mid = mido.MidiFile(mid_path)
        out = mido.MidiFile(ticks_per_beat=mid.ticks_per_beat, type=mid.type)

        for track in mid.tracks:
            new_track = mido.MidiTrack()
            out.tracks.append(new_track)
            note_idx = 0
            for msg in track:
                if msg.type == 'note_on' and msg.velocity > 0:
                    ch = msg.channel
                    pitch = msg.note
                    pc = pitch % 12
                    # Pitch correction
                    if pc not in allowed_pcs:
                        if (pc - 1) % 12 in allowed_pcs:
                            pitch -= 1
                        elif (pc + 1) % 12 in allowed_pcs:
                            pitch += 1
                        pitch = max(21, min(108, pitch))
                    # Velocity + timing
                    if ch == 0:
                        phrase_pos = (note_idx % 16) / 16.0
                        shape = 1.0 - abs(phrase_pos - 0.45) * 0.5
                        beat_accent = 12 if (note_idx % 4 == 0) else 0
                        base_vel = int(72 + shape * 18) + beat_accent
                        vel = max(55, min(105, base_vel + random.randint(-8, 8)))
                        time_jitter = random.randint(-5, 3) if note_idx % 4 == 0 else random.randint(-10, 12)
                    else:
                        is_root = (note_idx % 2 == 0)
                        base_vel = 58 if is_root else 48
                        vel = max(38, min(68, base_vel + random.randint(-5, 5)))
                        time_jitter = random.randint(-4, 4)
                    note_idx += 1
                    new_track.append(msg.copy(note=pitch, velocity=vel,
                                              time=max(0, msg.time + time_jitter)))
                else:
                    new_track.append(msg)
        out.save(out_path)
        return True
    except Exception:
        return False


# ── Audio pipeline ────────────────────────────────────────────────────────────

def clean_abc(abc_text):
    lines = []
    for line in abc_text.split('\n'):
        if line.strip().startswith('```'): continue
        if '%%MIDI pedal' in line: continue
        lines.append(line)
    return '\n'.join(lines)


def abc_to_mp3(abc_text, key="Dm", composer="Vivaldi"):
    with tempfile.TemporaryDirectory() as d:
        abc_f     = os.path.join(d, 'piece.abc')
        mid_f     = os.path.join(d, 'piece.mid')
        mid_pp_f  = os.path.join(d, 'piece_pp.mid')
        wav_f     = os.path.join(d, 'piece.wav')
        wav_rev_f = os.path.join(d, 'piece_reverb.wav')
        mp3_f     = os.path.join(d, 'piece.mp3')

        with open(abc_f, 'w') as f:
            f.write(clean_abc(abc_text))

        r = subprocess.run(['abc2midi', abc_f, '-o', mid_f],
                           capture_output=True, text=True, timeout=30)
        if not os.path.exists(mid_f):
            raise RuntimeError(f"abc2midi: {r.stderr[:400]}")

        render_mid = mid_pp_f if postprocess_midi(mid_f, mid_pp_f, key, composer) \
                                 and os.path.exists(mid_pp_f) else mid_f

        r = subprocess.run(['fluidsynth', '-ni', '-F', wav_f, '-r', '44100',
                            SOUNDFONT, render_mid],
                           capture_output=True, text=True, timeout=60)
        if not os.path.exists(wav_f):
            raise RuntimeError(f"fluidsynth: {r.stderr[:400]}")

        subprocess.run(['sox', wav_f, wav_rev_f,
                        'reverb', '28', '55', '85', '100', '0.1'],
                       capture_output=True, timeout=30)
        render_wav = wav_rev_f if os.path.exists(wav_rev_f) else wav_f

        r = subprocess.run(['lame', '-b', '192', '-q', '2', render_wav, mp3_f],
                           capture_output=True, text=True, timeout=30)
        if not os.path.exists(mp3_f):
            raise RuntimeError(f"lame: {r.stderr[:300]}")

        with open(mp3_f, 'rb') as f:
            return base64.b64encode(f.read()).decode()


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route('/')
def index():
    return send_from_directory('.', 'index.html')


@app.route('/compose', methods=['POST'])
def compose():
    data = request.json or {}
    prompt = data.get('prompt', '').strip()
    if not prompt:
        return jsonify({'error': 'No prompt provided'}), 400
    raw = ''
    try:
        # Step 1: Confucius interprets
        raw = call_deepseek([{"role": "user", "content": prompt}],
                            system=CONFUCIUS_SYSTEM, temperature=0.5)
        json_text = re.sub(r'```json|```', '', raw).strip()
        interp = json.loads(json_text)

        composer = interp.get('composer', 'Chopin')
        key      = interp.get('key', 'Cm')
        tempo    = interp.get('tempo', 66)
        mood     = interp.get('mood', 'reflective')
        note     = interp.get('programme_note', '')

        # Step 2: Compose
        brief = build_brief(composer, key, tempo, mood)
        abc = call_deepseek([{"role": "user", "content": brief}],
                            temperature=0.6, max_tokens=3500)
        abc = re.sub(r'```abc|```', '', abc).strip()

        # Step 3: Critique
        critique_results, failures = critique_abc(abc, composer)
        critique_summary = {
            "total": len(critique_results),
            "passed": len([r for r in critique_results if r.get('result') == 'PASS']),
            "failed": len(failures),
            "failures": [f['id'] for f in failures]
        }

        # Step 4: Retry if failures found
        if failures:
            correction_brief = build_correction_brief(
                composer, key, tempo, mood, abc, failures
            )
            abc_v2 = call_deepseek([{"role": "user", "content": correction_brief}],
                                   temperature=0.5, max_tokens=3500)
            abc_v2 = re.sub(r'```abc|```', '', abc_v2).strip()

            # Re-critique to confirm improvement
            _, failures_v2 = critique_abc(abc_v2, composer)
            # Accept v2 if it improved (fewer failures), otherwise keep whichever is better
            if len(failures_v2) <= len(failures):
                abc = abc_v2
                critique_summary['revised'] = True
                critique_summary['failures_after_revision'] = [f['id'] for f in failures_v2]
            else:
                critique_summary['revised'] = False

        # Step 5: Render
        mp3 = abc_to_mp3(abc, key=key, composer=composer)

        return jsonify({
            'abc': abc, 'mp3': mp3,
            'composer': composer, 'key': key,
            'tempo': tempo, 'mood': mood,
            'programme_note': note,
            'critique': critique_summary
        })

    except json.JSONDecodeError:
        return jsonify({'error': 'Confucius could not parse the mood', 'raw': raw}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
