"""Render chords through the polyphonic adapter and check the steals for clicks.

    python examples/poly_render.py [voice]        # CPython
    micropython examples/poly_render.py [voice]   # MicroPython
    python examples/poly_render.py mono_one --no-fade   # plant the fault

It plays four six-note chords on a four-voice instrument, so every chord
steals voices, and an overlapping phrase on a one-voice instrument, where
every note steals the only voice. It writes the chords to ``wav_exports/``
and then looks for clicks.

A click is a step in a signal that is otherwise smooth. The check takes the
second difference at each sample, x[n+1] - 2 x[n] + x[n-1], and divides it
by the loudest sample within 64 either side. For a smooth tone that ratio is
(2 pi f / rate) squared, under 0.005 for the notes played here; a step
of 1% of the level makes it 0.01 or more. The script prints the largest
ratio anywhere outside the steals, the largest inside any steal (the 6 blocks
from the note arriving), and their quotient. A quotient under 2 means the
steals are as smooth as the rest of the music.

That only works on a tone that is smooth to begin with, so for ``mono_one`` the
script plays a triangle through a low filter, and for ``poly106`` a sawtooth
through a low filter with its chorus on. Other voices play as shipped, and
the baseline then includes their own sharp edges. An instrument that reports
a ``latency_samples`` has its steals looked for that much later.

``--no-fade`` replaces the voice's one-block fades with a hard cut and a
hard start, the way a plain allocator steals, and shows the check sees the
click.
"""

import array
import struct
import sys

if "lib" not in sys.path:
    sys.path.insert(0, "lib")

import audiocore
import audioinstruments._rack.adapter as adapter

SAMPLE_RATE = 48000
BUFFER = 256
BLOCK = 128
WINDOW = 6 * BLOCK

# (seconds, notes), each chord strummed 25 ms apart and held to the next one.
CHORDS = (
    (0.0, (48, 55, 59, 62, 64, 67)),
    (0.9, (45, 52, 57, 60, 64, 69)),
    (1.8, (41, 48, 57, 60, 64, 65)),
    (2.7, (43, 50, 55, 59, 62, 67)),
)
LENGTH = 3.8

# One note every 250 ms, each starting 80 ms before the last one ends.
PHRASE = (60, 64, 67, 72, 67, 64, 62, 59)


def chord_score():
    score = []
    for index, (start, notes) in enumerate(CHORDS):
        for k, note in enumerate(notes):
            score.append((start + 0.025 * k, "on", note, 96))
        end = CHORDS[index + 1][0] if index + 1 < len(CHORDS) else start + 0.8
        for note in notes:
            score.append((end, "off", note, 0))
    return sorted(score, key=lambda e: e[0])


def phrase_score():
    score = []
    for k, note in enumerate(PHRASE):
        start = 0.25 * k
        score.append((start, "on", note, 100))
        score.append((start + 0.33, "off", note, 0))
    return sorted(score, key=lambda e: e[0])


# Instruments whose own allocator refuses a key when every voice is held; the
# chords here hold more keys than voices, so they are made to steal instead.
STEAL = {"poly80": "oldest"}

