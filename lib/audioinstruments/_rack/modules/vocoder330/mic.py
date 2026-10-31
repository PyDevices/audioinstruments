# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Vocoder330 mic: the voice the vocoder listens to.

The rack's instruments have no audio input, so the mic is built in. Its output
``mic`` is the modulator every other part reads, after the mic gain
(``mic_level``), and ``mic_source`` picks where it comes from:

- ``"test"``: a built-in talker, so the vocoder sounds in tests, renders and
  demos with no file and no hardware. A glottal sawtooth through three formant
  filters, with a burst of noise before some syllables, saying a phrase of six
  syllables that repeats every ``TALKER_PHRASE_S``. It is the same samples every
  run from a fresh module, and ``reset()`` starts the phrase again.
- ``"input"``: an audiodsp sample chained in with ``attach(sample)`` (any mono
  sample at the rack's rate: a ``WaveFile``, a ``RawSample``), or, with none
  attached, the ``mic_in`` jack, so a rack patched by hand can feed it. The
  first block of an attached sample is lost to the bridge that pulls it; a
  sample that has ended gives silence.
- ``"off"``: silence.

The talker is a design choice, not a model of any speaker: the vowels are
Peterson and Barney's (1952) averages for men.
"""

import math

import audiofilters

from ...core.bridge import NodeBridge, effect_kwargs
from ...core.jack import SignalType
from ...core.module import Module
from ...core.signal import add_scaled, copy_into, mul
from ...dsp.biquad import BiquadFilter
from ...dsp.noise import NoiseGenerator
from ...dsp.oscillator import OscillatorCore
from .._util import jack_signal
from .filters import clear_filter

#: ``mic_source``'s positions, as the module stores them.
MIC_SOURCES = ("off", "test", "input")

#: The mic's gain is ``MIC_GAIN_AT_10 * (mic_level / 10) ** 2``: 1.0 at the fresh 5.
MIC_GAIN_AT_10 = 4.0

#: The talker's voice: the glottal source's pitch, Hz.
TALKER_F0 = 110.0

#: The seconds the formants take to glide from one vowel's to the next's.
TALKER_GLIDE_S = 0.04

#: The phrase loops in this many seconds.
TALKER_PHRASE_S = 2.4

#: The talker's noise is seeded, so its fricatives are the same every run.
TALKER_SEED = 330

#: The formant filters' Q, and the levels of the first, second and third.
TALKER_FORMANT_Q = 5.0
TALKER_FORMANT_LEVELS = (1.0, 0.5, 0.25)

#: A syllable rises over the first, holds, and falls over the second; a fricative's
#: burst of noise comes just before it and lasts the third.
TALKER_RISE_S = 0.03
TALKER_FALL_S = 0.06
TALKER_BURST_S = 0.06

#: How loud the voiced sound and the noise are into the mic at the fresh ``mic_level``.
TALKER_GAIN = 2.2
TALKER_NOISE_GAIN = 0.35

#: Each vowel's first three formants, Hz: Peterson and Barney (1952), men.
TALKER_VOWELS = {
    "i": (270.0, 2290.0, 3010.0),
    "e": (530.0, 1840.0, 2480.0),
    "a": (730.0, 1090.0, 2440.0),
    "o": (570.0, 840.0, 2410.0),
    "u": (300.0, 870.0, 2240.0),
}

#: The phrase: each syllable's vowel, how long it holds, the silence after it,
#: whether a burst of noise comes before it, and how far its pitch moves across it
#: (semitones; negative falls). Two words of three syllables.
TALKER_PHRASE = (
    ("a", 0.18, 0.03, True, 0.6),
    ("i", 0.18, 0.03, False, 0.6),
    ("u", 0.24, 0.20, False, -0.8),
    ("e", 0.18, 0.03, True, 0.8),
    ("o", 0.18, 0.03, False, 0.6),
    ("a", 0.24, 0.20, False, -1.0),
)


class Vocoder330Mic(Module):
    NAME = "Vocoder330Mic"
    DISPLAY_NAME = "Vocoder330 Mic"
    HP = 6

    def _build(self):
        sr, n = self.sample_rate, self.block_size
        audio = SignalType.AUDIO
        self.in_jack = self.add_input("mic_in", "Mic In", audio)
        self.out_jack = self.add_output("mic", "Mic", audio)
        self.add_param("mic_level", "Mic Level", default=5.0, max_val=10.0)
        self.add_param("mic_source", "Mic Source", default=1.0, max_val=2.0)
        #: 0.0 when nothing reads the mic: the talker then only keeps time (set by the patch).
        self.add_param("active", "Active", default=1.0)

        self.osc = OscillatorCore(sr)
        self.noise = NoiseGenerator(seed=TALKER_SEED)
        self.formants = [BiquadFilter(n, sr, "BP", stages=1, q=TALKER_FORMANT_Q) for _ in range(3)]
        for name in ("_saw", "_band", "_voiced", "_env", "_pitch", "_noise", "_tmp", "_zero"):
            self.add_scratch(name)
        self._build_unit()

        # the phrase as start times: each syllable's burst (if any), voiced part and end
        self._burst_at = []
        self._voiced_at = []
        self._voiced_len = []
        self._end_at = []
        t = 0.0
        for _vowel, hold, gap, fricative, _glide in TALKER_PHRASE:
            self._burst_at.append(t if fricative else -1.0)
            if fricative:
                t += TALKER_BURST_S
            self._voiced_at.append(t)
            length = TALKER_RISE_S + hold + TALKER_FALL_S
            self._voiced_len.append(length)
            t += length + gap
            self._end_at.append(t)
        if t > TALKER_PHRASE_S:
            raise ValueError("the talker's phrase is longer than TALKER_PHRASE_S")

        self._sample = None
        self._bridge = None
        self._said = None  # a vowel the talker holds, or None for the phrase
        self.reset()

    def _build_unit(self):
        self.add_scratch("_unit")
        n = self.block_size
        for i in range(n):
            self._unit[i] = (i + 1) / n

    def set_block_size(self, block_size):
        super().set_block_size(block_size)
        for i in range(block_size):
            self._unit[i] = (i + 1) / block_size
        self.formants = [
            BiquadFilter(block_size, self.sample_rate, "BP", stages=1, q=TALKER_FORMANT_Q)
            for _ in range(3)
        ]
        if self._sample is not None:
            self.attach(self._sample)

    def reset(self):
        self._t = 0.0
        self.noise.reset()
        self.osc.reset()
        for f in self.formants:
            clear_filter(f)
        self._f = list(TALKER_VOWELS[TALKER_PHRASE[0][0]])
        self._e_vowel = TALKER_VOWELS[TALKER_PHRASE[0][0]]
        self._fresh = True
        self.out_jack.buffer[:] = 0.0

    # -- the sample an "input" mic plays ------------------------------------------------

    def attach(self, sample):
        """Chain a mono audiodsp sample in as the mic's input; ``None`` detaches it."""
        if sample is None:
            self._sample = None
            self._bridge = None
            return
        channels = getattr(sample, "channel_count", 1)
        if channels != 1:
            raise ValueError("attach_mic needs a mono sample, this one has %d channels" % channels)
        rate = getattr(sample, "sample_rate", self.sample_rate)
        if rate != self.sample_rate:
            raise ValueError(
                "attach_mic needs a sample at the instrument's %d Hz, this one is %d Hz"
                % (self.sample_rate, rate)
            )
        self._sample = sample
        self._bridge = NodeBridge(self.block_size, self.sample_rate).chain(
            sample,
            audiofilters.Filter(filter=None, **effect_kwargs(self.block_size, self.sample_rate)),
        )

    def say(self, vowel):
        """Make the talker hold ``vowel`` ('i', 'e', 'a', 'o' or 'u') until ``say(None)``."""
        if vowel is not None and vowel not in TALKER_VOWELS:
            raise ValueError("vowel must be one of %s" % ", ".join(sorted(TALKER_VOWELS)))
        self._said = vowel

    # -- the talker ---------------------------------------------------------------------

    def _eval(self, t):
        """The phrase at second ``t``: ``_e_amp``, ``_e_noise``, ``_e_pitch`` and ``_e_vowel``."""
        self._e_amp = 0.0
        self._e_noise = 0.0
        self._e_pitch = 0.0
        for k in range(len(TALKER_PHRASE)):
            start = self._burst_at[k] if self._burst_at[k] >= 0.0 else self._voiced_at[k]
            if t < start or t >= self._end_at[k]:
                continue
            self._e_vowel = TALKER_VOWELS[TALKER_PHRASE[k][0]]
            burst = self._burst_at[k]
            if burst >= 0.0 and t < self._voiced_at[k]:
                edge = 0.01
                d = t - burst
                self._e_noise = max(0.0, min(1.0, d / edge, (TALKER_BURST_S - d) / edge))
                return
            d = t - self._voiced_at[k]
            length = self._voiced_len[k]
            if d < length:
                self._e_amp = min(1.0, d / TALKER_RISE_S, (length - d) / TALKER_FALL_S)
                self._e_pitch = TALKER_PHRASE[k][4] * (d / length - 0.5)
            return

    def _ramp(self, dst, start, end):
        copy_into(dst, self._unit)
        dst *= end - start
        dst += start

    def _talk(self, n):
        """The talker's next block into ``_voiced``."""
        dt = n / self.sample_rate
        if self._said is not None:
            self._e_vowel = TALKER_VOWELS[self._said]
            a0 = a1 = 1.0
            n0 = n1 = 0.0
            p0 = p1 = 0.0
        else:
            t0 = self._t
            self._eval(t0)
            a0, n0, p0 = self._e_amp, self._e_noise, self._e_pitch
            t1 = t0 + dt
            if t1 >= TALKER_PHRASE_S:
                t1 -= TALKER_PHRASE_S
            self._t = t1
            self._eval(t1)
            a1, n1, p1 = self._e_amp, self._e_noise, self._e_pitch
        if a0 == 0.0 and a1 == 0.0 and n0 == 0.0 and n1 == 0.0:
            self._voiced[:] = 0.0
            return
        voiced = self._voiced
        voiced[:] = 0.0
        if a0 > 0.0 or a1 > 0.0:
            # the formants glide to the vowel being said
            target = self._e_vowel
            if self._fresh:
                self._f = list(target)
                self._fresh = False
            coef = 1.0 - math.exp(-dt / TALKER_GLIDE_S)
            for k in range(3):
                self._f[k] += (target[k] - self._f[k]) * coef
            self._ramp(self._pitch, p0 / 120.0, p1 / 120.0)
            self.osc.render(n, TALKER_F0, self._pitch, saw=self._saw)
            for k in range(3):
                self.formants[k].set(self._f[k], TALKER_FORMANT_Q)
                self.formants[k].process(self._saw, self._band)
                add_scaled(voiced, self._band, TALKER_FORMANT_LEVELS[k], self._tmp)
            self._ramp(self._env, a0, a1)
            mul(voiced, self._env)
            voiced *= TALKER_GAIN
        if n0 > 0.0 or n1 > 0.0:
            self.noise.white(self._noise)
            self._ramp(self._env, n0, n1)
            mul(self._noise, self._env)
            add_scaled(voiced, self._noise, TALKER_NOISE_GAIN, self._tmp)

    def process(self, block_size):
        p = self.params
        n = block_size
        out = self.out_jack.buffer
        source = int(p["mic_source"] + 0.5)
        if p["active"] < 0.5:
            # nothing listens: the talker only keeps time
            if source == 1 and self._said is None:
                self._t = (self._t + n / self.sample_rate) % TALKER_PHRASE_S
            out[:] = 0.0
            return
        if source == 1:
            self._talk(n)
            copy_into(out, self._voiced)
        elif source == 2:
            if self._bridge is not None:
                self._zero[:] = 0.0
                self._bridge.process(self._zero, out)
            else:
                feed = jack_signal(self.in_jack)
                if feed is not None:
                    copy_into(out, feed)
                else:
                    out[:] = 0.0
        else:
            out[:] = 0.0
            return
        gain = MIC_GAIN_AT_10 * (p["mic_level"] / 10.0) ** 2
        if gain != 1.0:
            out *= gain
