"""Play the Poly106: a pad progression, a bass line, brass stabs and a lead.

    python examples/poly106_demo.py            # writes wav_exports/poly106_demo.wav

One six-voice instrument plays the whole piece and changes patch between
sections, the way you would play it live. Afterwards the script checks what
it can without ears: every section makes sound, nothing reaches the
adapter's clip level, the chorus really spreads the pad across the speakers
(the correlation between left and right, against the same pad with the
chorus off), and how many voices were stolen along the way.
``examples/poly_render.py poly106`` is the check that steals do not click.
"""

import array
import struct
import sys

if "lib" not in sys.path:
    sys.path.insert(0, "lib")

import audiocore
import audioinstruments._rack.adapter as adapter
from demo_check import Audible, section_ok

RATE = 48000
BUFFER = 256
CLIP = 27000
BEAT = 0.5  # 120 bpm

# Patches, by number: see audioinstruments._rack.instruments.poly106.PRESETS.
WARM_PAD, BRASS, BRASS_STAB, PLUCK_BASS, LEAD = 1, 3, 4, 6, 7


def pad(t):
    """Four bars of A minor, F, C and G, each chord held a bar and let ring."""
    chords = (
        (45, 57, 60, 64, 67),
        (41, 57, 60, 64, 65),
        (48, 55, 60, 64, 67),
        (43, 55, 59, 62, 67),
    )
    score = []
    for k, chord in enumerate(chords):
        start = t + 4 * BEAT * k
        for i, note in enumerate(chord):
            score.append((start + 0.01 * i, note, 90, 4 * BEAT - 0.05))
    return score, t + 16 * BEAT + 1.5


def bass(t):
    """Two bars of eighth notes, twice: at 8', A2 sounds A2 (110 Hz), its sub A1."""
    line = (45, 45, 57, 45, 43, 43, 55, 43, 41, 41, 53, 41, 43, 55, 43, 50)
    score = []
    for rep in range(2):
        for k, note in enumerate(line):
            accent = 118 if k % 4 == 0 else 92
            score.append((t + (rep * 16 + k) * BEAT * 0.5, note, accent, BEAT * 0.35))
    return score, t + 16 * BEAT + 0.8


def stabs(t):
    """Brass stabs on the off-beats, then a swell."""
    hits = (
        (0.5, (57, 60, 64)),
        (1.5, (57, 60, 64)),
        (2.5, (55, 59, 62)),
        (3.0, (55, 59, 62)),
        (4.5, (53, 57, 60)),
        (5.5, (53, 57, 60)),
        (6.5, (52, 55, 59)),
        (7.0, (52, 56, 59)),
    )
    score = []
    for beat, chord in hits:
        for note in chord:
            score.append((t + beat * BEAT, note, 120, BEAT * 0.3))
    return score, t + 8 * BEAT + 0.6


def swell(t):
    score = [(t, note, 100, 4 * BEAT) for note in (45, 57, 60, 64, 69)]
    return score, t + 4 * BEAT + 1.0


def lead(t):
    """A melody with long notes, so the delayed vibrato comes in on them."""
    tune = (
        (69, 1.0),
        (72, 0.5),
        (74, 0.5),
        (76, 2.0),
        (74, 0.5),
        (72, 0.5),
        (69, 1.0),
        (67, 1.0),
        (69, 3.0),
    )
    score = []
    at = t
    for note, beats in tune:
        score.append((at, note, 100, beats * BEAT * 0.95))
        at += beats * BEAT
    return score, at + 1.0


SECTIONS = (
    ("pad", WARM_PAD, pad),
    ("bass", PLUCK_BASS, bass),
    ("stabs", BRASS_STAB, stabs),
    ("brass", BRASS, swell),
    ("lead", LEAD, lead),
)


class Meter:
    """One section's peak, RMS, clipped samples, left-right correlation and shares."""

    def __init__(self):
        self.peak = self.clipped = self.count = 0
        self.sl = self.sr = self.sll = self.srr = self.slr = 0.0
        self.audible = Audible(RATE)

    def feed(self, pcm):
        """Add a stretch of interleaved int16 stereo ``pcm``."""
        self.audible.feed(pcm)
        x = array.array("h", pcm)
        peak = self.peak
        clipped = 0
        sl = sr = sll = srr = slr = 0.0
        for i in range(0, len(x) - 1, 2):
            left = x[i]
            right = x[i + 1]
            for v in (left, right):
                if abs(v) > peak:
                    peak = abs(v)
                if abs(v) >= CLIP:
                    clipped += 1
            sl += left
            sr += right
            sll += left * left
            srr += right * right
            slr += left * right
        self.peak = peak
        self.clipped += clipped
        self.count += len(x) // 2
        self.sl += sl
        self.sr += sr
        self.sll += sll
        self.srr += srr
        self.slr += slr

    def rms(self):
        return ((self.sll + self.srr) / (2 * self.count)) ** 0.5

    def corr(self):
        n = self.count
        ml, mr = self.sl / n, self.sr / n
        vl = self.sll / n - ml * ml
        vr = self.srr / n - mr * mr
        return (self.slr / n - ml * mr) / (vl * vr) ** 0.5 if vl > 0 and vr > 0 else 1.0