# A triangle through a low filter with no envelope on it: a nearly pure tone,
# so that a step shows up against the smoothness around it.
# {voice: {module in each copy: {parameter: value}}}
SMOOTH = {
    "mono_one": {
        "synth": {
            "vco_a_level": 0.0,
            "vco_b_saw": 0.0,
            "vco_b_tri": 1.0,
            "vco_b_level": 1.0,
            "filter_cutoff": 0.5,
            "filter_env_amt": 0.0,
            "filter_res": 0.0,
            "volume": 1.1,
        }
    },
    "poly80": {
        "voice": {
            "mix": 0.0,
            "ch1_saw": True,
            "ch1_square": False,
            "ch1_noise": 0.0,
            "ch1_sine": 0.0,
            "ch1_hpf": 0.0,
            "ch1_lpf": 0.35,
            "ch1_res_h": 0.0,
            "ch1_res_l": 0.0,
            "ch1_il": 0.0,
            "ch1_al": 0.0,
            "ch1_init_bril": 0.0,
            "ch1_init_level": 0.0,
            "ch1_after_bril": 0.0,
            "ch1_after_level": 0.0,
            "ch1_attack": 0.0,
            "ch1_sustain": 1.0,
            "ch1_vcf_level": 1.0,
            "slop": 0.0,
        }
    },
    "poly106": {
        "voice": {
            "dco_saw": 1.0,
            "dco_pulse": 0.0,
            "dco_sub": 0.0,
            "vcf_freq": 0.36,
            "vcf_kybd": 0.0,
            "vcf_env": 0.0,
            "vcf_res": 0.0,
            "env_attack": 0.0,
            "env_sustain": 1.0,
            "vel_vca": 0.0,
            "vca_level": 1.0,
        }
    },
    "poly6": {
        "voice": {
            "vco_wave": 0.0,
            "sub_osc": 0.0,
            "sub_level": 0.0,
            "noise": 0.0,
            "vcf_cutoff": 0.35,
            "vcf_kbd_track": 0.0,
            "vcf_eg_int": 0.0,
            "vcf_resonance": 0.0,
            "eg_attack": 0.0,
            "eg_sustain": 1.0,
            "slop": 0.0,
            "volume": 0.6,
        }
    },
    "mono101": {
        "voice": {
            "saw": 1.0,
            "pulse": 0.0,
            "sub": 0.0,
            "noise": 0.0,
            "vcf_freq": 0.32,
            "vcf_kybd": 0.0,
            "vcf_env": 0.0,
            "vcf_res": 0.0,
            "env_attack": 0.0,
            "env_sustain": 1.0,
            "trig": 1.0,
            "vel_vca": 0.0,
            "volume": 0.8,
        }
    },
    "mono_synth": {
        "voice": {
            "osc1_wave": 2.0,
            "mix_osc1": 0.8,
            "mix_osc2": 0.0,
            "mix_osc3": 0.0,
            "mix_noise": 0.0,
            "vcf_cutoff": -0.6,
            "vcf_contour": 0.0,
            "vcf_emphasis": 0.0,
            "kybd_1": 0.0,
            "kybd_2": 0.0,
            "vca_attack": 0.0,
            "vca_sustain": 1.0,
            "vel_vca": 0.0,
            "volume": 0.8,
        }
    },
    "poly5": {
        "voice": {
            "mix_osc_a": 0.0,
            "mix_osc_b": 0.7,
            "mix_noise": 0.0,
            "osc_b_saw": 0.0,
            "osc_b_tri": 1.0,
            "osc_b_pulse": 0.0,
            "vcf_cutoff": 0.38,
            "vcf_env_amount": 0.0,
            "vcf_resonance": 0.0,
            "vcf_kybd": 1.0,
            "amp_attack": 0.0,
            "amp_sustain": 1.0,
            "slop": 0.0,
            "volume": 0.6,
        }
    },
    "poly8": {
        "voice": {
            "source_mix": 0.0,
            "vco1_wave": 0.0,
            "vcf_slope": 24.0,
            "vcf_cutoff": 0.38,
            "vcf_env": 0.0,
            "vcf_resonance": 0.0,
            "vcf_kybd": 1.0,
            "hpf_cutoff": 0.0,
            "env2_attack": 0.0,
            "env2_sustain": 1.0,
            "slop": 0.0,
            "volume": 0.6,
        }
    },
    "polyxa": {
        "voice": {
            "vco1_saw": 1.0,
            "vco1_pulse": 0.0,
            "vco2_saw": 0.0,
            "vco2_pulse": 0.0,
            "noise": 0.0,
            "vcf_slope": 24.0,
            "vcf_cutoff": 0.38,
            "vcf_env": 0.0,
            "vcf_resonance": 0.0,
            "vcf_kybd": 1.0,
            "vco2_vcf": 0.0,
            "aenv_attack": 0.0,
            "aenv_sustain": 1.0,
            "slop": 0.0,
            "volume": 0.6,
        }
    },
    "bass_pedals": {
        "voice": {
            "mix": 1.0,
            "filter_cutoff": 0.2,
            "filter_amount": 0.0,
            "filter_emphasis": 0.0,
            "loud_attack": 0.0,
            "loud_sustain": 1.0,
            "decay": 1.0,
            "loud_decay": 0.5,
            "glide": 0.0,
        }
    },
    "duosynth": {
        "voice": {
            "vco1_wave": 0.0,
            "mix_vco1": 0.9,
            "mix_vco2": 0.0,
            "mix_noise": 0.0,
            "vcf_cutoff": 0.38,
            "vcf_env": 0.0,
            "vcf_resonance": 0.0,
            "vcf_kybd": 0.0,
            "adsr_attack": 0.0,
            "adsr_sustain": 1.0,
            "vca_level": 1.0,
            "hpf_cutoff": 0.0,
            "drift": 0.0,
        }
    },
    "polya6": {
        "voice": {
            "osc1_saw": "up",
            "osc1_tri": False,
            "osc1_sine": False,
            "osc1_square": False,
            "osc2_saw": "off",
            "osc2_tri": False,
            "osc2_sine": False,
            "osc2_square": False,
            "mix_osc1": 80.0,
            "mix_osc2": 0.0,
            "mix_sub1": 0.0,
            "mix_sub2": 0.0,
            "mix_ring": 0.0,
            "mix_noise": 0.0,
            "f2_freq": 500.0,
            "f2_res": 0.0,
            "f2_env2": 0.0,
            "f2_keytrack": 0.0,
            "post_f2_lp": 100.0,
            "post_f1_lp": 0.0,
            "post_f1_hp": 0.0,
            "post_f1_bp": 0.0,
            "env1_attack": 0.002,
            "env2_attack": 0.002,
            "env3_attack": 0.002,
            "env3_sustain": 100.0,
            "slop": 0.0,
        }
    },
    "string_ensemble": {
        "voice": {
            "viola": 0.0,
            "violin": 0.0,
            "trumpet": 0.0,
            "horn": 1.0,
        }
    },
    "vocoder330": {
        "voice": {
            "strings_upper": 1.0,
            "strings_lower": 1.0,
            "strings_attack": 0.0,
            "release": 1.0,
        }
    },
}


