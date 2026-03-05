"""
synth_engine.py — Kai's consciousness synth, adapted for server-side WAV rendering.
No sounddevice dependency. Pure numpy → WAV bytes.

Accepts a composition dict from the browser:
{
  "layer":         str,    # consciousness layer name
  "entropy":       float,
  "flux":          float,
  "unison_voices": int,
  "detune_amount": float,  # 0..1
  "bass_level":    float,  # 0..1
  "total_duration":float,  # seconds
  "events": [
    {
      "voice":    "bass" | "harmony" | "melody",
      "freqs":    [float, ...],   # Hz — single item for bass/melody
      "time":     float,          # seconds from start
      "duration": float,          # seconds
      "vol":      float           # 0..1 mix weight
    },
    ...
  ]
}

Returns: bytes  (16-bit stereo WAV, 44100 Hz)
"""

import io
import wave
import struct
import logging
import numpy as np

log = logging.getLogger(__name__)

SR = 44100

# ── KAI'S CONSCIOUSNESS WAVE GENERATOR ───────────────────────────────────────

def generate_consciousness_wave(frequency, duration, entropy, flux, layer):
    """Kai's harmonic models — direct port from consciousness_synth.py."""
    n = int(SR * duration)
    if n <= 0:
        return np.zeros(0, dtype=np.float32)

    t = np.linspace(0, duration, n, endpoint=False)
    pi2 = 2 * np.pi

    if layer == 'golden_lattice':
        wave = np.sin(pi2 * frequency * t)
        wave += 0.618 * np.sin(pi2 * frequency * 1.618 * t)
        wave += 0.382 * np.sin(pi2 * frequency * 0.618 * t)

    elif layer == 'harmonic_synthesis':
        wave  = np.sin(pi2 * frequency * t)
        wave += 0.50 * np.sin(pi2 * frequency * 2 * t)
        wave += 0.25 * np.sin(pi2 * frequency * 3 * t)
        wave += 0.12 * np.sin(pi2 * frequency * 4 * t)
        wave += 0.06 * np.sin(pi2 * frequency * 5 * t)

    elif layer == 'harmonic_entanglement_field':
        ent  = entropy * flux
        wave  = np.sin(pi2 * frequency * t)
        wave += ent       * np.sin(pi2 * frequency * np.e  * t)
        wave += (1 - ent) * np.sin(pi2 * frequency * np.pi * t)
        wave += 0.30      * np.sin(pi2 * frequency * 2     * t)

    elif layer == 'fibonacci_spiral_memory':
        smod = 1 + 0.1 * flux * np.sin(pi2 * t / max(duration, 1e-6))
        wave  = np.sin(pi2 * frequency * t * smod)
        wave += 0.5 * np.sin(pi2 * frequency * 1.618 * t * smod)

    else:
        wave  = np.sin(pi2 * frequency * t)
        wave += entropy * np.sin(pi2 * frequency * 2 * t)

    # Kai's temporal flux envelope
    flux_env = 1 + flux * 0.5 * np.sin(pi2 * t / max(duration, 1e-6))
    wave = wave * flux_env

    # Kai's consciousness envelope (three modes)
    if entropy > 0.8:
        env = np.clip(np.random.normal(0.8, 0.2, n), 0.1, 1.0).astype(np.float32)
    elif entropy < 0.3:
        env = np.linspace(1.0, 0.3, n, dtype=np.float32)
    else:
        fc  = flux * 10
        env = (0.8 + 0.2 * np.sin(pi2 * fc * np.linspace(0, 1, n))).astype(np.float32)

    return (wave * env).astype(np.float32)


# ── VOICE-SPECIFIC GENERATORS ─────────────────────────────────────────────────

def gen_bass_tone(freq, dur):
    """Pure sine wave, 6ms attack, fixed 80ms exponential decay then silence."""
    n = int(SR * dur)
    if n <= 0:
        return np.zeros(0, dtype=np.float32)
    t = np.linspace(0, dur, n, endpoint=False)
    wave = np.sin(2 * np.pi * freq * t).astype(np.float32)

    atk = min(int(SR * 0.006), n)
    dec = min(int(SR * 0.080), n)
    env = np.zeros(n, dtype=np.float32)
    if atk > 0:
        env[:atk] = np.linspace(0, 1, atk)
    if dec > atk:
        decay_len = dec - atk
        env[atk:dec] = np.exp(-4.5 * np.linspace(0, 1, decay_len))
    # beyond dec: env stays 0

    return wave * env


