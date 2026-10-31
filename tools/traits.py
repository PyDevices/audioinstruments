# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Measure an instrument's traits from a render of a fixed phrase, and check them.

    python tools/traits.py poly106            # measure and compare with tests/traits/poly106.json
    python tools/traits.py poly106 --accept   # measure and store the values as accepted
    python tools/traits.py poly106 --show     # print every trait

    python tools/traits.py --reference af2894 4 --phrase keys --show
    python tools/traits.py --reference af2894 4 --phrase keys --vs electric_piano:0

The second form measures a SoundFont preset (a bank by the start of its md5,
then the preset number) with the same phrase as an instrument's run, played
through ``vrack.soundfont``, and writes the same traits under ``ref.``. With
``--vs NAME[:PATCH]`` it then prints how the instrument's accepted traits
differ from the reference's. See "A SoundFont as the reference" below.

An instrument's traits are numbers read off its own render: for each note of
the phrase, its pitch (cents from equal temperament), its spectrum (centroid
and the first harmonics against the fundamental), its RMS envelope (attack,
decay, sustain level and release) and its stereo correlation; across
velocities, how level and brightness follow the key; and the noise floor
once everything has died away. The accepted values live in
``tests/traits/<name>.json`` with a tolerance for each, and
``tests/test_traits.py`` renders the phrase again and checks every one.

Nothing here says what an instrument should sound like. A trait file
records what it did sound like when someone listened and accepted it, so a
change that moves the sound shows up as a list of traits that moved. If
the move is wanted, accept the new values and say so in the commit.

A drum instrument, or a kit, is measured with a drum phrase instead: every
GM drum note it plays, struck at three velocities and left to ring until it
is silent, with traits per note (see "Drums" below).

