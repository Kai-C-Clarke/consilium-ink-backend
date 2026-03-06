import os, re, subprocess, tempfile, base64, json, requests
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS

app = Flask(__name__, static_folder='.')
CORS(app)

DEEPSEEK_API_KEY = os.environ.get('DEEPSEEK_API_KEY', 'sk-44c5721e2b254942b2c208e052a3fc57')
SOUNDFONT = os.environ.get('SOUNDFONT', '/usr/share/sounds/sf2/FluidR3_GM.sf2')

CONFUCIUS_SYSTEM = """You are Confucius, the Master Voice of The Composer.
You interpret a user's feeling or mood and select the right composer and musical parameters.

Your roster:
- Bach: contrapuntal, walking bass, sequences, motor rhythm, minor keys
- Mozart: Alberti bass, singing melody, elegant, major keys, balanced
- Beethoven: dramatic, motivic, sudden dynamics, heroic, minor keys
- Chopin: nocturne, bel canto, chromatic, ornamental, melancholy
- Debussy: impressionist, parallel chords, pentatonic, floating, atmospheric
- Tchaikovsky: sweeping lyrical, waltz bass, passionate, emotional
- Vivaldi: driving rhythm, sequences, bright, energetic

From the user prompt output ONLY a JSON object — no markdown, no explanation:
{
  "composer": "Chopin",
  "key": "Cm",
  "tempo": 66,
  "mood": "melancholy and yearning",
  "programme_note": "Two or three sentences in Confucius voice — poetic, oblique, wise."
}

Key choices: Use minor keys (Cm, Gm, Dm, Am, Em) for dark/sad moods.
Use major keys (C, G, D, F, Bb, Eb) for bright/happy moods.
Tempo: 54-72 for slow, 76-96 for moderate, 100-132 for fast."""


STYLE_MAPS = {
    "Bach": """STYLE — BACH:
Melody: sequences (pattern repeated a step up/down), motor eighth notes, NO long held notes, imitation between voices
Left hand: walking bass — stepwise, as melodic as right hand, contrary motion when possible
Harmony: modulate to dominant or relative, seventh chords resolving by step, suspensions
Rhythm: continuous eighth notes in at least one voice, strict time, terraced dynamics (sudden not gradual)
AVOID: Alberti bass, waltz patterns, chromatic passing notes, sentimentality, rubato""",

    "Mozart": """STYLE — MOZART:
Melody: singing, graceful, clear 4-bar question/answer phrases, peak note at bar 3, one ornament per phrase
Left hand: Alberti bass pattern (low-high-mid-high: C,2 G,2 E,2 G,2), light, never louder than melody
Harmony: diatonic I-IV-V-vi, clear perfect cadences at phrase ends, modulate to dominant for Section B
Rhythm: mix of quarter and eighth notes, at least one dotted rhythm per phrase, rests at cadences
AVOID: chromatic harmony, dramatic sforzandi, continuous running eighths, anything effortful""",

    "Beethoven": """STYLE — BEETHOVEN:
Melody: short motivic cell of 2-4 notes, then developed — transposed, fragmented, inverted; dramatic leaps; rests as expression
Left hand: heavy block chords on strong beats, sforzando accents, octave bass notes for weight and power
Harmony: sudden subito pp after ff, diminished seventh chords, unexpected key changes, bold modulations
Rhythm: dotted rhythms for drive, at least one bar of full silence for drama, accents on unexpected beats
AVOID: long lyrical arching lines, gentle even motion, ornamental decoration, predictable progressions""",

    "Chopin": """STYLE — CHOPIN:
Melody: long arching bel canto lines, chromatic passing notes (C to E via C# D D#), at least one trill and grace note, dotted rhythms
Left hand: nocturne bass — deep single note on beat 1, mid-register chord on beats 2-3 (e.g. C,4 (EGc)4)
Harmony: chromatic inner voices moving by semitone, Neapolitan chord (flat II), harmonic ambiguity, delayed resolution
Rhythm: expressively varied — mix 3-unit, 2-unit, 1-unit notes; never metronomic; melody pushes and pulls
AVOID: Alberti bass, walking bass, mechanical even motion, loud dramatic outbursts, block chords in melody""",

    "Debussy": """STYLE — DEBUSSY:
Melody: pentatonic (C D E G A) or whole-tone scale (C D E F# G# Bb), long held notes, much silence, avoid strong cadential arrival
Left hand: sustained pedal note for multiple bars, parallel chord movement (same voicing sliding up/down by step)
Harmony: parallel chords moving in blocks, ninth and eleventh chords for colour, NO dominant-tonic resolution
Rhythm: long note values dominate, barlines are suggestions not walls, no strong beat-1 accent
AVOID: stepwise diatonic scale runs, driving rhythm, clear perfect cadences, ornamental trills, Alberti bass""",

    "Tchaikovsky": """STYLE — TCHAIKOVSKY:
Melody: sweeping arching lines that soar and sigh, characteristic two-note fall from peak (e.g. e2 d2), climax with mf or f
Left hand: waltz bass (strong single note beat 1, light chords beats 2-3), or in 4/4 rich sustained inner voices
Harmony: diminished seventh and augmented sixth chords, sequential harmony (progression repeated a step lower for yearning)
Rhythm: waltz pulse if 3/4, long values at phrase peaks, implied ritardando at phrase ends
AVOID: short motivic cells, pentatonic scales, mechanical regularity, sudden harsh dissonance""",

    "Vivaldi": """STYLE — VIVALDI:
Melody: sequences relentlessly (C D E | D E F | E F G — same shape ascending/descending), rapid eighth/sixteenth notes, arpeggiated chord outlines
Left hand: driving repeated notes or octaves on EVERY beat, never melodic, always rhythmically insistent
Harmony: changes on every beat or half-bar, clear I-V-I, circle of fifths sequences, modulate to dominant for B section
Rhythm: continuous driving pulse, NO rubato or hesitation, dotted rhythms for energy, accents on beat 1 of every bar
AVOID: long held notes, chromatic ambiguity, slow harmonic rhythm, gentle lyrical lines, sustained bass notes"""
}