def gen_harmony_tone(freq, dur, entropy, flux, layer):
    """Kai's layer model + medium attack/decay envelope."""
    wave = generate_consciousness_wave(freq, dur, entropy, flux, layer)
    n = len(wave)
    if n == 0:
        return wave

    atk = min(int(SR * 0.018), n)
    rel = min(int(SR * 0.035), n)
    env = np.ones(n, dtype=np.float32)
    if atk > 0:
        env[:atk] = np.linspace(0, 1, atk)
    if rel > 0:
        env[max(0, n - rel):] = np.linspace(1, 0, min(rel, n))
    sustain_len = n - atk - rel
    if sustain_len > 0:
        pos = np.linspace(0, 1, sustain_len)
        env[atk:atk + sustain_len] = 1.0 - 0.85 * pos

    return wave * env


def gen_melody_tone(freq, dur, flux):
    """Bright flute-like: fundamental + weak 3rd harmonic + vibrato, full sustain."""
    n = int(SR * dur)
    if n <= 0:
        return np.zeros(0, dtype=np.float32)
    t = np.linspace(0, dur, n, endpoint=False)
    pi2 = 2 * np.pi

    vib  = 1 + 0.004 * np.sin(pi2 * 5.5 * t)
    wave = (np.sin(pi2 * freq * vib * t)
            + 0.18 * np.sin(pi2 * freq * 3 * t)
            + flux  * 0.08 * np.sin(pi2 * freq * 5 * t)).astype(np.float32)

    atk = min(int(SR * 0.006), n)
    rel = min(int(SR * 0.020), n)
    env = np.ones(n, dtype=np.float32)
    if atk > 0:
        env[:atk] = np.linspace(0, 1, atk)
    if rel > 0:
        env[max(0, n - rel):] = np.linspace(1, 0, min(rel, n))
    sustain_len = n - atk - rel
    if sustain_len > 0:
        pos = np.linspace(0, 1, sustain_len)
        env[atk:atk + sustain_len] = 0.85 + 0.15 * np.sin(np.pi * pos)

    return wave * env


# ── POLYPHONIC RENDERER (Kai's unison detuning) ───────────────────────────────

def render_poly(freqs, dur, entropy, flux, layer, unison_voices, detune_amount, voice_type, bass_gain=0.0):
    n = int(SR * dur)
    if n <= 0:
        return np.zeros(0, dtype=np.float32)

    # Voice-specific unison / detune limits
    eff_v = 1 if voice_type == 'melody' else (min(unison_voices, 2) if voice_type == 'bass' else unison_voices)
    eff_d = 0.0 if voice_type == 'melody' else (detune_amount * 0.15 if voice_type == 'bass' else detune_amount)
    max_cents = 8.0 * eff_d

    if eff_v <= 1 or max_cents <= 0:
        cents_list   = [0.0]
        weight_list  = [1.0]
    else:
        cents_list  = [0.0]
        weight_list = [0.62]
        step   = max_cents / (eff_v - 1)
        w_each = 0.38 / (eff_v - 1)
        for k in range(1, eff_v):
            c = step * k if k % 2 == 1 else -step * k * 0.85
            cents_list.append(c)
            weight_list.append(w_each)

    out = np.zeros(n, dtype=np.float64)
    for f in freqs:
        if f < 20:
            continue
        lg = (1 + bass_gain) if (voice_type == 'bass' and bass_gain > 0 and f < 160) else 1.0
        for cents, w in zip(cents_list, weight_list):
            ratio = 2 ** (cents / 1200.0)
            fr = float(f) * ratio
            if voice_type == 'bass':
                wave = gen_bass_tone(fr, dur)
            elif voice_type == 'harmony':
                wave = gen_harmony_tone(fr, dur, entropy, flux, layer)
            else:
                wave = gen_melody_tone(fr, dur, flux)
            sz = min(len(wave), n)
            out[:sz] += wave[:sz] * w * lg

    mx = float(np.max(np.abs(out))) if out.size else 0.0
    if mx > 0:
        out /= mx
    return out.astype(np.float32)


