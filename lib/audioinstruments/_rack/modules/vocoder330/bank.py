# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Vocoder330 bank: a ten-band vocoder, once for the whole keyboard.

The bank reads the ``carrier`` bus (the 8' tone of every key whose vocoder
tablet is on) and the ``mic``. Ten band-pass filters split the mic and ten more,
at the same centres, split the carrier. A follower on each of the mic's bands
rises with ``FOLLOW_ATTACK_S`` and falls with ``FOLLOW_RELEASE_S``, and the
matching band of the carrier is multiplied by it, its gain ramped across the
block so a level that moves does not buzz at the block rate. The ten are summed.

A consonant path adds the mic through a high-pass at ``CONSONANT_HZ``, at the
level of ``vocoder_tone``, but only while the carrier sounds, so the hiss of an
"s" comes through with a key down and never without one.

``vocoder_hold`` freezes the spectrum: the followers stop listening, and each
level falls by ``exp(-block_seconds / HOLD_SAG_S)`` a block, so the held sound
fades over a few seconds. With neither vocoder tablet on (``active`` 0) nothing
runs. The compander and the pre-emphasis around a vocoder's bank cancel in
floating point, so they are not built.
"""

import math
from array import array

import audiobiquad

from ...core.jack import SignalType
from ...core.module import Module
from ...core.signal import BRIDGE_SCALE, add, add_scaled, copy_into, from_int16, mul, np
from ...dsp.biquad import BiquadFilter
from ..voice_mix import QUIET_LEVEL, QUIET_SECONDS
from .filters import DCTracker, clear_filter

#: The ten bands' centres, Hz. The analysis and the synthesis filters share them.
BAND_HZ = (200.0, 280.0, 400.0, 600.0, 900.0, 1300.0, 2000.0, 2800.0, 4000.0, 6000.0)

#: Each band is two band-pass stages in series at this Q: steep skirts keep the
#: neighbouring bands apart, and the Q is low enough that the summed bank
#: ripples by a few dB.
BAND_STAGES = 2
BAND_Q = 2.5

#: The followers: seconds to rise and to fall by a factor of e.
FOLLOW_ATTACK_S = 0.005
FOLLOW_RELEASE_S = 0.030

#: The bank's gain after the ten bands are summed.
VOCODER_GAIN = 28.0

#: Hold: seconds for a held level to fall by a factor of e.
HOLD_SAG_S = 2.5

#: The consonant path: a high-pass of two stages, the gain of ``vocoder_tone`` 10,
#: and the seconds the carrier gate takes to open or close.
CONSONANT_HZ = 4000.0
CONSONANT_STAGES = 2
CONSONANT_GAIN = 1.0
GATE_SMOOTH_S = 0.010

#: A band whose level is below this, now and last block, is not synthesised.
SKIP_LEVEL = 1e-4

#: A mic block this quiet has nothing in it for the followers to hear.
MIC_QUIET = 1e-4


def _peak(buf):
    hi = np.max(buf)
    lo = np.min(buf)
    return hi if hi > -lo else -lo


class Vocoder330Bank(Module):
    NAME = "Vocoder330Bank"
    DISPLAY_NAME = "Vocoder330 Bank"
    HP = 16

    def _build(self):
        sr, n = self.sample_rate, self.block_size
        audio = SignalType.AUDIO
        self.carrier_in = self.add_input("carrier", "Carrier", audio)
        self.mic_in = self.add_input("mic", "Mic", audio)
        self.out_jack = self.add_output("out", "Out", audio)
        self.add_param("vocoder_tone", "Vocoder Tone", default=3.0, max_val=10.0)
        self.add_param("vocoder_hold", "Vocoder Hold", default=0.0)
        #: 0.0 when neither vocoder tablet is on: the bank then runs nothing (set by the patch).
        self.add_param("active", "Active", default=1.0)

        self.analysis = [BiquadFilter(n, sr, "BP", BAND_STAGES, BAND_Q) for _ in BAND_HZ]
        self.synthesis = [BiquadFilter(n, sr, "BP", BAND_STAGES, BAND_Q) for _ in BAND_HZ]
        for i in range(len(BAND_HZ)):
            self.analysis[i].set(BAND_HZ[i], BAND_Q)
            self.synthesis[i].set(BAND_HZ[i], BAND_Q)
        self.consonant = BiquadFilter(n, sr, "HP", CONSONANT_STAGES, 0.707)
        self.consonant.set(CONSONANT_HZ, 0.707)
        for name in ("_band", "_sum", "_ramp", "_cons", "_unit", "_sq"):
            self.add_scratch(name)
        self._fill_unit()
        self.dc = DCTracker(len(BAND_HZ), n, sr)
        self.level = [0.0] * len(BAND_HZ)
        self._prev = [0.0] * len(BAND_HZ)
        self._running = False
        self._gate = 0.0
        self._quiet = 0
        self._rates()

    def _rates(self):
        """The followers' coefficients for this block length."""
        dt = self.block_size / self.sample_rate
        self._dt = dt
        self._attack = math.exp(-dt / FOLLOW_ATTACK_S)
        self._release = math.exp(-dt / FOLLOW_RELEASE_S)
        self._sag = math.exp(-dt / HOLD_SAG_S)
        self._gate_coef = 1.0 - math.exp(-dt / GATE_SMOOTH_S)
        self._quiet_blocks = int(QUIET_SECONDS * self.sample_rate / self.block_size) + 1

    def _fill_unit(self):
        n = self.block_size
        for i in range(n):
            self._unit[i] = (i + 1) / n

    def set_block_size(self, block_size):
        super().set_block_size(block_size)
        sr = self.sample_rate
        self.analysis = [BiquadFilter(block_size, sr, "BP", BAND_STAGES, BAND_Q) for _ in BAND_HZ]
        self.synthesis = [BiquadFilter(block_size, sr, "BP", BAND_STAGES, BAND_Q) for _ in BAND_HZ]
        for i in range(len(BAND_HZ)):
            self.analysis[i].set(BAND_HZ[i], BAND_Q)
            self.synthesis[i].set(BAND_HZ[i], BAND_Q)
        self.consonant = BiquadFilter(block_size, sr, "HP", CONSONANT_STAGES, 0.707)
        self.consonant.set(CONSONANT_HZ, 0.707)
        self.dc = DCTracker(len(BAND_HZ), block_size, sr)
        self._fill_unit()
        self._rates()

    def reset(self):
        for f in self.analysis + self.synthesis:
            clear_filter(f)
        clear_filter(self.consonant)
        self._stop()
        self.out_jack.buffer[:] = 0.0

    def _stop(self):
        for i in range(len(BAND_HZ)):
            self.level[i] = 0.0
            self._prev[i] = 0.0
        self._running = False
        self._gate = 0.0
        self._quiet = 0

    def _ramp_between(self, start, end):
        """``_ramp`` runs from just after ``start`` to ``end`` across the block."""
        ramp = self._ramp
        copy_into(ramp, self._unit)
        ramp *= end - start
        ramp += start

    def _follow(self, mic):
        """Move each band's level toward what the mic's band holds now."""
        sq = self._sq
        n = self.block_size
        for i in range(len(BAND_HZ)):
            self.analysis[i].process(mic, self._band)
            mean = float(np.sum(self._band)) / n
            copy_into(sq, self._band)
            mul(sq, sq)
            # the band's RMS about its own mean: the filter's offset is not the mic
            rms = math.sqrt(max(0.0, float(np.sum(sq)) / n - mean * mean))
            lvl = self.level[i]
            coef = self._attack if rms > lvl else self._release
            self.level[i] = rms + (lvl - rms) * coef

    def process(self, block_size):
        p = self.params
        out = self.out_jack.buffer
        hold = p["vocoder_hold"] >= 0.5
        if p["active"] < 0.5:
            if self._running:
                self._stop()
            if hold:
                for i in range(len(BAND_HZ)):
                    self.level[i] *= self._sag
            out[:] = 0.0
            return
        if not self._running:
            for f in self.analysis + self.synthesis:
                clear_filter(f)
            clear_filter(self.consonant)
            self.dc.clear()
            self._running = True

        carrier = self.carrier_in.get_buffer()
        mic = self.mic_in.get_buffer()
        sounding = _peak(carrier) > QUIET_LEVEL
        self._quiet = 0 if sounding else self._quiet + 1
        carrier_dead = self._quiet >= self._quiet_blocks

        # the followers: they listen unless held; with no key down there is nothing to hear
        # them with, so they rest at zero
        if hold:
            for i in range(len(BAND_HZ)):
                self.level[i] *= self._sag
        elif carrier_dead or _peak(mic) < MIC_QUIET and max(self.level) < SKIP_LEVEL:
            for i in range(len(BAND_HZ)):
                self.level[i] = 0.0
        else:
            self._follow(mic)

        out[:] = 0.0
        if not carrier_dead:
            total = self._sum
            total[:] = 0.0
            for i in range(len(BAND_HZ)):
                l0 = self._prev[i]
                l1 = self.level[i]
                if l0 < SKIP_LEVEL and l1 < SKIP_LEVEL:
                    continue
                self.synthesis[i].process(carrier, self._band)
                self.dc.remove(i, self._band)
                self._ramp_between(l0, l1)
                mul(self._band, self._ramp)
                add(total, self._band)
            add_scaled(out, total, VOCODER_GAIN, self._band)
        for i in range(len(BAND_HZ)):
            self._prev[i] = self.level[i]

        # the consonant path: the mic's hiss, while a key sounds
        target = 1.0 if sounding else 0.0
        g0 = self._gate
        g1 = g0 + (target - g0) * self._gate_coef
        if g1 < 1e-3 and target == 0.0:
            g1 = 0.0
        self._gate = g1
        gain = p["vocoder_tone"] * CONSONANT_GAIN / 10.0
        if gain > 0.0 and (g0 > 0.0 or g1 > 0.0) and _peak(mic) >= MIC_QUIET:
            self.consonant.process(mic, self._cons)
            self._ramp_between(g0, g1)
            mul(self._cons, self._ramp)
            add_scaled(out, self._cons, gain, self._band)

    # -- as a graph fragment ------------------------------------------------------------

    def fragment(self, f):
        """Ten analysis chains on the mic and ten synthesis chains on the carrier, each two
        ``BIQUAD`` band-passes; the consonant path two high-passes. The followers are
        block-rate: after each block the mic's bands are read back, their RMS about the mean
        moves the levels as it does on the rack, and the levels become the synthesis
        ``MIX`` gains, which ramp across the next block. The rack ramps from the last block's
        level to this one's within the block, so the carrier and the mic go through a
        one-block ``FBDELAY`` first and the bank sounds a block late.

        The ported ``synthio.Biquad`` of the rack settles on a constant offset that
        the rack takes out with a tracker; the graph's float ``BIQUAD`` has none."""
        import audiograph as ag

        self._ag = ag
        n = self.block_size
        sr = self.sample_rate
        carrier = f.input(self.carrier_in)
        mic = f.input(self.mic_in)
        if carrier is None or mic is None:
            return False
        self._g_on = f.switch("bank", self.params["active"] >= 0.5)
        grp = self._g_on
        self._g_nodes = []
        self._g_carrier = carrier
        self._g_mic = mic
        f.keep(carrier)
        f.keep(mic)
        frames_ms = 1000.0 * n / sr

        def line(src):
            b = f.buffer()
            node = f.add(ag.FBDELAY, (src,), b, arg=frames_ms + 1.0, group=grp)
            f.set(node, ag.DELAY_MS, frames_ms)
            f.set(node, ag.DELAY_FEEDBACK, 0.0)
            f.set(node, ag.DELAY_MIX, 2.0)
            self._g_nodes.append(node)
            return b

        def chain(src, mode, hz, q, stages):
            for _ in range(stages):
                b = f.buffer()
                node = f.add(ag.BIQUAD, (src,), b, group=grp)
                f.set(node, ag.BIQUAD_MODE, mode)
                f.set(node, ag.BIQUAD_FREQUENCY, hz)
                f.set(node, ag.BIQUAD_Q, q)
                self._g_nodes.append(node)
                src = b
            return src

        self._g_bands = []
        for hz in BAND_HZ:
            band = chain(mic, audiobiquad.BAND_PASS, hz, BAND_Q, BAND_STAGES)
            f.keep(band)
            self._g_bands.append(band)
        c_late = line(carrier)
        m_late = line(mic)
        synth = [chain(c_late, audiobiquad.BAND_PASS, hz, BAND_Q, BAND_STAGES) for hz in BAND_HZ]
        cons = chain(m_late, audiobiquad.HIGH_PASS, CONSONANT_HZ, 0.707, CONSONANT_STAGES)
        b_lo = f.buffer()
        self._n_lo = f.add(ag.MIX, tuple(synth[:8]), b_lo, group=grp)
        self._n_out = f.add(
            ag.MIX, (b_lo,) + tuple(synth[8:]) + (cons,), f.output(self.out_jack), group=grp
        )
        f.set(self._n_out, 0, 1.0)
        self._g_i16 = array("h", bytes(2 * n))
        self._g_unit = self._band  # float scratch
        self._g_floor = QUIET_LEVEL * BRIDGE_SCALE
        self._g_mic_quiet = MIC_QUIET * BRIDGE_SCALE
        self._g_set = [None] * (len(BAND_HZ) + 1)
        self._graph_clear()
        f.bind(("active",), self._graph_active)
        f.bind(("vocoder_tone",), self._graph_gains)
        f.after_run(self._graph_after)
        f.on_reset(self._graph_clear)

    def _graph_clear(self):
        for i in range(len(BAND_HZ)):
            self.level[i] = 0.0
            self._prev[i] = 0.0
        self._gate = 0.0
        self._quiet = 0
        self._g_set = [None] * (len(BAND_HZ) + 1)
        f = self._fragment
        if f is not None and getattr(self, "_g_nodes", None):
            for node in self._g_nodes:
                f.reset(node)
            self._graph_gains()

    def _graph_active(self):
        f = self._fragment
        on = self.params["active"] >= 0.5
        if on != getattr(self, "_g_was_on", None):
            self._g_was_on = on
            f.enable("bank", on)
            if not on:
                self._stop()
            self._graph_clear()

    def _graph_gains(self):
        """The synthesis ``MIX`` gains at the levels the last block ended at, and the
        consonant gain at the gate's."""
        f = self._fragment
        for i in range(len(BAND_HZ)):
            k = self.level[i] * VOCODER_GAIN
            if k != self._g_set[i]:
                self._g_set[i] = k
                if i < 8:
                    f.set(self._n_lo, i, k)
                else:
                    f.set(self._n_out, 1 + i - 8, k)
        gain = self._gate * self.params["vocoder_tone"] * CONSONANT_GAIN / 10.0
        if gain != self._g_set[-1]:
            self._g_set[-1] = gain
            f.set(self._n_out, 3, gain)

    def _graph_after(self, sounding):
        """The followers and the consonant gate, on the block that just rendered."""
        f = self._fragment
        if self.params["active"] < 0.5:
            if self.params["vocoder_hold"] >= 0.5:
                for i in range(len(BAND_HZ)):
                    self.level[i] *= self._sag
            self._graph_gains()
            return
        hold = self.params["vocoder_hold"] >= 0.5
        sounding_now = f.peak(self._g_carrier) > self._g_floor
        self._quiet = 0 if sounding_now else self._quiet + 1
        dead = self._quiet >= self._quiet_blocks
        if hold:
            for i in range(len(BAND_HZ)):
                self.level[i] *= self._sag
        elif dead or f.peak(self._g_mic) < self._g_mic_quiet and max(self.level) < SKIP_LEVEL:
            for i in range(len(BAND_HZ)):
                self.level[i] = 0.0
        else:
            n = self.block_size
            band = self._g_unit
            sq = self._sq
            i16 = self._g_i16
            for i in range(len(BAND_HZ)):
                f.read(self._g_bands[i], i16)
                from_int16(band, i16)
                mean = float(np.sum(band)) / n
                copy_into(sq, band)
                mul(sq, sq)
                rms = math.sqrt(max(0.0, float(np.sum(sq)) / n - mean * mean))
                lvl = self.level[i]
                coef = self._attack if rms > lvl else self._release
                self.level[i] = rms + (lvl - rms) * coef
        target = 1.0 if sounding_now else 0.0
        g1 = self._gate + (target - self._gate) * self._gate_coef
        if g1 < 1e-3 and target == 0.0:
            g1 = 0.0
        self._gate = g1
        self._graph_gains()
