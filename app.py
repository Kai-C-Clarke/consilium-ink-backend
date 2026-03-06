import os, re, subprocess, tempfile, base64, json, requests, random
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS

app = Flask(__name__, static_folder='.')
CORS(app)

DEEPSEEK_API_KEY = os.environ.get('DEEPSEEK_API_KEY', 'sk-44c5721e2b254942b2c208e052a3fc57')
SOUNDFONT = os.environ.get('SOUNDFONT', '/usr/share/sounds/sf2/FluidR3_GM.sf2')

CONFUCIUS_SYSTEM = """You are Confucius, the Master Voice of The Composer.
You interpret a user's feeling or mood and select the right composer and musical parameters.

Match ENERGY LEVEL first, then character:

HIGH ENERGY (fire, dancing, celebration, triumph, storms, battle, joy, excitement, laughter):
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


STYLE_MAPS = {
    "Bach": """STYLE — BACH:
V:1 melody: sequences (repeat pattern a step up/down), motor eighth notes, stepwise with 3rd/4th leaps, NO held notes
V:2 bass: walking bass — stepwise movement, as melodic as right hand, contrary motion to melody, eighth notes
Harmony: modulate to dominant or relative, seventh chords resolving by step, suspensions
Rhythm: continuous eighth notes in bass, strict time, terraced dynamics (sudden ff to pp)
AVOID: Alberti bass, waltz patterns, chromaticism, sentimentality""",

    "Mozart": """STYLE — MOZART:
V:1 melody: singing, graceful, 4-bar question/answer, peak at bar 3, one ornament per phrase
V:2 bass: Alberti bass — low note then chord alternating: C,2 G,2 E,2 G,2 — light throughout
Harmony: diatonic I-IV-V-vi, clear cadences, modulate to dominant for B section
Rhythm: quarters and eighths, at least one dotted rhythm per phrase
AVOID: chromaticism, sforzandi, continuous running eighths, anything effortful""",

    "Beethoven": """STYLE — BEETHOVEN:
V:1 melody: short motivic cell (2-4 notes), transposed up/down, dramatic octave leaps, rests as drama
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
Rhythm: expressively varied melody — mix 3+1+2+2, 4+2+2 patterns; never metronomic
AVOID: Alberti bass, walking bass, mechanical motion, block chords in melody""",

    "Debussy": """STYLE — DEBUSSY:
V:1 melody: pentatonic or whole-tone scale, long held notes (4-8 units), much silence (z), no strong arrival
V:2 bass: parallel chord blocks sliding by step, sustained pedal notes (4-8 units), no Alberti
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
V:1 melody: relentless sequences — same shape repeated a step up/down (D E F# | E F# G# | F# G# A)
  Rapid eighth notes, dotted rhythms, arpeggiate chord outlines, NEVER hold notes
V:2 bass: DRIVING REPEATED BASS — same note repeated every beat, or alternating with chord
  Correct example: D,2 D,2 D,2 D,2 | A,,2 A,,2 A,,2 A,,2 | D,2 (D,F,A,)2 D,2 (D,F,A,)2 |
  Bass must be insistent, rhythmic, never melodic, never held
Harmony: changes every beat, clear I-V-I, circle of fifths, modulate to dominant
Rhythm: continuous driving pulse, dotted rhythms, NO hesitation
AVOID: held notes, chromaticism, slow harmony, lyrical passages"""
}

RELATIVES = {
    "Cm":"Eb","Gm":"Bb","Dm":"F","Am":"C","Em":"G","Bm":"D",
    "Fm":"Ab","Bbm":"Db","C":"Am","G":"Em","D":"Bm","A":"F#m",
    "F":"Dm","Bb":"Gm","Eb":"Cm","Ab":"Fm","E":"C#m","B":"G#m"
}


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

══ FORMAT — FOLLOW EXACTLY ══

Use this exact header structure:
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

CRITICAL RULES:
1. Voice 1 comes FIRST (all 28 bars), then Voice 2 (all 28 bars). Never interleave.
2. Voice 1: ONE note at a time. Never (G4 c4). Correct: G3 A B2 c2
3. Every bar = exactly 8 units. eighth=1, quarter=2, dotted-quarter=3, half=4, whole=8
   WARNING: A/ = 0.5 (too short). Use A (=1) not A/
   WRONG: G3 A/ B2 c2 = 7.5  CORRECT: G3 A B2 c2 = 8
4. Voice 2 must have exactly 28 bars. Never leave it empty.
5. Mix note lengths — never all quarter notes (G2 A2 B2 c2 is mechanical and wrong)
6. Dynamics in Voice 1 only, in double quotes: "pp" "mp" "mf"

Output ONLY the ABC notation. No explanation. No markdown. Start with X:1"""


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


def postprocess_midi(mid_path, out_path):
    """Apply per-channel velocity shaping and timing humanisation."""
    try:
        import mido
        mid = mido.MidiFile(mid_path)
        out = mido.MidiFile(ticks_per_beat=mid.ticks_per_beat, type=mid.type)
        for track in mid.tracks:
            new_track = mido.MidiTrack()
            out.tracks.append(new_track)
            note_idx = 0
            for msg in track:
                if msg.type == 'note_on' and msg.velocity > 0:
                    ch = msg.channel
                    if ch == 0:  # melody
                        phrase_pos = (note_idx % 16) / 16.0
                        shape = 1.0 - abs(phrase_pos - 0.5) * 0.55
                        base_vel = int(70 + shape * 20)
                        vel = max(48, min(100, base_vel + random.randint(-6, 6)))
                        time_jitter = random.randint(-8, 8)
                    else:  # bass — quieter, steady
                        base_vel = 46
                        vel = max(32, min(60, base_vel + random.randint(-4, 4)))
                        time_jitter = 0
                    note_idx += 1
                    new_time = max(0, msg.time + time_jitter)
                    new_track.append(msg.copy(velocity=vel, time=new_time))
                else:
                    new_track.append(msg)
        out.save(out_path)
        return True
    except Exception:
        return False


def clean_abc(abc_text):
    lines = []
    for line in abc_text.split('\n'):
        if line.strip().startswith('```'): continue
        if '%%MIDI pedal' in line: continue
        lines.append(line)
    return '\n'.join(lines)


def abc_to_mp3(abc_text):
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

        render_mid = mid_pp_f if postprocess_midi(mid_f, mid_pp_f) and os.path.exists(mid_pp_f) else mid_f

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
        raw = call_deepseek([{"role": "user", "content": prompt}],
                            system=CONFUCIUS_SYSTEM, temperature=0.5)
        json_text = re.sub(r'```json|```', '', raw).strip()
        interp = json.loads(json_text)

        composer = interp.get('composer', 'Chopin')
        key      = interp.get('key', 'Cm')
        tempo    = interp.get('tempo', 66)
        mood     = interp.get('mood', 'reflective')
        note     = interp.get('programme_note', '')

        brief = build_brief(composer, key, tempo, mood)
        abc = call_deepseek([{"role": "user", "content": brief}],
                            temperature=0.6, max_tokens=3500)
        abc = re.sub(r'```abc|```', '', abc).strip()

        mp3 = abc_to_mp3(abc)

        return jsonify({'abc': abc, 'mp3': mp3, 'composer': composer,
                        'key': key, 'tempo': tempo, 'mood': mood,
                        'programme_note': note})

    except json.JSONDecodeError:
        return jsonify({'error': 'Confucius could not parse the mood', 'raw': raw}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