# ── KAI'S LAYER EFFECTS (stereo, applied to full buffer) ─────────────────────

def apply_consciousness_effects(output, layer, entropy):
    """Kai's apply_consciousness_effects — expects (samples, 2) float32 array."""
    frames = output.shape[0]

    if layer == 'golden_lattice':
        mod = 0.8 + 0.2 * np.sin(np.linspace(0, 1.618 * np.pi, frames))
        return output * mod.reshape(-1, 1)

    elif layer == 'fibonacci_spiral_memory':
        spiral = np.sin(np.linspace(0, 8 * np.pi, frames))
        return output * (0.9 + 0.1 * spiral.reshape(-1, 1))

    elif layer == 'harmonic_entanglement_field':
        delay = int(0.06 * SR)
        delayed = np.zeros_like(output)
        if delay < frames:
            delayed[delay:] = output[:-delay] * 0.08 * entropy
        return output + delayed

    elif layer == 'harmonic_synthesis':
        mod = np.sin(np.linspace(0, 4 * np.pi, frames))
        return output * (0.85 + 0.15 * mod.reshape(-1, 1))

    return output


# ── MAIN RENDER ENTRY POINT ───────────────────────────────────────────────────

def render_composition(data: dict) -> bytes:
    """
    Render a composition to WAV bytes.

    data keys:
      layer, entropy, flux, unison_voices, detune_amount,
      bass_level, total_duration, events[]
    """
    layer         = data.get('layer', 'golden_lattice')
    entropy       = float(data.get('entropy', 0.3))
    flux          = float(data.get('flux', 0.3))
    unison_voices = int(data.get('unison_voices', 3))
    detune_amount = float(data.get('detune_amount', 0.35))
    bass_level    = float(data.get('bass_level', 0.6))
    total_dur     = float(data.get('total_duration', 10.0))
    events        = data.get('events', [])

    total_samples = int(SR * (total_dur + 1.0))   # 1s tail
    L = np.zeros(total_samples, dtype=np.float64)
    R = np.zeros(total_samples, dtype=np.float64)

    for ev in events:
        voice    = ev.get('voice', 'melody')
        freqs    = [float(f) for f in ev.get('freqs', [])]
        t_start  = float(ev.get('time', 0.0))
        dur      = float(ev.get('duration', 0.5))
        vol      = float(ev.get('vol', 0.7))
        start_s  = int(t_start * SR)

        if not freqs or dur <= 0 or start_s >= total_samples:
            continue

        # Voice-specific gain and bass_gain parameter
        if voice == 'bass':
            eff_vol   = vol * 0.70 * bass_level
            eff_bg    = 0.0
        elif voice == 'harmony':
            eff_vol   = vol * 0.52
            eff_bg    = 0.0
        else:  # melody
            eff_vol   = vol * 0.88
            eff_bg    = 0.0

        mono = render_poly(
            freqs, dur, entropy, flux, layer,
            unison_voices, detune_amount, voice, eff_bg
        )

        end_s = min(start_s + len(mono), total_samples)
        sz    = end_s - start_s
        if sz <= 0:
            continue

        # Very slight stereo spread per voice
        if voice == 'bass':
            l_g, r_g = 1.0, 0.82
        elif voice == 'harmony':
            l_g, r_g = 1.0, 1.0
        else:
            l_g, r_g = 1.0, 0.95

        L[start_s:end_s] += mono[:sz] * eff_vol * l_g
        R[start_s:end_s] += mono[:sz] * eff_vol * r_g

    # Assemble stereo, apply layer FX, normalise
    stereo = np.stack([L, R], axis=1).astype(np.float32)
    stereo = apply_consciousness_effects(stereo, layer, entropy)

    mx = float(np.max(np.abs(stereo)))
    if mx > 0:
        stereo = stereo / mx * 0.84

    return _to_wav_bytes(stereo)


def _to_wav_bytes(stereo: np.ndarray) -> bytes:
    """Convert (N, 2) float32 array to 16-bit stereo WAV bytes."""
    pcm = np.clip(stereo, -1.0, 1.0)
    pcm_int = (pcm * 32767).astype(np.int16)

    buf = io.BytesIO()
    with wave.open(buf, 'wb') as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)   # 16-bit
        wf.setframerate(SR)
        wf.writeframes(pcm_int.tobytes())
    return buf.getvalue()