def render(sections, chorus_off=False, wav_file=None):
    """Play the piece, metering each section as it goes and streaming a WAV.

    Nothing holds the whole render: it would not fit MicroPython's default
    heap. Returns the sections' start times, a ``Meter`` for each and the
    number of voices stolen.
    """
    on_cpython = sys.implementation.name == "cpython"
    inst = adapter.create(
        RATE, voice="poly106", output="pull" if on_cpython else "ring", ring_blocks=2
    )
    events = []
    starts = []
    t = 0.2
    for name, patch, write in sections:
        starts.append((name, int(t * RATE)))
        events.append((t - 0.1, "patch", patch, 0))
        score, t = write(t)
        for at, note, velocity, length in score:
            events.append((at, "on", note, velocity))
            events.append((at + length, "off", note, 0))
    events.sort(key=lambda e: (e[0], e[1] != "patch", e[1] == "on"))
    buffers = int((t + 0.5) * RATE) // BUFFER
    frames = buffers * BUFFER
    bounds = [frame for _, frame in starts] + [frames]
    meters = [Meter() for _ in starts]
    if wav_file is not None:
        write_wav_header(wav_file, frames * 4)
    k = 0
    for b in range(buffers):
        first = b * BUFFER
        end = first + BUFFER
        while k < len(events) and events[k][0] * RATE < end:
            _, kind, a, v = events[k]
            if kind == "patch":
                inst.program_change(a)
                if chorus_off:
                    inst.set_macro(9, 0)
            elif kind == "on":
                inst.note_on(a, v)
            else:
                inst.note_off(a)
            k += 1
        inst.fill()
        _, data = audiocore.get_buffer(inst.output)
        data = bytes(data)
        if wav_file is not None:
            wav_file.write(data)
        for s, meter in enumerate(meters):
            lo = max(bounds[s], first)
            hi = min(bounds[s + 1], end)
            if lo < hi:
                meter.feed(data[(lo - first) * 4 : (hi - first) * 4])
    stolen = inst.voice_pool.stolen
    inst.deinit()
    return starts, meters, stolen


def write_wav_header(f, length):
    f.write(
        struct.pack(
            "<4sI4s4sIHHIIHH4sI",
            b"RIFF",
            36 + length,
            b"WAVE",
            b"fmt ",
            16,
            1,
            2,
            RATE,
            RATE * 4,
            4,
            16,
            b"data",
            length,
        )
    )


def main():
    wav_path = "wav_exports/poly106_demo.wav"
    wav_file = None
    try:
        import os

        try:
            os.mkdir("wav_exports")
        except OSError:
            pass
        wav_file = open(wav_path, "wb")  # noqa: SIM115 (closed after the render)
    except OSError as exc:
        print("no wav written:", exc)
    starts, meters, stolen = render(SECTIONS, wav_file=wav_file)
    if wav_file is not None:
        wav_file.close()
        print("wrote %s" % wav_path)
    ok = True
    print("section  peak   rms  clipped  L/R correlation  audible   upper")
    for (name, _), meter in zip(starts, meters):
        share, upper = meter.audible.share(), meter.audible.upper_share()
        print(
            "%-7s %5d %5.0f %8d  %15.3f %7.0f%% %6.1f%%"
            % (name, meter.peak, meter.rms(), meter.clipped, meter.corr(), 100 * share, 100 * upper)
        )
        ok = ok and section_ok(meter.rms(), meter.clipped, share, upper)
    wet_corr = meters[0].corr()
    _, dry, _ = render(SECTIONS[:1], chorus_off=True)
    dry_corr = dry[0].corr()
    print("pad with the chorus off: L/R correlation %.3f; on: %.3f" % (dry_corr, wet_corr))
    ok = ok and dry_corr > 0.999 and wet_corr < 0.9
    print("voices stolen: %d" % stolen)
    print("result:", "ok" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