RELATIVES = {
    "Cm":"Eb","Gm":"Bb","Dm":"F","Am":"C","Em":"G","Bm":"D",
    "Fm":"Ab","Bbm":"Db","C":"Am","G":"Em","D":"Bm","A":"F#m",
    "F":"Dm","Bb":"Gm","Eb":"Cm","Ab":"Fm","E":"C#m","B":"G#m"
}

def build_brief(composer, key, tempo, mood):
    style = STYLE_MAPS.get(composer, STYLE_MAPS["Chopin"])
    key_b = RELATIVES.get(key, "Eb")
    return f"""Compose a complete ternary form (ABA') piece with coda in the style of {composer}.

Section A: 8 bars, K:{key}, Q:1/4={tempo}, "pp", {mood} character
Section B: 8 bars, K:{key_b}, slightly contrasting character, "mp"
Section A': 8 bars, K:{key}, return to A character, "pp", embellished — must differ from A
Coda: 4 bars, "pppp", dissolving, stepwise descent to silence

{style}

══ ABSOLUTE RULES — VIOLATING THESE WILL BREAK THE OUTPUT ══

RULE 1 — MELODY IS A SINGLE LINE:
One note at a time in Voice 1. Never two simultaneous notes.
WRONG: (G4 c4)  ← two notes, this is a chord ✗
CORRECT: G3 A B2 c2  ← single line moving note by note ✓

RULE 2 — BAR LENGTH = EXACTLY 8 UNITS (L:1/8, M:4/4):
Count carefully: whole=8, half=4, quarter=2, dotted-quarter=3, eighth=1, sixteenth=0.5
CRITICAL: A alone = 1 unit (eighth note). A/ = 0.5 (sixteenth). Never use trailing slash.
WRONG: G3 A/ B2 c2 = 3+0.5+2+2 = 7.5 units ✗
CORRECT: G3 A B2 c2 = 3+1+2+2 = 8 units ✓

RULE 3 — ALL EXPRESSION MARKS REQUIRED:
"pp", "mp", "mf", "p", "pppp" (dynamics in double quotes before notes)
!crescendo(! and !crescendo)! — at least one per piece
!diminuendo(! and !diminuendo)! — at least one per piece
Slurs: (G3 A B2) over melodic phrases — group 3-6 notes
!trill! on at least one note in Section A'
!fermata! on the peak note of Section A', bar 4

RULE 4 — RHYTHM MUST VARY:
Never write all quarter notes (all 2-unit notes). Mix note lengths.
WRONG: G2 A2 B2 c2  ← all quarters, sounds mechanical ✗
CORRECT: G3 A B2 c2  ← dotted + eighth + quarter + quarter ✓

RULE 5 — CODA DESCENDS:
Melody must step downward bar by bar and end on a whole note: C8 or c8

Output ONLY the ABC notation. No explanation. No markdown. Start with X:1."""