Every instrument in ``vrack.adapter.ALL`` can have a spec in ``SPECS``:
which of its patches to play, which notes and velocities, and how long to
hold and let ring, since a pad needs longer than a pluck. A spec's
``controls`` maps a patch to controls set after its program change (names
and values as its ``set_control`` takes them), to hold still what would
otherwise move, such as a rotary speaker. CPython only (it uses numpy's
FFT).
"""

import argparse
import contextlib
import hashlib
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if os.path.join(ROOT, "lib") not in sys.path:
    sys.path.insert(0, os.path.join(ROOT, "lib"))

import audiocore  # noqa: E402
import vrack.adapter as adapter  # noqa: E402
from vrack.soundfont import PERCUSSION_BANK, open_bank  # noqa: E402

try:
    from .traits_phrase import BUFFER, SAMPLE_RATE, phrase  # noqa: F401
except ImportError:  # run as a script
    from traits_phrase import BUFFER, SAMPLE_RATE, phrase  # noqa: F401

TRAITS_DIR = os.path.join(ROOT, "tests", "traits")
#: The RMS envelope is read every 2 ms, over a window of two periods of the
#: note's fundamental, kept between 5 and 60 ms.
FRAME = 96
WINDOW_MS = (5.0, 60.0)
SILENT_DB = -120.0

#: A trait is accepted only if it holds still when the instrument is bent this
#: far off centre, either way (14-bit MIDI; three steps of a two-semitone range
#: is about a count on the pitch wire), and when every wire truncates instead of
#: rounding. Two detuned oscillators beat, and a count of tuning moves the
#: beating inside the measuring window: decay times and harmonic levels taken
#: there would fail on any change that touches rounding.
BEND_CENTRE = 8192
NUDGES = (BEND_CENTRE + 3, BEND_CENTRE - 3)

#: Per instrument: the patches played, the notes of the range at
#: ``velocity``, the velocities played on ``velocity_note``, and seconds held
#: and left to ring after each note. A spec with an ``engine`` measures that
#: form of ``instrument`` (the Poly106's graph), rendered here when this
#: Python's audiodsp has the engine's module (``audiograph``), and otherwise
#: under the interpreter ``VRACK_MICROPYTHON`` names (or ``micropython`` on
#: the path).
SPECS = {
    "mono101": {
        "patches": (0, 1, 2, 4, 6, 7),
        "notes": (36, 60, 84),
        "velocity": 100,
        "velocities": (32, 80, 127),
        "velocity_note": 60,
        "hold": 0.5,
        "ring": 0.6,
        "tail": 0.3,
    },
    "mono_synth": {
        "patches": (0, 1, 2, 3, 4, 9),
        "notes": (36, 60, 84),
        "velocity": 100,
        "velocities": (32, 80, 127),
        "velocity_note": 60,
        "hold": 0.5,
        "ring": 0.6,
        "tail": 0.3,
    },
    "poly106": {
        "patches": (0, 1, 3, 5, 9),
        "notes": (36, 60, 84),
        "velocity": 100,
        "velocities": (32, 80, 127),
        "velocity_note": 60,
        "hold": 0.5,
        "ring": 0.6,
        "tail": 0.3,
    },
    "poly106_graph": {
        "instrument": "poly106",
        "engine": "graph",
        "patches": (0, 1, 3, 5, 9),
        "notes": (36, 60, 84),
        "velocity": 100,
        "velocities": (32, 80, 127),
        "velocity_note": 60,
        "hold": 0.5,
        "ring": 0.6,
        "tail": 0.3,
    },
    "poly5": {
        "patches": (0, 1, 2, 4, 5, 7),
        "notes": (36, 60, 84),
        "velocity": 100,
        "velocities": (32, 80, 127),
        "velocity_note": 60,
        "hold": 0.5,
        "ring": 0.6,
        "tail": 0.3,
    },
    "poly6": {
        "patches": (0, 2, 4, 6, 7),
        "notes": (36, 60, 84),
        "velocity": 100,
        "velocities": (32, 80, 127),
        "velocity_note": 60,
        "hold": 0.5,
        "ring": 0.6,
        "tail": 0.3,
    },
    "poly8": {
        "patches": (0, 2, 5, 6, 7),
        "notes": (36, 60, 84),
        "velocity": 100,
        "velocities": (32, 80, 127),
        "velocity_note": 60,
        "hold": 0.5,
        "ring": 0.6,
        "tail": 0.3,
    },
    "polya6": {
        "patches": (0, 1, 2, 5, 9),
        "notes": (36, 60, 84),
        "velocity": 100,
        "velocities": (32, 80, 127),
        "velocity_note": 60,
        "hold": 0.5,
        "ring": 0.6,
        "tail": 0.3,
    },
    "polyxa": {
        "patches": (0, 1, 2, 5, 6),
        "notes": (36, 60, 84),
        "velocity": 100,
        "velocities": (32, 80, 127),
        "velocity_note": 60,
        "hold": 0.5,
        "ring": 0.6,
        "tail": 0.3,
    },
    "bass_pedals": {
        "patches": (1, 2, 3, 5, 10),
        "notes": (36, 41, 43, 48),
        "velocity": 100,
        "velocities": (32, 80, 127),
        "velocity_note": 43,
        "hold": 0.8,
        "ring": 1.0,
        "tail": 0.5,
    },
    "poly80": {
        "patches": (0, 1, 5, 6, 7),
        "notes": (36, 60, 84),
        "velocity": 100,
        "velocities": (32, 80, 127),
        "velocity_note": 60,
        "hold": 0.5,
        "ring": 0.6,
        "tail": 0.3,
    },
    "duosynth": {
        "patches": (0, 1, 3, 5, 6),
        "notes": (36, 60, 84),
        "velocity": 100,
        "velocities": (32, 80, 127),
        "velocity_note": 60,
        "hold": 0.5,
        "ring": 0.6,
        "tail": 0.3,
    },
    "clavichord": {
        "patches": (0, 1, 2, 3, 4, 6),
        "notes": (36, 48, 60, 72, 84),
        "velocity": 100,
        "velocities": (32, 80, 127),
        "velocity_note": 60,
        "hold": 1.0,
        "ring": 1.0,
        "tail": 0.3,
    },
    "electric_grand70": {
        "patches": (0, 1, 2, 3, 4, 5),
        "notes": (36, 48, 60, 72, 84),
        "velocity": 100,
        "velocities": (32, 80, 127),
        "velocity_note": 60,
        "hold": 1.0,
        "ring": 1.0,
        "tail": 0.3,
    },
    "electric_piano": {
        "patches": (0, 1, 2, 3, 4, 6),
        "notes": (36, 48, 60, 72, 84),
        "velocity": 100,
        "velocities": (32, 80, 127),
        "velocity_note": 60,
        "hold": 1.0,
        "ring": 1.0,
        "tail": 0.3,
    },
    "reed_piano": {
        "patches": (0, 1, 2, 3, 4, 5),
        "notes": (36, 48, 60, 72, 84),
        "velocity": 100,
        "velocities": (32, 80, 127),
        "velocity_note": 60,
        "hold": 1.0,
        "ring": 1.0,
        "tail": 0.3,
    },
    "reed_piano200a": {
        "patches": (0, 1, 2, 3, 4, 6),
        "notes": (36, 48, 60, 72, 84),
        "velocity": 100,
        "velocities": (32, 80, 127),
        "velocity_note": 60,
        "hold": 1.0,
        "ring": 1.0,
        "tail": 0.3,
    },
    "string_ensemble": {
        "patches": (0, 1, 3, 5, 8),
        "notes": (36, 60, 84),
        "velocity": 100,
        "velocities": (32, 80, 127),
        "velocity_note": 60,
        "hold": 1.5,
        "ring": 1.0,
        "tail": 0.3,
    },
    "vocoder330": {
        "patches": (1, 3, 4, 8),
        "notes": (48, 60, 84),
        "velocity": 100,
        "velocities": (32, 80, 127),
        "velocity_note": 60,
        "hold": 1.5,
        "ring": 2.0,
        "tail": 0.3,
    },
    "tonewheel3": {
        "patches": (0, 1, 2, 5, 6, 7),
        # the speaker stopped and the scanner off, so a held note holds still;
        # Rock Drive and Full Organ keep both running
        "controls": {
            0: {"rotary": "stop", "vibrato": False},
            1: {"rotary": "stop", "vibrato": False},
            5: {"rotary": "stop", "vibrato": False},
            7: {"rotary": "stop", "vibrato": False},
        },
        "notes": (36, 48, 60, 72, 84),
        "velocity": 100,
        "velocities": (32, 80, 127),
        "velocity_note": 60,
        "hold": 1.5,
        "ring": 0.5,
        "tail": 0.3,
    },
    "combo_organ": {
        "patches": (0, 1, 2, 3, 4, 5),
        "controls": {
            0: {"vibrato": False},
            2: {"vibrato": False},
            3: {"vibrato": False},
            5: {"vibrato": False},
        },
        "notes": (36, 48, 60, 72, 84),
        "velocity": 100,
        "velocities": (32, 80, 127),
        "velocity_note": 60,
        "hold": 1.5,
        "ring": 0.5,
        "tail": 0.3,
    },
    "compact_organ": {
        "patches": (0, 1, 2, 3, 4, 5),
        "controls": {
            2: {"vibrato": False},
            3: {"vibrato": False},
            4: {"vibrato": False},
            5: {"vibrato": False},
        },
        "notes": (36, 48, 60, 72, 84),
        "velocity": 100,
        "velocities": (32, 80, 127),
        "velocity_note": 60,
        "hold": 1.5,
        "ring": 0.5,
        "tail": 0.3,
    },
    "rhythm606": {
        "patches": (0, 1),
        "drums": True,
        "notes": (36, 38, 41, 48, 49, 46, 42),
        "velocity": 100,
        "velocities": (40, 100, 127),
        "ring": 10.0,
        "tail": 0.3,
    },
    "rhythm808": {
        "patches": (0, 1),
        "drums": True,
        "notes": (36, 37, 38, 39, 42, 46, 41, 45, 48, 49, 56, 62, 63, 64, 75, 70),
        "velocity": 100,
        "velocities": (40, 100, 127),
        "ring": 10.0,
        "tail": 0.3,
    },
    "rhythm909": {
        "patches": (0, 1),
        "drums": True,
        "notes": (36, 37, 38, 39, 42, 46, 41, 45, 48, 49, 51),
        "velocity": 100,
        "velocities": (40, 100, 127),
        "ring": 10.0,
        "tail": 0.3,
    },
}

#: Phrases for a reference that has no instrument spec of its own yet: the
#: same keys as a spec, without ``patches``. A Phase 2 instrument copies the
#: phrase of its family into its spec, so its reference can be measured with
#: exactly the notes it is measured with.
PHRASES = {
    # electric pianos, clavinet and other plucked or struck keys: a long hold
    # and a long ring, since the note dies away by itself
    "keys": {
        "notes": (36, 48, 60, 72, 84),
        "velocity": 100,
        "velocities": (32, 80, 127),
        "velocity_note": 60,
        "hold": 1.0,
        "ring": 1.0,
        "tail": 0.3,
    },
    # an organ: held notes that do not decay until release
    "organ": {
        "notes": (36, 48, 60, 72, 84),
        "velocity": 100,
        "velocities": (32, 80, 127),
        "velocity_note": 60,
        "hold": 1.5,
        "ring": 0.5,
        "tail": 0.3,
    },
    # a drum kit: every note the kit plays (None: ask the kit), struck at three
    # velocities, the key held until the sound is silent or ``ring`` seconds have
    # passed (a cymbal, an 808 kick)
    "drums": {
        "drums": True,
        "notes": None,
        "velocity": 100,
        "velocities": (40, 100, 127),
        "ring": 10.0,
        "tail": 0.3,
    },
}

#: Tolerance by kind of trait: an absolute amount, a fraction of the value,
#: and the least the tolerance may be.
TOLERANCE = {
    "cents": (3.0, 0.0, 3.0),
    "db": (1.0, 0.0, 1.0),
    "harmonic_db": (1.5, 0.0, 1.5),
    "hz": (0.0, 0.05, 20.0),
    "ms": (0.0, 0.15, 6.0),
    "corr": (0.05, 0.0, 0.05),
    "floor_db": (6.0, 0.0, 6.0),
    # drums
    "band_db": (2.0, 0.0, 2.0),
    "ratio_db": (3.0, 0.0, 3.0),
    "pitch_hz": (0.0, 0.03, 1.0),
    "drop_cents": (0.0, 0.2, 50.0),
    "ms_long": (0.0, 0.25, 30.0),
}


def _db(x):
    return 20.0 * math.log10(x) if x > 1e-9 else SILENT_DB


def note_hz(note):
    return 440.0 * 2.0 ** ((note - 69) / 12.0)


# -- the phrase -----------------------------------------------------------------


def play(inst, spec, bend=BEND_CENTRE):
    """Play the phrase on ``inst`` (anything with the component contract and an
    ``output`` to pull): (stereo float array, latency in frames, events)."""
    if bend != BEND_CENTRE:
        inst.pitch_bend(bend)
    events, length = phrase(spec)
    todo = []
    for on, off, note, velocity in events:
        todo.append((on, 1, note, velocity))
        todo.append((off, 0, note, 0))
    todo.sort()
    buffers = length // BUFFER
    out = np.zeros((buffers * BUFFER, 2), dtype=np.float64)
    k = 0
    for b in range(buffers):
        start = b * BUFFER
        while k < len(todo) and todo[k][0] < start + BUFFER:
            frame, on, note, velocity = todo[k]
            if on:
                inst.note_on(note, velocity, sample_position=frame - start)
            else:
                inst.note_off(note, sample_position=frame - start)
            k += 1
        _, data = audiocore.get_buffer(inst.output)
        pcm = np.frombuffer(bytes(data), dtype=np.int16).reshape(-1, 2)
        out[start : start + BUFFER] = pcm / 32768.0
    return out, inst.latency_samples, events


def create_instrument(name):
    """A fresh instrument ``name`` whose output can be pulled (a sampler's always can).

    The rack, always: a spec without an ``engine`` measures the rack, and
    ``create()``'s default would take a patch's graph form wherever audiodsp
    has ``audiograph``."""
    if name in adapter.SAMPLERS:
        return adapter.create(SAMPLE_RATE, voice=name)
    return adapter.create(SAMPLE_RATE, voice=name, output="pull", engine="rack")


_ENGINE_MODULES = {"graph": "audiograph"}
_interpreters = {}


def render_here(engine="graph"):
    """True when this interpreter can render a spec with ``engine`` itself."""
    try:
        __import__(_ENGINE_MODULES[engine])
    except ImportError:
        return False
    return True


def can_render(engine="graph"):
    """True when a spec with ``engine`` can be rendered, here or under MicroPython."""
    return render_here(engine) or render_interpreter(engine) is not None


def render_interpreter(engine="graph"):
    """The MicroPython that renders a spec with ``engine`` (``VRACK_MICROPYTHON``, or
    ``micropython`` on the path), or None when there is none or it lacks the module."""
    interpreter = os.environ.get("VRACK_MICROPYTHON") or shutil.which("micropython")
    if not interpreter:
        return None
    key = (interpreter, engine)
    if key not in _interpreters:
        probe = subprocess.run(
            [interpreter, "-c", "import %s" % _ENGINE_MODULES[engine]], capture_output=True
        )
        _interpreters[key] = interpreter if probe.returncode == 0 else None
    return _interpreters[key]


def render_outside(spec, patch):
    """Play the phrase under the interpreter that has the spec's engine
    (``tools/traits_render.py``): (stereo float array, latency, events)."""
    interpreter = render_interpreter(spec["engine"])
    if not interpreter:
        raise RuntimeError(
            "the %s %s form needs audiodsp with audiograph, or a MicroPython with it:"
            " set VRACK_MICROPYTHON" % (spec["instrument"], spec["engine"])
        )
    events, _ = phrase(spec)
    fd, path = tempfile.mkstemp(suffix=".pcm")
    os.close(fd)
    try:
        ran = subprocess.run(
            [
                interpreter,
                os.path.join(HERE, "traits_render.py"),
                spec["instrument"],
                str(patch),
                spec["engine"],
                json.dumps(
                    {k: v for k, v in spec.items() if k not in ("patches", "engine", "instrument")}
                ),
                path,
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=600,
        )
        if ran.returncode:
            raise RuntimeError(
                "the render under %s failed:\n%s%s" % (interpreter, ran.stdout, ran.stderr)
            )
        latency = int(ran.stdout.strip().splitlines()[-1].split()[1])
        with open(path, "rb") as f:
            pcm = np.frombuffer(f.read(), dtype=np.int16).reshape(-1, 2)
    finally:
        os.unlink(path)
    return pcm / 32768.0, latency, events


def apply_controls(inst, spec, patch):
    """Set the controls the spec gives ``patch``, after its program change."""
    for control, value in spec.get("controls", {}).get(patch, {}).items():
        inst.patch.set_control(inst.voice_pool, control, value)


def render(name, patch, spec, bend=BEND_CENTRE):
    """Play the phrase on patch ``patch`` of a fresh instrument: (stereo float array, latency, events).

    ``bend`` is a MIDI pitch bend, sent before the phrase."""
    if spec.get("engine"):
        if not render_here(spec["engine"]):
            if bend != BEND_CENTRE:
                raise RuntimeError("a nudged render of the %s form runs here only" % spec["engine"])
            return render_outside(spec, patch)
        inst = adapter.create(
            SAMPLE_RATE,
            voice=spec["instrument"],
            engine=spec["engine"],
            output="pull",
            buffer_frames=BUFFER,
        )
        inst.program_change(patch)
        apply_controls(inst, spec, patch)
        try:
            return play(inst, spec, bend)
        finally:
            inst.deinit()
    inst = create_instrument(name)
    inst.program_change(patch)
    apply_controls(inst, spec, patch)
    try:
        return play(inst, spec, bend)
    finally:
        inst.deinit()


# -- measuring --------------------------------------------------------------------


def rms_envelope(x, f0):
    """RMS every FRAME samples, over a window two periods of ``f0`` long, centred."""
    lo, hi = WINDOW_MS
    window = int(SAMPLE_RATE * min(hi, max(lo, 2000.0 / f0)) / 1000.0)
    sq = np.concatenate(([0.0], np.cumsum(x * x)))
    centres = np.arange(0, len(x), FRAME)
    a = np.clip(centres - window // 2, 0, len(x))
    b = np.clip(centres + window // 2, 0, len(x))
    return np.sqrt(np.maximum(sq[b] - sq[a], 0.0) / window)


def spectrum(x):
    """Magnitude spectrum of x under a Hann window, zero-padded, and its bin width."""
    n = len(x)
    size = 1
    while size < 8 * n:
        size *= 2
    w = np.hanning(n)
    mag = np.abs(np.fft.rfft(x * w, size))
    return mag, SAMPLE_RATE / size


def _peak_near(mag, width, hz, span, strict=False):
    """The interpolated frequency and magnitude of the largest bin within ``hz`` x (1 +- span).

    The window may hold no peak, only the skirt of one that lies outside it: its
    largest bin sits beside a larger bin. The parabola through those three
    points then has its vertex somewhere else, often many bins away, so a skirt
    is not interpolated: its bin is returned as it is, the floor a harmonic that
    is absent reads as. With ``strict`` a skirt is no peak at all, ``(hz, 0.0)``,
    for a caller looking for a tone.
    """
    lo = max(1, int(hz * (1.0 - span) / width))
    hi = min(len(mag) - 2, int(hz * (1.0 + span) / width) + 1)
    if hi <= lo:
        return hz, 0.0
    i = lo + int(np.argmax(mag[lo:hi]))
    a, b, c = mag[i - 1], mag[i], mag[i + 1]
    if b <= 0.0:
        return hz, 0.0
    if a > b or c > b:
        return (hz, 0.0) if strict else (i * width, b)
    la, lb, lc = math.log(a + 1e-12), math.log(b), math.log(c + 1e-12)
    d = la - 2.0 * lb + lc
    shift = 0.5 * (la - lc) / d if d != 0.0 else 0.0
    shift = max(-0.5, min(0.5, shift))  # the 1e-12 floor on a and c can bend a tiny peak
    return (i + shift) * width, math.exp(lb - 0.25 * (la - lc) * shift)


def fundamental(mag, width, nominal):
    """The tone's fundamental: the lowest strong partial at the nominal pitch's octaves."""
    best = None
    top = float(np.max(mag))
    for octave in (-2, -1, 0, 1):
        hz = nominal * 2.0**octave
        if hz < 15.0:
            continue
        f, m = _peak_near(mag, width, hz, 0.03, strict=True)
        if m > top * 0.05 and (best is None or f < best[0]):
            best = (f, m)
    if best is None:
        return _peak_near(mag, width, nominal, 0.03)
    return best


def pitch(mag, width, f0):
    """The fundamental from the first four partials, each weighted by its level."""
    total = weight = 0.0
    for k in range(1, 5):
        if f0 * k > SAMPLE_RATE * 0.45:
            break
        f, m = _peak_near(mag, width, f0 * k, 0.02)
        total += m * f / k
        weight += m
    return total / weight if weight else f0


def note_traits(x, on, off, ring_end, note):
    """The traits of one note: x is mono, on/off/ring_end frames where its sound is."""
    traits = {}
    nominal = note_hz(note)
    start = on + SAMPLE_RATE // 100
    mag, width = spectrum(x[start:off])
    f0 = pitch(mag, width, fundamental(mag, width, nominal)[0])
    traits["pitch_cents"] = ("cents", 1200.0 * math.log2(f0 / nominal))
    env = rms_envelope(x[on:ring_end], f0)
    peak_i = int(np.argmax(env))
    peak = float(env[peak_i])
    traits["peak_db"] = ("db", _db(peak))
    held = (off - on) // FRAME
    rise = np.nonzero(env[: peak_i + 1] >= 0.9 * peak)[0]
    traits["attack_ms"] = (
        "ms",
        (int(rise[0]) if len(rise) else peak_i) * FRAME * 1000.0 / SAMPLE_RATE,
    )
    fall = np.nonzero(env[peak_i:held] < peak * 0.5)[0]
    decay = int(fall[0]) if len(fall) else held - peak_i
    traits["decay_ms"] = ("ms", decay * FRAME * 1000.0 / SAMPLE_RATE)
    at_off = float(np.mean(env[max(0, held - 5) : held]))
    traits["sustain_db"] = ("db", _db(at_off) - _db(peak) if peak > 0 else 0.0)
    after = np.nonzero(env[held:] < at_off * 0.1)[0]
    release = int(after[0]) if len(after) else len(env) - held
    traits["release_ms"] = ("ms", release * FRAME * 1000.0 / SAMPLE_RATE)

    # the spectrum, from the loudest stretch of the held part
    start = on + peak_i * FRAME
    stop = min(off, start + SAMPLE_RATE // 3)
    if stop - start < SAMPLE_RATE // 20:
        start, stop = on, off
    seg = x[start:stop]
    mag, width = spectrum(seg)
    freqs = np.arange(len(mag)) * width
    band = (freqs > 20.0) & (freqs < 20000.0)
    total = float(np.sum(mag[band]))
    traits["centroid_hz"] = ("hz", float(np.sum(freqs[band] * mag[band]) / total) if total else 0.0)
    _, m0 = _peak_near(mag, width, f0, 0.02)
    for h in range(2, 6):
        if f0 * h < SAMPLE_RATE * 0.45:
            _, mh = _peak_near(mag, width, f0 * h, 0.02)
            traits["h%d_db" % h] = ("harmonic_db", _db(mh) - _db(m0))
    return traits


def measure_render(stereo, latency, events, spec, prefix):
    """The traits of one rendered phrase, their keys starting with ``prefix``."""
    traits = {}
    mono = 0.5 * (stereo[:, 0] + stereo[:, 1])
    levels = []
    for index, (on, off, note, velocity) in enumerate(events):
        on += latency
        off += latency
        ring_end = events[index + 1][0] + latency if index + 1 < len(events) else len(mono)
        t = note_traits(mono, on, off, min(ring_end, len(mono)), note)
        if index < len(spec["notes"]):
            for key, value in t.items():
                traits["%sn%d.%s" % (prefix, note, key)] = value
            if note == spec["velocity_note"]:
                left, right = stereo[on:off, 0], stereo[on:off, 1]
                if np.std(left) > 0 and np.std(right) > 0:
                    traits[prefix + "lr_corr"] = ("corr", float(np.corrcoef(left, right)[0, 1]))
        else:
            levels.append((velocity, t["peak_db"][1], t["centroid_hz"][1]))
    loudest = max(levels)
    for velocity, level, centroid in levels:
        if velocity == loudest[0]:
            continue
        traits["%svel%d.level_db" % (prefix, velocity)] = ("db", level - loudest[1])
        traits["%svel%d.centroid_hz" % (prefix, velocity)] = ("hz", centroid)
    tail = mono[-int(spec["tail"] * SAMPLE_RATE * 0.5) :]
    traits[prefix + "noise_floor_db"] = ("floor_db", _db(float(np.sqrt(np.mean(tail * tail)))))
    return traits


def _truncating_cast(dst_i16, src, tmp):
    """The float-to-int16 cast, truncating: up to a count off on every wire."""
    from vrack.core.signal import BRIDGE_SCALE

    dst_i16[:] = np.clip(np.asarray(src, dtype=np.float64) * BRIDGE_SCALE, -32768.0, 32767.0)


@contextlib.contextmanager
def truncating():
    """Every module that casts to the wires truncates while this is open."""
    import vrack.core.bridge
    import vrack.core.graph
    import vrack.core.signal
    import vrack.dsp.ladder

    modules = (vrack.core.signal, vrack.core.bridge, vrack.core.graph, vrack.dsp.ladder)
    saved = [module.to_int16 for module in modules]
    for module in modules:
        module.to_int16 = _truncating_cast
    try:
        yield
    finally:
        for module, cast in zip(modules, saved):
            module.to_int16 = cast


def nudged(name):
    """``name`` measured bent each way of ``NUDGES``, and with truncating wires."""
    out = [measure(name, bend=bend) for bend in NUDGES]
    with truncating():
        out.append(measure(name))
    return out


def measure(name, spec=None, bend=BEND_CENTRE):
    """Every trait of ``name``: {trait: (kind, value)}, played under pitch bend ``bend``."""
    spec = spec or SPECS[name]
    traits = {}
    for patch in spec["patches"]:
        if spec.get("drums"):
            inst = create_instrument(name)
            try:
                inst.program_change(patch)
                traits.update(measure_drums(inst, spec, "p%d." % patch))
            finally:
                inst.deinit()
            continue
        stereo, latency, events = render(name, patch, spec, bend)
        traits.update(measure_render(stereo, latency, events, spec, "p%d." % patch))
    return traits


# -- drums -----------------------------------------------------------------------------
#
# A drum sound is not a held note: it is struck, rings by itself for a few
# milliseconds or several seconds, and has to be measured until it is silent.
# So the drum phrase is not on a fixed schedule. Each note of the spec is
# struck at each velocity in turn, the key is held (as a one-shot drum plays,
# whatever the gate) until the output has been silent for 50 ms or ``ring``
# seconds are up, and then let go. The traits are read off each strike by itself.
#
# Per note (``d<note>.``): the peak level at each velocity (``v40.peak_db``)
# and the spectral centroid at each (``v40.centroid_hz``); and from the strike
# at the spec's ``velocity``: the time from the loudest moment to the last
# moment within 20 and 40 dB of it (``decay20_ms``, ``decay40_ms``), the
# time from the strike to the last moment within 60 dB (``length_ms``), the
# centroid over the first half second, how that energy divides between below
# 200 Hz, 200 Hz to 2 kHz and above (``band_low_db`` and so on, each a share
# of the whole in dB), and the noise against the tone (``noise_tone_db``,
# negative for a tone, positive for noise). When the strike has a fundamental
# in 25 to 800 Hz, a strong tone carrying a fifth of the energy, a kick or a
# tom has: ``fundamental_hz`` and how far the pitch fell between 2-12 ms and
# 38-48 ms after its loudest moment (``pitch_drop_cents``, when the tone is
# still sounding). Across the phrase, the ``noise_floor_db`` after the last
# strike.

#: The keys a kit is asked about: General MIDI 2's percussion range.
DRUM_KEYS = range(27, 88)
#: Seconds of silence that end a strike, and the level below which it is silent.
QUIET_MS = 50
QUIET_PEAK = 1.3e-4
#: The span of a strike whose spectrum is read, in seconds.
SPECTRUM_SECONDS = 0.5
#: Band edges for the low/mid/high balance, in Hz.
BANDS = (("low", 20.0, 200.0), ("mid", 200.0, 2000.0), ("high", 2000.0, 20000.0))
TONE_BAND = (25.0, 800.0)


def kit_notes(font, bank_number, program, velocity=100):
    """The keys of the percussion range the preset has a zone for, at ``velocity``."""
    notes = []
    for key in DRUM_KEYS:
        try:
            if font.regions(bank_number, program, key, velocity):
                notes.append(key)
        except KeyError:
            break
    return tuple(notes)


def with_notes(inst, spec):
    """The spec with its notes filled in from ``inst``'s preset when it has none."""
    if spec.get("notes") is not None:
        return spec
    bank_number, program = inst.preset
    notes = kit_notes(inst.bank, bank_number, program, spec["velocity"])
    if not notes:
        raise LookupError(
            "the preset %d:%d has no zone in the percussion range" % (bank_number, program)
        )
    return dict(spec, notes=notes)


def drum_hits(inst, spec):
    """Strike each note at each velocity in turn and yield what comes out:
    (note, velocity, stereo array from the strike until silence, latency in
    frames), then (None, None, the silence after the last strike, 0)."""
    cap = int(round(spec["ring"] * SAMPLE_RATE / BUFFER))
    quiet = int(round(QUIET_MS * SAMPLE_RATE / 1000.0 / BUFFER))
    latency = inst.latency_samples
    # the instrument may delay its output: wait that long before judging silence
    wait = latency // BUFFER + 1

    def pull():
        _, data = audiocore.get_buffer(inst.output)
        return np.frombuffer(bytes(data), dtype=np.int16).reshape(-1, 2) / 32768.0

    for note in spec["notes"]:
        for velocity in spec["velocities"]:
            inst.note_on(note, velocity)
            blocks, silent = [], 0
            for b in range(cap):
                block = pull()
                blocks.append(block)
                silent = silent + 1 if float(np.max(np.abs(block))) < QUIET_PEAK else 0
                if silent >= quiet and b >= wait:
                    break
            inst.note_off(note)
            yield note, velocity, np.concatenate(blocks), latency
    tail = [pull() for _ in range(int(spec["tail"] * SAMPLE_RATE / BUFFER))]
    yield None, None, np.concatenate(tail), 0


def _tone_runs(power, width):
    """The tonal peaks of a power spectrum: [(first bin, last bin)] of the runs of bins
    standing well above the spectrum's local median, that have a bin 12 dB above it."""
    block = max(8, int(round(200.0 / width)))
    count = len(power) // block
    if count < 2:
        return []
    blocks = power[: count * block].reshape(count, block)
    centres = np.arange(count) * block + block / 2.0
    base = np.interp(np.arange(len(power)), centres, np.median(blocks, axis=1)) + 1e-18
    near = power > 4.0 * base
    edges = np.diff(np.concatenate(([0], near.astype(np.int8), [0])))
    runs = []
    for first, last in zip(np.nonzero(edges == 1)[0], np.nonzero(edges == -1)[0]):
        if np.max(power[first:last] / base[first:last]) >= 16.0:
            runs.append((int(first), int(last)))
    return runs


def _inst_freq(x, lo, hi):
    """Analytic signal of ``x`` limited to lo..hi Hz with soft edges."""
    n = len(x)
    size = 1
    while size < 2 * n:
        size *= 2
    spec = np.fft.rfft(x, size)
    freqs = np.arange(len(spec)) * SAMPLE_RATE / size
    gain = np.clip((freqs - lo * 0.7) / (lo * 0.3), 0.0, 1.0) * np.clip(
        (hi * 1.3 - freqs) / (hi * 0.3), 0.0, 1.0
    )
    full = np.zeros(size, dtype=complex)
    full[: len(spec)] = spec * gain * 2.0
    return np.fft.ifft(full)[:n]


def _weighted_freq(z, a, b):
    """The mean instantaneous frequency over samples a..b of an analytic signal, by power."""
    seg = z[a : b + 1]
    if len(seg) < 3:
        return None
    step = np.angle(seg[1:] * np.conj(seg[:-1])) * SAMPLE_RATE / (2.0 * math.pi)
    weight = np.abs(seg[1:]) ** 2
    return float(np.sum(step * weight) / np.sum(weight)) if np.sum(weight) > 0 else None


def strike_traits(x, f0_hint=None):
    """The detailed traits of one strike, mono: {name: (kind, value)}."""
    traits = {}
    count = int(SPECTRUM_SECONDS * SAMPLE_RATE)
    seg = np.zeros(count)
    seg[: min(count, len(x))] = x[:count]
    # the first half of a Hann window falling: the strike itself stays whole
    seg *= np.hanning(2 * count)[count:]
    size = 1
    while size < 2 * count:
        size *= 2
    mag = np.abs(np.fft.rfft(seg, size))
    width = SAMPLE_RATE / size
    power = mag * mag
    freqs = np.arange(len(mag)) * width
    inband = (freqs >= 20.0) & (freqs <= 20000.0)
    total = float(np.sum(power[inband]))
    magsum = float(np.sum(mag[inband]))
    traits["centroid_hz"] = (
        "hz",
        float(np.sum(freqs[inband] * mag[inband]) / magsum) if magsum else 0.0,
    )
    for name, lo, hi in BANDS:
        share = float(np.sum(power[(freqs >= lo) & (freqs < hi)])) / total if total else 0.0
        traits["band_%s_db" % name] = ("band_db", max(-60.0, 10.0 * math.log10(share + 1e-9)))

    # tone against noise: the runs of bins well above the local median are the tone
    runs = _tone_runs(power, width)
    tone = sum(
        float(np.sum(power[a:b])) for a, b in runs if freqs[a] >= 20.0 and freqs[b - 1] <= 20000.0
    )
    noise = max(total - tone, 0.0)
    ratio = 10.0 * math.log10((noise + 1e-12 * total) / (tone + 1e-12 * total)) if total else 0.0
    traits["noise_tone_db"] = ("ratio_db", max(-40.0, min(40.0, ratio)))

    # the envelope, read with a window that suits a fundamental if there is one
    best = None
    for a, b in runs:
        if TONE_BAND[0] <= freqs[a] and freqs[b - 1] <= TONE_BAND[1] * 1.25:
            share = float(np.sum(power[a:b]))
            if best is None or share > best[0]:
                best = (share, a, b)
    f0 = None
    if best is not None and total and best[0] >= 0.2 * total:
        _, a, b = best
        f0, _ = _peak_near(mag, width, float(freqs[a + int(np.argmax(power[a:b]))]), 0.02)
        traits["fundamental_hz"] = ("pitch_hz", f0)
    env = rms_envelope(x, f0 or 1000.0)
    peak_i = int(np.argmax(env))
    peak = float(env[peak_i])
    ms = FRAME * 1000.0 / SAMPLE_RATE

    def last_within(db):
        above = np.nonzero(env >= peak * 10.0 ** (-db / 20.0))[0]
        return int(above[-1]) if len(above) else peak_i

    traits["decay20_ms"] = ("ms", (last_within(20) - peak_i) * ms)
    traits["decay40_ms"] = ("ms", (last_within(40) - peak_i) * ms)
    traits["length_ms"] = ("ms_long", last_within(60) * ms)

    if f0 is not None:
        span = int(0.2 * SAMPLE_RATE)
        z = _inst_freq(x[:span], 20.0, min(4.0 * f0, 900.0))
        top = int(np.argmax(np.abs(z)))
        per_ms = SAMPLE_RATE / 1000.0

        def at(a_ms, b_ms):
            return _weighted_freq(z, top + int(a_ms * per_ms), top + int(b_ms * per_ms))

        early, late = at(2, 12), at(38, 48)
        if early and late and early > 0 and late > 0:
            end = top + int(48 * per_ms)
            # only while the tone is still sounding at the end of the window
            if end < len(z) and abs(z[end]) >= 0.01 * abs(z[top]):
                traits["pitch_drop_cents"] = ("drop_cents", 1200.0 * math.log2(early / late))
    return traits


def measure_drums(inst, spec, prefix):
    """The traits of a drum instrument (or a kit) played with a drum phrase:
    {prefix + trait: (kind, value)}."""
    spec = with_notes(inst, spec)
    traits = {}
    for note, velocity, stereo, latency in drum_hits(inst, spec):
        if note is None:
            tail = 0.5 * (stereo[:, 0] + stereo[:, 1])
            tail = tail[len(tail) // 2 :]
            traits[prefix + "noise_floor_db"] = (
                "floor_db",
                _db(float(np.sqrt(np.mean(tail * tail)))),
            )
            continue
        x = 0.5 * (stereo[latency:, 0] + stereo[latency:, 1])
        key = "%sd%d." % (prefix, note)
        peak = float(np.max(np.abs(x))) if len(x) else 0.0
        traits["%sv%d.peak_db" % (key, velocity)] = ("db", _db(peak))
        if peak <= 0.0:
            continue
        detail = strike_traits(x)
        traits["%sv%d.centroid_hz" % (key, velocity)] = detail["centroid_hz"]
        if velocity == spec["velocity"]:
            for name, value in detail.items():
                traits[key + name] = value
    return traits


# -- a SoundFont as the reference ----------------------------------------------------
#
# A fixed-sound instrument (an electric piano, an organ, a drum machine) has a
# SoundFont to be studied against: a bank somebody else recorded, played through
# the same sampler the carried-over instruments use. The banks live in
# ``~/soundfonts/`` and never in this repository; ``~/soundfonts/reference/``
# holds one JSON record per bank (``bank``, ``file``, ``md5``, ``licence``,
# ``source_url``, ``presets``). A bank is named by its md5, and the file is
# checked against it every time, so a renamed or replaced file cannot pass for
# the one that was studied.

SOUNDFONTS = os.path.join(os.path.expanduser("~"), "soundfonts")


def file_md5(path):
    digest = hashlib.md5()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def find_reference(md5, folder=None):
    """The record and the verified path of the bank whose md5 starts with ``md5``.

    ``md5`` is at least 6 hex digits. Raises ``LookupError`` when no record has
    it or two do, and ``OSError`` when the record's file is missing or its md5
    is not the record's."""
    folder = folder or SOUNDFONTS
    md5 = md5.lower()
    if len(md5) < 6 or any(c not in "0123456789abcdef" for c in md5):
        raise LookupError(
            "a bank is named by the first 6 or more hex digits of its md5, not %r" % md5
        )
    records = os.path.join(folder, "reference")
    found = []
    if os.path.isdir(records):
        for entry in sorted(os.listdir(records)):
            if entry.endswith(".json"):
                with open(os.path.join(records, entry)) as f:
                    record = json.load(f)
                if str(record.get("md5", "")).startswith(md5):
                    found.append(record)
    if not found:
        raise LookupError("no record in %s has an md5 starting %s" % (records, md5))
    if len(found) > 1:
        raise LookupError("%d records start with md5 %s: give more digits" % (len(found), md5))
    record = found[0]
    path = os.path.join(folder, record["file"])
    if not os.path.isfile(path):
        raise OSError("the bank %s (md5 %s) is not at %s" % (record["bank"], record["md5"], path))
    actual = file_md5(path)
    if actual != record["md5"]:
        raise OSError("%s has md5 %s, the record says %s" % (path, actual, record["md5"]))
    return record, path


def open_reference(path, program, bank_number=0, drums=False):
    """An instrument on one preset of the bank at ``path``: the melodic instrument, or
    ``soundfont_drums`` for bank 128 (``program`` is then the kit's program number) or
    when ``drums`` says the preset is a kit in a melodic bank."""
    if bank_number == PERCUSSION_BANK:
        inst = adapter.create(SAMPLE_RATE, voice="soundfont_drums", bank=path)
        try:
            kits = [p for p, _ in open_bank(path).programs(PERCUSSION_BANK)]
            if program not in kits:
                raise LookupError("the bank has no kit %d:%d" % (bank_number, program))
            inst.program_change(kits.index(program))
        except BaseException:
            inst.deinit()
            raise
        return inst
    inst = adapter.create(SAMPLE_RATE, voice="soundfont", bank=path)
    try:
        if bank_number:
            inst.control_change(0, bank_number)
        inst.program_change(program)
        if inst.preset != (bank_number, program) or inst.preset_name is None:
            raise LookupError("the bank has no melodic preset %d:%d" % (bank_number, program))
    except BaseException:
        inst.deinit()
        raise
    return inst


def render_reference(path, program, spec, bank_number=0):
    """The phrase played through ``vrack.soundfont`` on one melodic preset of the bank at ``path``."""
    inst = open_reference(path, program, bank_number)
    try:
        return play(inst, spec)
    finally:
        inst.deinit()


def reference_spec(path, program, spec, bank_number=0):
    """``spec`` with a drum phrase's notes filled in from the preset (as it is recorded)."""
    if not spec.get("drums"):
        return spec
    inst = open_reference(path, program, bank_number)
    try:
        return with_notes(inst, spec)
    finally:
        inst.deinit()


def measure_reference(path, program, spec, bank_number=0):
    """The traits of one preset, keys starting ``ref.`` where an instrument's start ``p<patch>.``."""
    if spec.get("drums"):
        inst = open_reference(path, program, bank_number)
        try:
            return measure_drums(inst, spec, "ref.")
        finally:
            inst.deinit()
    stereo, latency, events = render_reference(path, program, spec, bank_number)
    return measure_render(stereo, latency, events, spec, "ref.")


def spec_for(phrase_name):
    """The phrase of an instrument's spec, or of ``PHRASES``: the spec without ``patches`` and ``reference``.
    A drum kit in a melodic bank (the FreePats "Synthesizer percuss" at 0:0) is played with ``drums``."""
    source = SPECS.get(phrase_name) or PHRASES.get(phrase_name)
    if source is None:
        raise LookupError(
            "no phrase %r: the instruments are %s, the phrases %s"
            % (phrase_name, sorted(SPECS), sorted(PHRASES))
        )
    return {k: v for k, v in source.items() if k not in ("patches", "reference")}


def against_reference(accepted, reference, patch):
    """How an instrument's accepted traits differ from a reference's:
    [(trait, kind, instrument, reference, instrument - reference)], for the
    traits both have. ``accepted`` is a loaded trait file's ``traits``."""
    prefix = "p%d." % patch
    rows = []
    for key, entry in sorted(accepted.items()):
        if not key.startswith(prefix):
            continue
        ref = reference.get("ref." + key[len(prefix) :])
        if ref is not None:
            rows.append(
                (key[len(prefix) :], entry["kind"], entry["value"], ref[1], entry["value"] - ref[1])
            )
    return rows


# -- accepting and checking ---------------------------------------------------------


def tolerance(kind, value):
    absolute, fraction, least = TOLERANCE[kind]
    return max(least, absolute, abs(value) * fraction)


def path_for(name):
    return os.path.join(TRAITS_DIR, name + ".json")


def unsteady(traits, nudged):
    """The traits that move by more than half their tolerance, or go missing, in
    any of ``nudged``: other measurements of the same phrase."""
    out = []
    for key, (kind, value) in traits.items():
        for other in nudged:
            now = other.get(key)
            if now is None or abs(now[1] - value) > 0.5 * tolerance(kind, value):
                out.append(key)
                break
    return sorted(out)


def accept(name, traits, nudged=None):
    """Store measured traits as the accepted ones, each with its tolerance.

    With ``nudged`` (the same instrument measured as ``nudged()`` does), the
    traits that do not hold still are recorded as unsteady instead, and are not
    checked."""
    shaky = unsteady(traits, nudged) if nudged is not None else []
    record = {
        "instrument": name,
        "spec": SPECS[name],
        "traits": {
            key: {
                "kind": kind,
                "value": round(value, 3),
                "tol": round(tolerance(kind, value), 3),
            }
            for key, (kind, value) in sorted(traits.items())
            if key not in shaky
        },
        "unsteady": shaky,
    }
    os.makedirs(TRAITS_DIR, exist_ok=True)
    with open(path_for(name), "w") as f:
        json.dump(record, f, indent=1, sort_keys=True)
        f.write("\n")
    return record


def load(name):
    with open(path_for(name)) as f:
        return json.load(f)


def compare(record, traits):
    """The traits that moved outside their tolerance, or went missing: [(key, accepted, now, tol)]."""
    moved = []
    for key, entry in sorted(record["traits"].items()):
        now = traits.get(key)
        if now is None:
            moved.append((key, entry["value"], None, entry["tol"]))
        elif abs(now[1] - entry["value"]) > entry["tol"]:
            moved.append((key, entry["value"], now[1], entry["tol"]))
    for key in sorted(set(traits) - set(record["traits"]) - set(record.get("unsteady", ()))):
        moved.append((key, None, traits[key][1], None))
    return moved


def reference_record(record, program, bank_number, phrase_name, spec, traits):
    """The traits of a reference, with what they were measured from."""
    return {
        "reference": {
            "bank": record["bank"],
            "md5": record["md5"],
            "licence": record.get("licence"),
            "bank_number": bank_number,
            "program": program,
        },
        "phrase": phrase_name,
        "spec": spec,
        "traits": {
            key: {"kind": kind, "value": round(value, 3)}
            for key, (kind, value) in sorted(traits.items())
        },
    }


def main_reference(args):
    record, path = find_reference(args.reference[0], args.soundfonts)
    program = int(args.reference[1])
    vs_name, _, vs_patch = (args.vs or "").partition(":")
    phrase_name = args.phrase or vs_name or ("drums" if args.bank == PERCUSSION_BANK else "keys")
    spec = reference_spec(path, program, spec_for(phrase_name), args.bank)
    traits = measure_reference(path, program, spec, args.bank)
    print(
        "%s (md5 %s, %s) preset %d:%d, phrase %s: %d traits"
        % (
            record["bank"],
            record["md5"][:8],
            record.get("licence", "licence unrecorded"),
            args.bank,
            program,
            phrase_name,
            len(traits),
        )
    )
    if args.show:
        for key, (kind, value) in sorted(traits.items()):
            print("%-32s %10.2f  %s" % (key, value, kind))
    if args.out:
        with open(args.out, "w") as f:
            json.dump(
                reference_record(record, program, args.bank, phrase_name, spec, traits),
                f,
                indent=1,
                sort_keys=True,
            )
            f.write("\n")
        print("wrote", args.out)
    if vs_name:
        patch = int(vs_patch or 0)
        rows = against_reference(load(vs_name)["traits"], traits, patch)
        print("%s patch %d against the reference (instrument - reference):" % (vs_name, patch))
        for trait, kind, mine, theirs, diff in rows:
            print("%-28s %10.2f %10.2f %+10.2f  %s" % (trait, mine, theirs, diff, kind))
        if not rows:
            print("no trait in common: is the instrument's phrase %r?" % phrase_name)
    return 0


def main(argv):
    parser = argparse.ArgumentParser(prog="traits.py", description=__doc__.split("\n")[0])
    parser.add_argument("names", nargs="*", help="instruments (all of SPECS when none)")
    parser.add_argument(
        "--accept", action="store_true", help="store the measured values as accepted"
    )
    parser.add_argument("--show", action="store_true", help="print every trait")
    parser.add_argument(
        "--reference",
        nargs=2,
        metavar=("MD5", "PROGRAM"),
        help="measure a SoundFont preset instead (bank 128: a kit, by its program number)",
    )
    parser.add_argument("--bank", type=int, default=0, help="the preset's bank number (default 0)")
    parser.add_argument(
        "--phrase", help="an instrument or one of %s (default keys)" % ", ".join(sorted(PHRASES))
    )
    parser.add_argument(
        "--vs",
        metavar="NAME[:PATCH]",
        help="print an instrument's accepted traits against the reference",
    )
    parser.add_argument("--out", help="write the reference's traits to this JSON file")
    parser.add_argument(
        "--soundfonts", help="the folder of banks and reference/ (default ~/soundfonts)"
    )
    args = parser.parse_args(argv[1:])
    if args.reference:
        try:
            return main_reference(args)
        except (LookupError, OSError) as exc:
            print("traits.py:", exc)
            return 2
    names = args.names or sorted(SPECS)
    status = 0
    for name in names:
        traits = measure(name)
        if args.show:
            for key, (kind, value) in sorted(traits.items()):
                print("%-32s %10.2f  %s" % (key, value, kind))
        if args.accept:
            record = accept(name, traits, nudged(name))
            print(
                "%s: accepted %d traits into %s (%d unsteady)"
                % (name, len(record["traits"]), path_for(name), len(record["unsteady"]))
            )
            continue
        moved = compare(load(name), traits)
        for key, was, now, tol in moved:
            print("%s: %s was %s, now %s (tolerance %s)" % (name, key, was, now, tol))
        print("%s: %d traits, %d moved" % (name, len(traits), len(moved)))
        status |= 1 if moved else 0
    return status


if __name__ == "__main__":
    sys.exit(main(sys.argv))
