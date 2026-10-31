# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Vocoder330 output: the rest of the shared section, filtered once for the keyboard.

It reads the four tone buses (``strings``, ``choir_a``, ``choir_b``, ``choir_c``),
the bank's ``vocoder``, the ``mic`` and the keys' ``vib``, and writes ``left`` and
``right``:

1. The strings go through a low-pass (``strings_tone``) and ``strings_level``,
   then an align line, then the ensemble. They always go through the ensemble.
2. The choir goes through seven band-pass filters, one at each of
   ``CHOIR_FILTERS_HZ``, each fed the sum of the buses that use it; then
   ``voice_level``, then the vibrato, then the ensemble if ``voice_ensemble`` is on
   and a plain delay otherwise.
3. The vocoder goes through ``voice_level``, a vibrato of its own and the same two
   ways, by ``vocoder_ensemble``.
4. The direct mic is the mic times ``direct_mic``, delayed to match, with no
   vibrato and no ensemble.

Every path comes out ``LATENCY_FRAMES`` twice plus the vibrato's centre late, so
the sections stay aligned and a tablet switched while a note sounds never jumps in
time. The ensemble's lines add a few milliseconds more to the sound they sweep;
the first line of each side also passes the signal through at that fixed delay,
which is where an impulse first arrives.
"""

import math

import audiobiquad

from ...core.bridge import NodeBridge, biquad_kwargs
from ...core.jack import SignalType
from ...core.module import Module
from ...core.signal import add, add_scaled, copy_into, mul, np, scale, scaled_into
from ...dsp.biquad import BiquadFilter
from ...dsp.ensemble import (
    LATENCY_FRAMES,
    AlignCore,
    EnsembleCore,
    EnsembleLine,
    VibratoCore,
)
from .filters import DCTracker, clear_filter

#: The strings' tone control is a 12 dB per octave low-pass, 800 Hz to 12 kHz, exponential.
TONE_MIN_HZ = 800.0
TONE_MAX_HZ = 12000.0
TONE_Q = 0.707

#: Each level slider is linear: this much gain a step, 0 to 10.
LEVEL_SCALE = 0.1

#: The gain of each section's sum on its way to the master, before its level slider.
STRINGS_GAIN = 2.0
CHOIR_GAIN = 2.5

#: The human voice's seven tone filters, Hz: F1 to F7.
CHOIR_FILTERS_HZ = (200.0, 230.0, 600.0, 900.0, 1300.0, 2800.0, 3300.0)
CHOIR_Q = 4.0

#: Which of the three choir buses (a, b, c) feed each tone filter: lower male 8' (a) uses
#: F1, F3, F4, F6; lower male 4' and upper male 8' (b) use F2, F3, F4, F6; upper female 4'
#: (c) uses F3, F4, F5, F7. A filter is fed the sum of the buses that use it.
CHOIR_FEEDS = ("a", "b", "abc", "abc", "c", "ab", "c")

#: The vibrato's pitch swing at ``vib_depth`` 10, in semitones either way, and its rate
#: range (``vib_rate`` 0 to 10, exponential), Hz.
VIB_MAX_SEMITONES = 0.5
VIB_MIN_HZ = 2.0
VIB_MAX_HZ = 9.0

#: The ensemble: four lines, two a side. Line A sweeps with a slow triangle of 3.9 s and
#: line B 4.6 s, each carrying 26 fast sines (150 ms and 176.9 ms). The right side's
#: sweeps are the left's upside down. The first line of a side is the dry plus its wet
#: and the second its wet alone, each at ENSEMBLE_LEVEL into its side.
ENSEMBLE_SLOW_S = (3.9, 4.6)
ENSEMBLE_FAST_CYCLES = 26
ENSEMBLE_CENTRE_MS = 4.0
ENSEMBLE_SLOW_MS = 1.6
ENSEMBLE_FAST_MS = 0.12
ENSEMBLE_TONE_HZ = 8000.0
ENSEMBLE_TABLE_LEN = 4096
ENSEMBLE_LEVEL = 1.0 / 3.0

#: Corner frequency of the DC block that ends the chain, Hz: what the tone filters
#: and the ensemble leave of an offset is taken out here.
DC_HZ = 10.0

#: A bus this quiet is silence to a filter: below one count of the 16-bit wire.
SILENT = 3e-5


def ensemble_lines():
    """The four lines of the ensemble."""
    slow_a, slow_b = ENSEMBLE_SLOW_S
    cycles = ENSEMBLE_FAST_CYCLES
    return (
        EnsembleLine(1.0 / slow_a, cycles, 0.0, left=ENSEMBLE_LEVEL, mix=1.0),
        EnsembleLine(1.0 / slow_b, cycles, 0.0, left=ENSEMBLE_LEVEL, mix=2.0),
        EnsembleLine(1.0 / slow_a, cycles, 0.5, right=ENSEMBLE_LEVEL, mix=1.0),
        EnsembleLine(1.0 / slow_b, cycles, 0.5, right=ENSEMBLE_LEVEL, mix=2.0),
    )


def ensemble_core(sample_rate, block_size):
    """The Vocoder330's ensemble, on from the start."""
    return EnsembleCore(
        sample_rate,
        block_size,
        lines=ensemble_lines(),
        centre_ms=ENSEMBLE_CENTRE_MS,
        slow_depth_ms=ENSEMBLE_SLOW_MS,
        fast_depth_ms=ENSEMBLE_FAST_MS,
        tone_hz=ENSEMBLE_TONE_HZ,
        table_len=ENSEMBLE_TABLE_LEN,
        slow_shape="triangle",
        on=True,
    )