def render(voice, voices, score, seconds, fades=True):
    """Play ``score`` and return (left samples, stereo bytes, steal start frames)."""
    on_cpython = sys.implementation.name == "cpython"
    inst = adapter.create(
        SAMPLE_RATE,
        voice=voice,
        voices=voices,
        block_size=BLOCK,
        buffer_frames=BUFFER,
        output="pull" if on_cpython else "ring",
        ring_blocks=2,
    )
    pool = inst.voice_pool
    if voice in STEAL:  # its chords hold more keys than voices: steal, don't refuse
        pool.alloc.set_steal(STEAL[voice])
    for module, params in SMOOTH.get(voice, {}).items():
        for name, value in params.items():
            pool.set_param(module, name, value)
    late = inst.latency_samples
    if not fades:
        mix = pool.mix

        def hard_cut(i):
            mix.gain[i] = mix.target[i] = 0.0

        def hard_start(i, pan):
            mix.pan[i] = pan
            mix.gain[i] = mix.target[i] = 1.0

        pool.fade_out = hard_cut
        pool.fade_in = hard_start
    buffers = int(seconds * SAMPLE_RATE) // BUFFER
    left = array.array("h", bytes(buffers * BUFFER * 2))
    stereo = bytearray(buffers * BUFFER * 4)
    steals = []
    queue = list(score)
    for index in range(buffers):
        start = index * BUFFER
        stolen = pool.stolen
        note_on = False
        while queue and queue[0][0] * SAMPLE_RATE < start + BUFFER:
            _, kind, note, velocity = queue.pop(0)
            if kind == "on":
                inst.note_on(note, velocity)
                note_on = True
            else:
                inst.note_off(note)
        if pool.stolen > stolen or (pool.mono and note_on):
            # a ring holds one buffer more than is pulled, so the audio of
            # these events leaves one buffer later
            steals.append(late + (start if on_cpython else start + BUFFER))
        inst.fill()
        _, data = audiocore.get_buffer(inst.output)
        pcm = array.array("h", bytes(data))
        stereo[index * BUFFER * 4 : (index + 1) * BUFFER * 4] = data
        for i in range(BUFFER):
            left[start + i] = pcm[2 * i]
    inst.deinit()
    return left, stereo, steals


