# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""StringEnsemble monophonic bass section.

Compiled to a graph, the bass is a group of its own that runs while a bass key
is down or its envelope is still falling: two ``OSC`` nodes on a pitch wire
that holds the last bass key, their ``MIX``, a one-stage ``PHASER`` for the
tone filter, an ``ENV`` and a ``VCA`` for the volume and velocity. While the
group is off the oscillators stand still, as the rack leaves them. The rack
renders nothing in the block its envelope runs out in, so the group stops a
block early: Python follows the release in floats and works out whether it
ends in the next block.
"""

import math
from array import array

import audiobiquad

from ...core.bridge import NodeBridge, biquad_kwargs
from ...core.jack import SignalType
from ...core.module import Module
from ...core.signal import BASE_FREQ_C4, BRIDGE_SCALE, add, copy_into, scaled_into
from ...dsp.blocks import steps_to_reach
from ...dsp.envelope import RELEASE_TOLERANCE, EnvelopeCore
from ...dsp.oscillator import OscillatorCore
from .._util import jack_signal
from ..compact_organ.voice import PITCH_OCTAVES
from .envelope import ATTACK_TO_PEAK, CRESCENDO_RANGE, slider_time

#: The bottom 20 keys of a 49-key keyboard starting at MIDI 36 (C2 to G3).
BASS_LOW = 36
BASS_HIGH = 55

#: Cello 8' pulse width: 50% square wave.
CELLO_WIDTH = 0.5

#: Fixed release time for the bass in seconds.
BASS_RELEASE_S = 0.15

#: Fixed one-pole low-pass cutoff frequency for the bass in Hz.
BASS_TONE_HZ = 1000.0

#: Bass output level scaling.
BASS_SCALE = 1.0

#: Velocity sensitivity depth in the bass: at max vel_vca, velocity scales 0.2 to 1.0.
VEL_DEPTH = 0.8


class StringEnsembleBass(Module):
    """Monophonic bass module for the lowest held key on keys 36 to 55."""

    NAME = "StringEnsembleBass"
    DISPLAY_NAME = "StringEnsemble Bass"
    HP = 12

    def _build(self):
        sr, n = self.sample_rate, self.block_size
        self.osc16 = OscillatorCore(sr)
        self.osc8 = OscillatorCore(sr)
        self.env = EnvelopeCore(sr, n)
        self._build_filters(n)

        self._velocity = 1.0

        cv, gate, audio = SignalType.CV, SignalType.GATE, SignalType.AUDIO
        self.pitch_in = self.add_input("pitch", "Pitch", cv)
        self.note_in = self.add_input("note", "Note", cv)
        self.gate_in = self.add_input("gate", "Gate", gate)
        self.vel_in = self.add_input("velocity", "Velocity", cv)
        self.audio_out = self.add_output("out", "Bass Out", audio)

        self.add_param("contrabass", "Contra-bass 16'", default=0.0)
        self.add_param("cello", "Cello 8'", default=0.0)
        self.add_param("bass_volume", "Volume Bass", default=0.5)
        self.add_param("crescendo", "Crescendo", default=0.4)
        self.add_param("tune", "Tune", default=0.0, min_val=-50.0, max_val=50.0)
        self.add_param("vel_vca", "Velocity VCA", default=0.0)

        for name in (
            "_saw16",
            "_pulse8",
            "_mix",
            "_filtered",
            "_cv",
            "_last_pitch",
            "_bass_gate_buf",
            "_env_buf",
            "_tmp",
        ):
            self.add_scratch(name)

    def _build_filters(self, n):
        self._filter_node = audiobiquad.AllPass(
            stages=1,
            frequency=BASS_TONE_HZ,
            feedback=0.0,
            mix=0.5,
            sample_rate=self.sample_rate,
            channel_count=1,
            **biquad_kwargs(n),
        )
        self.bridge = NodeBridge(n, self.sample_rate).chain(self._filter_node)

    def set_block_size(self, block_size):
        super().set_block_size(block_size)
        self.env.set_block_size(block_size)
        self._build_filters(block_size)

    def reset(self):
        self.env.reset()
        self.bridge.reset()
        self._last_pitch[:] = 0.0

    def process(self, block_size):
        n = block_size
        p = self.params

        gate_buf = jack_signal(self.gate_in)
        gate_high = gate_buf is not None and gate_buf[n - 1] > 0.5

        note_buf = jack_signal(self.note_in)
        if note_buf is not None:
            note_cv = float(note_buf[n - 1])
            key = 60.0 + note_cv * 120.0
            is_bass_key = (BASS_LOW - 0.5) <= key <= (BASS_HIGH + 0.5)
        else:
            is_bass_key = False

        bass_gate_high = gate_high and is_bass_key

        if bass_gate_high:
            vel_buf = jack_signal(self.vel_in)
            if vel_buf is not None:
                self._velocity = float(vel_buf[0])
            pitch_buf = jack_signal(self.pitch_in)
            if pitch_buf is not None:
                copy_into(self._last_pitch, pitch_buf)
            else:
                self._last_pitch[:] = 0.0
            self._bass_gate_buf[:] = 1.0
        else:
            self._bass_gate_buf[:] = 0.0

        attack = slider_time(p["crescendo"], CRESCENDO_RANGE) / ATTACK_TO_PEAK
        self.env.set_times(attack, 0.01, 1.0, BASS_RELEASE_S)
        self.env.render(self._bass_gate_buf, self._env_buf)

        if self.env.state == 0 and not bass_gate_high:
            self.audio_out.buffer[:] = 0.0
            return

        contrabass = p["contrabass"] >= 0.5
        cello = p["cello"] >= 0.5
        if not (contrabass or cello):
            self.audio_out.buffer[:] = 0.0
            return

        cv = self._cv
        copy_into(cv, self._last_pitch)
        tune = p["tune"]
        if tune != 0.0:
            cv += tune / 12000.0

        base = BASE_FREQ_C4
        if contrabass:
            self.osc16.render(n, base * 0.5, cv, saw=self._saw16)
        if cello:
            self.osc8.render(n, base, cv, pulse_width=CELLO_WIDTH, pulse=self._pulse8)
            self._pulse8 -= CELLO_WIDTH - 0.5

        mix = self._mix
        mix[:] = 0.0
        if contrabass:
            add(mix, self._saw16)
        if cello:
            add(mix, self._pulse8)

        self.bridge.process(mix, self._filtered)
        self._filtered *= self._env_buf

        vel_vca = p["vel_vca"]
        vel_factor = 1.0 - vel_vca * VEL_DEPTH * (1.0 - self._velocity)
        gain = p["bass_volume"] * BASS_SCALE * vel_factor
        scaled_into(self.audio_out.buffer, self._filtered, gain)

    # -- as a graph fragment ------------------------------------------------------------

    def fragment(self, f):
        import audiograph as ag

        self._ag = ag
        self._g_on = f.switch("bass", False)
        g = self._g_on
        b_pcv = f.buffer()
        self._n_pcv = f.add(ag.MIX, (), b_pcv, group=g)
        b_gate = f.buffer()
        self._n_gate = f.add(ag.CONST, (), b_gate, group=g)
        wires = []
        self._n_osc = []
        for wave, ratio in ((1, 0.5), (2, 1.0)):
            b = f.buffer()
            node = f.add(ag.OSC, (b_pcv, None, None, None), b, group=g)
            f.set(node, ag.OSC_WAVEFORM, wave)
            f.set(node, ag.OSC_PULSE_WIDTH, CELLO_WIDTH)
            f.set(node, ag.OSC_LEVEL, 0.25)  # the node's +-0.5, as OscillatorCore's
            f.set(node, ag.OSC_FREQUENCY, BASE_FREQ_C4 * ratio)
            f.set(node, ag.OSC_PITCH_OCTAVES, PITCH_OCTAVES)
            self._n_osc.append(node)
            wires.append(b)
        b_mix = f.buffer()
        self._n_mix = f.add(ag.MIX, tuple(wires), b_mix, group=g)
        b_tone = f.buffer()
        self._n_tone = f.add(ag.PHASER, (b_mix,), b_tone, arg=1.0, group=g)
        f.set(self._n_tone, ag.PHASER_FREQUENCY, BASS_TONE_HZ)
        f.set(self._n_tone, ag.PHASER_FEEDBACK, 0.0)
        f.set(self._n_tone, ag.PHASER_MIX, 0.5)
        b_env = f.buffer()
        f.keep(b_env)  # its last sample says when the group may stop
        self._g_env_buf = b_env
        self._n_env = f.add(ag.ENV, (b_gate,), b_env, group=g)
        f.set(self._n_env, ag.ENV_DECAY, 0.01)
        f.set(self._n_env, ag.ENV_SUSTAIN, 1.0)
        f.set(self._n_env, ag.ENV_RELEASE, BASS_RELEASE_S)
        self._n_vca = f.add(ag.VCA, (b_tone, b_env, None), f.output(self.audio_out), group=g)
        f.set(self._n_vca, ag.VCA_SELECT, 0.0)
        self._g_last = array("h", bytes(2 * self.block_size))
        self._g = {"gate": 0.0, "note": 0.0, "pitch": 0.0, "vel": 1.0}
        for jack, key in (
            (self.gate_in, "gate"),
            (self.note_in, "note"),
            (self.pitch_in, "pitch"),
            (self.vel_in, "vel"),
        ):
            f.watch(jack, lambda v, key=key: self._g.__setitem__(key, v))
        self._g_sounding = False  # the envelope still above 0 after the last block
        self._g_level = 0.0
        self._g_coeff = math.exp(-1.0 / max(1.0, BASS_RELEASE_S * self.sample_rate * 0.25))
        self._g_high = False
        f.bind(
            ("contrabass", "cello", "bass_volume", "crescendo", "tune", "vel_vca"),
            self._graph_params,
        )
        f.before_run(self._graph_block)
        f.after_run(self._graph_after)
        f.on_reset(self._graph_reset)

    def _graph_params(self):
        p = self.params
        f = self._fragment
        ag = self._ag
        f.set(self._n_mix, 0, 1.0 if p["contrabass"] >= 0.5 else 0.0)
        f.set(self._n_mix, 1, 1.0 if p["cello"] >= 0.5 else 0.0)
        attack = slider_time(p["crescendo"], CRESCENDO_RANGE) / ATTACK_TO_PEAK
        f.set(self._n_env, ag.ENV_ATTACK, attack)
        self._graph_gain()

    def _graph_gain(self):
        p = self.params
        vel = 1.0 - p["vel_vca"] * VEL_DEPTH * (1.0 - self._velocity)
        self._fragment.set(self._n_vca, self._ag.VCA_GAIN, p["bass_volume"] * BASS_SCALE * vel)

    def _graph_block(self):
        """process(), once a block: the bass key, held pitch and gate, and whether the group
        runs."""
        f = self._fragment
        g = self._g
        key = 60.0 + g["note"] * 120.0
        high = g["gate"] > 0.5 and (BASS_LOW - 0.5) <= key <= (BASS_HIGH + 0.5)
        if high:
            if self._velocity != g["vel"]:
                self._velocity = g["vel"]
                self._graph_gain()
            pitch = g["pitch"] + self.params["tune"] / 12000.0
            f.set(self._n_pcv, self._ag.MIX_OFFSET, pitch * BRIDGE_SCALE)
        if high != self._g_high:
            self._g_high = high
            f.set(self._n_gate, 0, BRIDGE_SCALE if high else 0.0)
        if not high and self._g_sounding and self._g_ends():
            # the rack's envelope runs out in this block, and the rack renders none of it
            self._g_sounding = False
            f.reset(self._n_env)
        p = self.params
        on = (high or self._g_sounding) and (p["contrabass"] >= 0.5 or p["cello"] >= 0.5)
        f.enable("bass", on)
        if high:
            self._g_sounding = True

    def _g_ends(self):
        """Whether the release ends in the next block, from the level the last ended on."""
        return (
            steps_to_reach(self._g_level, 0.0, self._g_coeff, RELEASE_TOLERANCE) < self.block_size
        )

    def _graph_after(self, sounding):
        f = self._fragment
        if not self._g_sounding or f.rendered < 1:
            return
        if self._g_high:
            # the level a release would start from, read off the wire
            f.read(self._g_env_buf, self._g_last)
            self._g_level = self._g_last[self.block_size - 1] / BRIDGE_SCALE
        else:
            # falling: followed in floats, as the rack's is, since the last few counts of
            # the wire are too coarse to say in which block it ends
            self._g_level *= self._g_coeff ** (self.block_size * f.rendered)

    def _graph_reset(self):
        f = self._fragment
        f.reset(self._n_env)
        f.reset(self._n_tone)
        self._g_sounding = False