def _peak(buf):
    hi = np.max(buf)
    lo = np.min(buf)
    return hi if hi > -lo else -lo


class Vocoder330Output(Module):
    NAME = "Vocoder330Output"
    DISPLAY_NAME = "Vocoder330 Output"
    HP = 14
    LATENCY_FRAMES = LATENCY_FRAMES

    def _build(self):
        audio, cv = SignalType.AUDIO, SignalType.CV
        self.strings_in = self.add_input("strings", "Strings", audio)
        self.choir_a_in = self.add_input("choir_a", "Choir A", audio)
        self.choir_b_in = self.add_input("choir_b", "Choir B", audio)
        self.choir_c_in = self.add_input("choir_c", "Choir C", audio)
        self.vocoder_in = self.add_input("vocoder", "Vocoder", audio)
        self.mic_in = self.add_input("mic", "Mic", audio)
        self.vib_in = self.add_input("vib", "Vibrato", cv)
        self.left_out = self.add_output("left", "Left", audio)
        self.right_out = self.add_output("right", "Right", audio)

        self.add_param("strings_tone", "Strings Tone", default=6.0, max_val=10.0)
        self.add_param("strings_level", "Strings Level", default=7.0, max_val=10.0)
        self.add_param("voice_level", "Voice Level", default=7.0, max_val=10.0)
        self.add_param("direct_mic", "Direct Mic", default=0.0, max_val=10.0)
        self.add_param("voice_ensemble", "Voice Ensemble", default=0.0)
        self.add_param("vocoder_ensemble", "Vocoder Ensemble", default=0.0)
        self.add_param("vib_depth", "Vibrato Depth", default=3.0, max_val=10.0)
        self.add_param("vib_rate", "Vibrato Rate", default=5.0, max_val=10.0)

        for name in (
            "_s1",
            "_s2",
            "_ab",
            "_abc",
            "_band",
            "_choir",
            "_choir_v",
            "_voc",
            "_voc_v",
            "_ens",
            "_byp",
            "_mic",
            "_mic_d",
            "_tmp",
            "_unit",
            "_dc_l",
            "_dc_r",
        ):
            self.add_scratch(name)
        self._build_cores()
        self._ens_choir = 0.0  # the ensemble's share of the choir and of the vocoder, last block
        self._ens_voc = 0.0
        self._need = [False] * len(CHOIR_FEEDS)
        self._used = [False] * len(CHOIR_FEEDS)
        self._cleared = [True] * len(CHOIR_FEEDS)

    def _build_cores(self):
        sr, n = self.sample_rate, self.block_size
        self.tone = BiquadFilter(n, sr, "LP", 1, TONE_Q)
        self.choir_filters = [BiquadFilter(n, sr, "BP", 1, CHOIR_Q) for _ in CHOIR_FILTERS_HZ]
        for f, hz in zip(self.choir_filters, CHOIR_FILTERS_HZ):
            f.set(hz, CHOIR_Q)
        self.vibrato_choir = VibratoCore(sr, n)
        self.vibrato_voc = VibratoCore(sr, n)
        centre = self.vibrato_choir.centre_frames
        self.align = AlignCore(sr, n, extra_frames=centre)
        self.align_mic = AlignCore(sr, n, extra_frames=LATENCY_FRAMES + centre)
        self.ensemble = ensemble_core(sr, n)
        self.choir_dc = DCTracker(len(CHOIR_FILTERS_HZ), n, sr)
        self._dc_bridges = []
        for _ in range(2):
            node = audiobiquad.AllPass(
                stages=1,
                frequency=DC_HZ,
                feedback=0.0,
                mix=0.5,
                sample_rate=sr,
                channel_count=1,
                **biquad_kwargs(n),
            )
            self._dc_bridges.append(NodeBridge(n, sr).chain(node))
        self._fill_unit()

    def _fill_unit(self):
        n = self.block_size
        for i in range(n):
            self._unit[i] = (i + 1) / n

    def set_block_size(self, block_size):
        super().set_block_size(block_size)
        self._build_cores()

    def reset(self):
        clear_filter(self.tone)
        for f in self.choir_filters:
            clear_filter(f)
        self.choir_dc.clear()
        for bridge in self._dc_bridges:
            bridge.reset()
        for core in (
            self.vibrato_choir,
            self.vibrato_voc,
            self.align,
            self.align_mic,
            self.ensemble,
        ):
            core.reset()
        self._ens_choir = 0.0
        self._ens_voc = 0.0
        for i in range(len(self._need)):
            self._need[i] = False

    def _add_ramped(self, dst, src, k0, k1):
        """dst += src * (k0 to k1 across the block)."""
        if k0 == k1:
            add_scaled(dst, src, k1, self._tmp)
            return
        tmp = self._tmp
        copy_into(tmp, self._unit)
        tmp *= k1 - k0
        tmp += k0
        mul(tmp, src)
        add(dst, tmp)

    def _choir_sum(self):
        """The choir buses through the seven tone filters into ``_choir``."""
        a = self.choir_a_in.get_buffer()
        b = self.choir_b_in.get_buffer()
        c = self.choir_c_in.get_buffer()
        loud_a = _peak(a) > SILENT
        loud_b = _peak(b) > SILENT
        loud_c = _peak(c) > SILENT
        out = self._choir
        out[:] = 0.0
        need = self._need
        used = self._used
        for j in range(len(CHOIR_FEEDS)):
            feed = CHOIR_FEEDS[j]
            used[j] = (
                (loud_a and "a" in feed) or (loud_b and "b" in feed) or (loud_c and "c" in feed)
            )
        if not (any(used) or any(need)):
            return
        copy_into(self._ab, a)
        add(self._ab, b)
        copy_into(self._abc, self._ab)
        add(self._abc, c)
        for j in range(len(CHOIR_FEEDS)):
            if used[j] or need[j]:
                feed = CHOIR_FEEDS[j]
                if feed == "a":
                    src = a
                elif feed == "b":
                    src = b
                elif feed == "c":
                    src = c
                elif feed == "ab":
                    src = self._ab
                else:
                    src = self._abc
                self.choir_filters[j].process(src, self._band)
                self.choir_dc.remove(j, self._band)
                add(out, self._band)
                self._cleared[j] = False
            elif not self._cleared[j]:
                clear_filter(self.choir_filters[j])  # idle: no stale offset for the next chord
                self.choir_dc.clear(j)
                self._cleared[j] = True
        for j in range(len(CHOIR_FEEDS)):
            need[j] = used[j]

    def process(self, block_size):
        p = self.params
        n = block_size

        # strings: tone, level, align
        tone_hz = TONE_MIN_HZ * ((TONE_MAX_HZ / TONE_MIN_HZ) ** (p["strings_tone"] / 10.0))
        self.tone.set(tone_hz, TONE_Q)
        self.tone.process(self.strings_in.get_buffer(), self._s1)
        scale(self._s1, STRINGS_GAIN * LEVEL_SCALE * p["strings_level"])
        self.align.render(self._s1, self._s2)

        # choir and vocoder: level, vibrato
        voice_gain = LEVEL_SCALE * p["voice_level"]
        self._choir_sum()
        scale(self._choir, CHOIR_GAIN * voice_gain)
        scaled_into(self._voc, self.vocoder_in.get_buffer(), voice_gain)
        rate = VIB_MIN_HZ * ((VIB_MAX_HZ / VIB_MIN_HZ) ** (p["vib_rate"] / 10.0))
        vib = float(self.vib_in.get_buffer()[n - 1]) if self.vib_in.is_connected else 1.0
        semitones = VIB_MAX_SEMITONES * p["vib_depth"] / 10.0 * vib
        swing = (2.0 ** (semitones / 12.0) - 1.0) / (2.0 * math.pi * rate)  # seconds of delay
        self.vibrato_choir.set(rate, swing * 1000.0)
        self.vibrato_voc.set(rate, swing * 1000.0)
        self.vibrato_choir.render(self._choir, self._choir_v)
        self.vibrato_voc.render(self._voc, self._voc_v)

        # the ensemble takes the strings, and the choir and the vocoder if their tablets are on;
        # what is not is plainly delayed to match
        k_choir = 1.0 if p["voice_ensemble"] >= 0.5 else 0.0
        k_voc = 1.0 if p["vocoder_ensemble"] >= 0.5 else 0.0
        copy_into(self._ens, self._s2)
        self._byp[:] = 0.0
        self._add_ramped(self._ens, self._choir_v, self._ens_choir, k_choir)
        self._add_ramped(self._ens, self._voc_v, self._ens_voc, k_voc)
        self._add_ramped(self._byp, self._choir_v, 1.0 - self._ens_choir, 1.0 - k_choir)
        self._add_ramped(self._byp, self._voc_v, 1.0 - self._ens_voc, 1.0 - k_voc)
        self._ens_choir = k_choir
        self._ens_voc = k_voc
        left = self.left_out.buffer
        right = self.right_out.buffer
        self.ensemble.render(self._ens, self._byp, left, right)

        # the direct mic: no vibrato and no ensemble, delayed to match
        self.align_mic.render(self.mic_in.get_buffer(), self._mic_d)
        direct = LEVEL_SCALE * p["direct_mic"]
        if direct != 0.0:
            add_scaled(left, self._mic_d, direct, self._tmp)
            add_scaled(right, self._mic_d, direct, self._tmp)

        # the DC block: each side less its 10 Hz low-pass
        self._dc_bridges[0].process(left, self._dc_l)
        add_scaled(left, self._dc_l, -1.0, self._tmp)
        self._dc_bridges[1].process(right, self._dc_r)
        add_scaled(right, self._dc_r, -1.0, self._tmp)
