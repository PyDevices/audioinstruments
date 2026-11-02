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
    MAX_DELAY_MS,
    VIB_CENTRE_MS,
    VIB_START_HZ,
    VIB_TABLE_LEN,
    AlignCore,
    EnsembleCore,
    EnsembleLine,
    VibratoCore,
    _sine_table,
    _Sweep,
    sweep_table,
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
        #: 0.0 when no tablet plays that section: a graph skips its nodes (set by the patch).
        self.add_param("choir_on", "Choir On", default=1.0)
        self.add_param("vocoder_on", "Vocoder On", default=1.0)

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

    # -- as a graph fragment ------------------------------------------------------------

    def fragment(self, f):
        """The strings' low-pass, the choir's seven band-passes, the vibratos, the four
        ensemble lines and the DC block are ``BIQUAD``, ``FBDELAY`` and ``PHASER`` nodes
        joined by ``MIX`` nodes. A ``MIX`` gain that moves ramps across the block, which is
        the rack's cross-fade between the ensemble and the plain delay.

        The graph has no bridges, so every path is 512 frames sooner than the rack's. The
        bank sounds one block late (see ``Vocoder330Bank``), so the other paths are
        delayed that block too and come out together. The lines' sweeps start where the rack's
        do, after the bridge's 256 frames of silence (``prime``)."""
        import audiograph as ag

        self._ag = ag
        n = self.block_size
        sr = self.sample_rate
        strings = f.input(self.strings_in)
        a, b, c = (f.input(j) for j in (self.choir_a_in, self.choir_b_in, self.choir_c_in))
        voc = f.input(self.vocoder_in)
        mic = f.input(self.mic_in)
        if None in (strings, a, b, c, voc, mic) or not f.is_control(self.vib_in):
            return False
        block_ms = 1000.0 * n / sr

        def node(kind, src, out=None, arg=0.0, group=None):
            wire = f.buffer() if out is None else out
            return f.add(kind, src, wire, arg=arg, group=group), wire

        def delay(src, ms, out=None, group=None):
            nd, wire = node(ag.FBDELAY, (src,), out, arg=MAX_DELAY_MS, group=group)
            f.set(nd, ag.DELAY_MS, ms)
            f.set(nd, ag.DELAY_FEEDBACK, 0.0)
            f.set(nd, ag.DELAY_MIX, 2.0)
            return nd, wire

        # strings
        self._n_tone, w = node(ag.BIQUAD, (strings,))
        f.set(self._n_tone, ag.BIQUAD_MODE, audiobiquad.LOW_PASS)
        f.set(self._n_tone, ag.BIQUAD_Q, TONE_Q)
        self._n_strings, w = node(ag.MIX, (w,))
        centre_ms = VIB_CENTRE_MS
        _, s2 = delay(w, centre_ms + block_ms)
        # choir: the sums, the seven filters, one gain (no choir tablet down: skipped)
        self._g_choir = f.switch("choir")
        self._n_ab, ab = node(ag.MIX, (a, b), group=self._g_choir)
        self._n_abc, abc = node(ag.MIX, (ab, c), group=self._g_choir)
        for nd in (self._n_ab, self._n_abc):
            for i in range(2):
                f.set(nd, i, 1.0)
        f.set(self._n_abc, 1, 1.0)
        bands = []
        for hz, feed in zip(CHOIR_FILTERS_HZ, CHOIR_FEEDS):
            src = {"a": a, "b": b, "c": c, "ab": ab, "abc": abc}[feed]
            nd, wire = node(ag.BIQUAD, (src,), group=self._g_choir)
            f.set(nd, ag.BIQUAD_MODE, audiobiquad.BAND_PASS)
            f.set(nd, ag.BIQUAD_FREQUENCY, hz)
            f.set(nd, ag.BIQUAD_Q, CHOIR_Q)
            bands.append(wire)
        self._n_choir, choir = node(ag.MIX, tuple(bands), group=self._g_choir)
        # vibrato: a sine-swept wet line, the choir's one block later than the vocoder's
        self._g_vib_tables = [_sine_table(VIB_TABLE_LEN), _sine_table(VIB_TABLE_LEN)]
        self._n_vib = []
        self._g_vibrato = f.switch("vibrato")
        self._n_voc, voc_g = node(ag.MIX, (voc,))
        vib_wires = []
        for k, (src, extra) in enumerate(((choir, block_ms), (voc_g, 0.0))):
            nd, wire = delay(src, VIB_CENTRE_MS + extra, group=self._g_vibrato)
            f.set(nd, ag.DELAY_WOW_HZ, 5.0)
            f.set(nd, ag.DELAY_WOW_DEPTH_MS, 0.0)
            f.table(nd, self._g_vib_tables[k])
            self._n_vib.append((nd, extra))
            vib_wires.append(wire)
        choir_v, voc_v = vib_wires
        # the ensemble takes the strings and what is switched to it; the rest goes round
        self._n_ens_in, ens_in = node(ag.MIX, (s2, choir_v, voc_v))
        self._n_byp, byp = node(ag.MIX, (choir_v, voc_v))
        # the direct mic, as late as the rest
        self._g_direct = f.switch("direct")
        _, mic_d = delay(mic, VIB_CENTRE_MS + block_ms, group=self._g_direct)
        # the lines (a group of their own, so the voices' primes leave them alone)
        self._g_lines = f.switch("lines")
        self._g_tables = []
        self._n_lines = []
        lines = []
        for spec in ensemble_lines():
            sweep = _Sweep(spec, ENSEMBLE_SLOW_MS, ENSEMBLE_FAST_MS, "triangle")
            tbl, peak = sweep_table(sweep, ENSEMBLE_TABLE_LEN)
            self._g_tables.append(tbl)
            nd, wire = node(ag.FBDELAY, (ens_in,), None, MAX_DELAY_MS, self._g_lines)
            f.set(nd, ag.DELAY_MS, ENSEMBLE_CENTRE_MS)
            f.set(nd, ag.DELAY_FEEDBACK, 0.0)
            f.set(nd, ag.DELAY_MIX, spec.mix)
            f.set(nd, ag.DELAY_WOW_HZ, spec.slow_hz)
            f.set(nd, ag.DELAY_WOW_DEPTH_MS, peak)
            f.set(nd, ag.DELAY_DAMPING_HZ, ENSEMBLE_TONE_HZ)
            f.table(nd, tbl)
            self._n_lines.append(nd)
            lines.append(wire)
        scale = f.take_master_scale((self.left_out, self.right_out))
        self._g_scale = 1.0 if scale is None else scale
        self._n_dc = []
        self._n_sides = []
        for jack, side in ((self.left_out, "left"), (self.right_out, "right")):
            used = [i for i, spec in enumerate(ensemble_lines()) if getattr(spec, side) != 0.0]
            side_wire = f.buffer()
            nd = f.add(ag.MIX, tuple(lines[i] for i in used) + (byp, mic_d), side_wire)
            for j, i in enumerate(used):
                f.set(nd, j, getattr(ensemble_lines()[i], side))
            f.set(nd, len(used), 1.0)
            self._n_sides.append((nd, len(used) + 1))
            lp = f.buffer()
            dc = f.add(ag.PHASER, (side_wire,), lp, arg=1.0)
            f.set(dc, ag.PHASER_FREQUENCY, DC_HZ)
            f.set(dc, ag.PHASER_FEEDBACK, 0.0)
            f.set(dc, ag.PHASER_MIX, 0.5)
            self._n_dc.append(dc)
            out = f.add(ag.MIX, (side_wire, lp), f.output(jack))
            f.set(out, 0, self._g_scale)
            f.set(out, 1, -self._g_scale)
        self._g_vib = 1.0
        self._g_ens = [0.0, 0.0]  # the shares of the choir and the vocoder the ensemble takes
        f.watch(self.vib_in, self._graph_vib)
        f.bind(
            (
                "strings_tone",
                "strings_level",
                "voice_level",
                "direct_mic",
                "voice_ensemble",
                "vocoder_ensemble",
                "vib_depth",
                "vib_rate",
                "choir_on",
                "vocoder_on",
            ),
            self._graph_params,
        )
        f.on_reset(self._graph_reset)
        f.prime(self._graph_prime)

    def _graph_vib(self, value):
        self._g_vib = value
        self._graph_params()

    def _graph_params(self):
        p = self.params
        f = self._fragment
        ag = self._ag
        tone_hz = TONE_MIN_HZ * ((TONE_MAX_HZ / TONE_MIN_HZ) ** (p["strings_tone"] / 10.0))
        f.set(self._n_tone, ag.BIQUAD_FREQUENCY, tone_hz)
        f.set(self._n_strings, 0, STRINGS_GAIN * LEVEL_SCALE * p["strings_level"])
        voice_gain = LEVEL_SCALE * p["voice_level"]
        for i in range(len(CHOIR_FILTERS_HZ)):
            f.set(self._n_choir, i, CHOIR_GAIN * voice_gain)
        f.set(self._n_voc, 0, voice_gain)
        rate = VIB_MIN_HZ * ((VIB_MAX_HZ / VIB_MIN_HZ) ** (p["vib_rate"] / 10.0))
        semitones = VIB_MAX_SEMITONES * p["vib_depth"] / 10.0 * self._g_vib
        swing = (2.0 ** (semitones / 12.0) - 1.0) / (2.0 * math.pi * rate)
        depth = max(0.0, min(VIB_CENTRE_MS * 0.9, swing * 1000.0))
        ag = self._ag
        for nd, _ in self._n_vib:
            f.set(nd, ag.DELAY_WOW_HZ, rate)
            f.set(nd, ag.DELAY_WOW_DEPTH_MS, depth)
        k_choir = 1.0 if p["voice_ensemble"] >= 0.5 else 0.0
        k_voc = 1.0 if p["vocoder_ensemble"] >= 0.5 else 0.0
        f.set(self._n_ens_in, 1, k_choir)
        f.set(self._n_ens_in, 2, k_voc)
        f.set(self._n_byp, 0, 1.0 - k_choir)
        f.set(self._n_byp, 1, 1.0 - k_voc)
        f.set(self._n_ens_in, 0, 1.0)
        direct = LEVEL_SCALE * p["direct_mic"]
        for nd, last in self._n_sides:
            f.set(nd, last, direct)
        choir_on = p["choir_on"] >= 0.5
        f.enable("choir", choir_on)
        f.enable("vibrato", choir_on or p["vocoder_on"] >= 0.5)
        f.enable("direct", direct > 0.0)

    def _graph_prime(self, run):
        """Put the sweeps where the rack's are. The graph is sooner than the rack, so a line's
        sweep starts that much ahead: the ensemble's lines run ``2 * LATENCY_FRAMES - block``
        frames before the first block.

        The vibrato's sweep is set by its line's history instead. The rack's line ran one
        chunk of silence at ``VIB_START_HZ`` when its bridge was built, so its sweep is
        ``VIB_START_HZ * LATENCY_FRAMES / sample_rate`` of a turn along when the first block
        arrives; and the graph's choir comes one block later than the rack's line hears it,
        so the graph's sweep starts ``rate * block / sample_rate`` of a turn behind that. The
        vibrato runs the difference in one block at a wow rate scaled to cover it. The rate
        is the one set now: a ``vib_rate`` moved before the first block leaves the sweep
        ``(new - old) * block / sample_rate`` of a turn from the rack's."""
        n = self.block_size
        f = self._fragment
        ag = self._ag
        vib = tuple(nd for nd, _ in self._n_vib)
        ens = tuple(self._n_lines)
        ahead = max(0, 2 * LATENCY_FRAMES - n) // n
        for _ in range(max(0, ahead - 1)):
            run(1 << self._g_lines, ens)
        sr = self.sample_rate
        rates = [f.get(nd, ag.DELAY_WOW_HZ) for nd in vib]
        for nd, hz in zip(vib, rates):
            turns = (VIB_START_HZ * LATENCY_FRAMES - hz * n) / sr
            turns -= math.floor(turns)
            f.set(nd, ag.DELAY_WOW_HZ, (turns or 1.0) * sr / n)
        run((1 << self._g_lines) | (1 << self._g_vibrato), ens + vib)
        for nd, hz in zip(vib, rates):
            f.set(nd, ag.DELAY_WOW_HZ, hz)

    def _graph_reset(self):
        f = self._fragment
        for nd in [self._n_tone] + self._n_lines + self._n_dc + [nd for nd, _ in self._n_vib]:
            f.reset(nd)