def jerk(x, first, last, quiet=500):
    """The largest second difference over the loudest sample nearby, in x[first:last].

    Stretches quieter than ``quiet`` counts are skipped: there the 16-bit
    rounding is as big as the signal.
    """
    first = max(first, 65)
    last = min(last, len(x) - 65)
    worst = 0.0
    n = first
    while n < last:
        top = 0
        for k in range(n - 64, n + 65, 8):
            a = abs(x[k])
            if a > top:
                top = a
        if top >= quiet:
            end = min(n + 8, last)
            for m in range(n, end):
                j = abs(x[m + 1] - 2 * x[m] + x[m - 1]) / top
                if j > worst:
                    worst = j
        n += 8
    return worst


def outside(x, steals):
    """The largest jerk in the stretches between steals."""
    worst = 0.0
    edge = 64
    pos = 0
    for start in steals + [len(x)]:
        stop = start - edge
        if stop > pos:
            j = jerk(x, pos, stop)
            if j > worst:
                worst = j
        pos = start + WINDOW + edge
    return worst


def inside(x, steals):
    worst = 0.0
    for start in steals:
        j = jerk(x, start - 1, start + WINDOW)
        if j > worst:
            worst = j
    return worst


def level(x):
    peak = 0
    total = 0.0
    clipped = 0
    for v in x:
        a = abs(v)
        if a > peak:
            peak = a
        if a >= 27000:
            clipped += 1
        total += v * v
    return peak, (total / len(x)) ** 0.5, clipped


def write_wav(path, stereo):
    with open(path, "wb") as f:
        f.write(
            struct.pack(
                "<4sI4s4sIHHIIHH4sI",
                b"RIFF",
                36 + len(stereo),
                b"WAVE",
                b"fmt ",
                16,
                1,
                2,
                SAMPLE_RATE,
                SAMPLE_RATE * 4,
                4,
                16,
                b"data",
                len(stereo),
            )
        )
        f.write(stereo)


def save(name, stereo):
    try:
        import os

        try:
            os.mkdir("wav_exports")
        except OSError:
            pass
        impl = sys.implementation.name
        path = "wav_exports/poly_%s_%s.wav" % (name, impl)
        write_wav(path, stereo)
        print("wrote %s (%d bytes)" % (path, len(stereo)))
    except OSError as exc:
        print("no wav written:", exc)


def check_chords(voice, fades):
    x, stereo, steals = render(voice, 4, chord_score(), LENGTH, fades)
    peak, rms, clipped = level(x)
    print(
        "chords on 4 voices: peak %d, rms %.0f, clipped samples %d, %d steals"
        % (peak, rms, clipped, len(steals))
    )
    save(voice, stereo)
    return peak, report("chords", x, steals)


def check_phrase(voice, fades, mono=False):
    x, stereo, steals = render(voice, 1, phrase_score(), 2.4, fades)
    if mono:
        peak, rms, clipped = level(x)
        print(
            "phrase on 1 voice: peak %d, rms %.0f, clipped samples %d, %d note-ons"
            % (peak, rms, clipped, len(steals))
        )
        save(voice, stereo)
        return peak, report("one voice", x, steals)
    return report("one voice", x, steals)


def report(label, x, steals):
    base = outside(x, steals)
    worst = inside(x, steals)
    quotient = worst / base if base else 0.0
    print(
        "%s: smoothness outside the steals %.4f, inside %.4f over %d steals: x%.2f"
        % (label, base, worst, len(steals), quotient)
    )
    return quotient


def main(argv):
    voice = "mono_one"
    for arg in argv[1:]:
        if not arg.startswith("--"):
            voice = arg
    fades = "--no-fade" not in argv
    print(
        "%s on %s, fades %s"
        % (voice, sys.implementation.name, "on" if fades else "OFF (planted fault)")
    )
    if adapter.voice_patch(voice).MONO:
        peak, phrase_ratio = check_phrase(voice, fades, mono=True)
        ok = peak > 500 and phrase_ratio < 2.0
    else:
        peak, chord_ratio = check_chords(voice, fades)
        phrase_ratio = check_phrase(voice, fades)
        ok = peak > 500 and chord_ratio < 2.0 and phrase_ratio < 2.0
    print("result:", "no clicks" if ok else "CLICK or silence")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