def call_deepseek(messages, system=None, temperature=0.7, max_tokens=3000):
    payload = {
        "model": "deepseek-chat",
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens
    }
    if system:
        payload["messages"] = [{"role":"system","content":system}] + messages
    r = requests.post(
        "https://api.deepseek.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                 "Content-Type": "application/json"},
        json=payload, timeout=90
    )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


def clean_abc(abc_text):
    lines = []
    for line in abc_text.split('\n'):
        if line.strip().startswith('```'): continue
        if '%%MIDI pedal' in line: continue  # abc2midi doesn't support this
        lines.append(line)
    return '\n'.join(lines)


def abc_to_mp3(abc_text):
    with tempfile.TemporaryDirectory() as d:
        abc_f = os.path.join(d,'piece.abc')
        mid_f = os.path.join(d,'piece.mid')
        wav_f = os.path.join(d,'piece.wav')
        mp3_f = os.path.join(d,'piece.mp3')

        with open(abc_f,'w') as f:
            f.write(clean_abc(abc_text))

        r = subprocess.run(['abc2midi', abc_f,'-o',mid_f],
                          capture_output=True, text=True, timeout=30)
        if not os.path.exists(mid_f):
            raise RuntimeError(f"abc2midi: {r.stderr[:300]}")

        r = subprocess.run(['fluidsynth','-ni','-F',wav_f,'-r','44100',
                           SOUNDFONT, mid_f],
                          capture_output=True, text=True, timeout=60)
        if not os.path.exists(wav_f):
            raise RuntimeError(f"fluidsynth: {r.stderr[:300]}")

        # Apply subtle reverb (concert hall ambience) before encoding
        wav_reverb = os.path.join(d, 'piece_reverb.wav')
        sox_result = subprocess.run([
            'sox', wav_f, wav_reverb,
            'reverb', '25',   # reverb amount — subtle, not washed out
            '50',             # HF damping — soften high end slightly
            '80',             # room scale — medium hall
            '100',            # stereo depth
            '0.1',            # pre-delay ms
        ], capture_output=True, text=True, timeout=30)
        render_wav = wav_reverb if os.path.exists(wav_reverb) else wav_f

        r = subprocess.run(['lame','-b','192','-q','2', render_wav, mp3_f],
                          capture_output=True, text=True, timeout=30)
        if not os.path.exists(mp3_f):
            raise RuntimeError(f"lame: {r.stderr[:300]}")

        with open(mp3_f,'rb') as f:
            return base64.b64encode(f.read()).decode()


@app.route('/')
def index():
    return send_from_directory('.','index.html')

@app.route('/compose', methods=['POST'])
def compose():
    data = request.json or {}
    prompt = data.get('prompt','').strip()
    if not prompt:
        return jsonify({'error':'No prompt provided'}), 400
    try:
        # Confucius interprets
        raw = call_deepseek([{"role":"user","content":prompt}],
                           system=CONFUCIUS_SYSTEM, temperature=0.5)
        json_text = re.sub(r'```json|```','',raw).strip()
        interp = json.loads(json_text)

        composer = interp.get('composer','Chopin')
        key      = interp.get('key','Cm')
        tempo    = interp.get('tempo', 66)
        mood     = interp.get('mood','reflective')
        note     = interp.get('programme_note','')

        # Compose
        brief = build_brief(composer, key, tempo, mood)
        abc = call_deepseek([{"role":"user","content":brief}],
                           temperature=0.6, max_tokens=3000)
        abc = re.sub(r'```abc|```','',abc).strip()

        # Render
        mp3 = abc_to_mp3(abc)

        return jsonify({
            'abc': abc, 'mp3': mp3,
            'composer': composer, 'key': key,
            'tempo': tempo, 'mood': mood,
            'programme_note': note
        })

    except json.JSONDecodeError:
        return jsonify({'error':'Confucius could not interpret that prompt',
                       'raw': raw}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
