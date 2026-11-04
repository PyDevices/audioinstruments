# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""StringEnsemble voice, inspired by one key of the ARP/Eminent Solina String Ensemble.

Each voice is a keyer: 8' and 4' footage oscillators switched on and off by a
short ramp. It has no envelope, no filter and no VCA of its own: shaping happens
once on the bus.

Compiled to a graph, the keyer is a linear ``LAG`` on a ``CONST`` that Python
moves, as the rack's ramp would move, and each register an ``OSC``: the
viola's pulse, the trumpet's and horn's saw and the horn's triangle at 8',
the violin's pulse at 4'. A ``MIX`` takes them at their levels (and the
pulses' shift as its offset), and a ``VCA`` puts the keyer and the velocity
on the sum. In the blocks the rack would not render the oscillators (the key
up and the keyer shut), they stand still, each turning a whole number of
cycles a block, deaf to the pitch wire (see the compact organ's voice), so a
key sharing a group with one that plays keeps its phase.

On the rack, one oscillator node gives two waveforms from one phase; the
first time a voice asks for three (the viola and the horn together) a second
node joins it and both restart at phase 0. The graph's 8' oscillators restart
then too.
"""

import math

from ...core.jack import SignalType
from ...core.module import Module
from ...core.signal import BASE_FREQ_C4, BRIDGE_SCALE, add_scaled, copy_into, scaled_into
from ...dsp.blocks import Ramp, linear_segment
from ...dsp.oscillator import OscillatorCore
from .._util import jack_signal
from ..compact_organ.voice import PITCH_OCTAVES, frozen_hz

#: The pulse width for the viola and violin: 25% duty cycle.
VIOLA_WIDTH = 0.25

#: Output levels for each upper register into the voice's mix.
VIOLA_LEVEL = 0.5
VIOLIN_LEVEL = 0.45
TRUMPET_LEVEL = 0.6
HORN_LEVEL = 0.8

#: Horn waveform mix: a triangle body with a small sawtooth bite.
HORN_SAW = 0.25
HORN_TRI = 0.75

#: Keyer opening ramp time in seconds.
KEY_ON_S = 0.005

#: Keyer choking closing ramp time in seconds.
KEY_CHOKE_S = 0.03

#: Velocity sensitivity depth in the keyer: at max vel_vca, keys range from 0.2 to 1.0.
VEL_DEPTH = 0.8

#: The graph's voice wire carries a quarter of the voice, so a chord of every register
#: sums under the wire's rails in the mix; the output takes the four back.
GRAPH_VOICE_SCALE = 0.25

#: The graph's oscillators: (waveform, footage ratio), in the order the mix takes them.
_SAW, _PULSE, _TRI = 1, 2, 4
GRAPH_OSCS = ((_PULSE, 1.0), (_SAW, 1.0), (_TRI, 1.0), (_PULSE, 2.0))


def _seed(text):
    """A per-voice seed from the module's id."""
    h = 5381
    for ch in text:
        h = (h * 33 + ord(ch)) & 0xFFFF
    return h


class StringEnsembleVoice(Module):
    """One key of the divide-down string ensemble."""

    NAME = "StringEnsembleVoice"
    DISPLAY_NAME = "StringEnsemble Voice"
    HP = 12

    def _build(self):
        sr, n = self.sample_rate, self.block_size
        self.osc8 = OscillatorCore(sr)
        self.osc4 = OscillatorCore(sr)
        self._ramp = Ramp(n)
        self._scattered = False

        self._gate_high = False
        self._latched = False
        self._choking = False
        self._closing = False
        self._gain = 0.0
        self._velocity = 1.0

        cv, gate, audio = SignalType.CV, SignalType.GATE, SignalType.AUDIO
        self.pitch_in = self.add_input("pitch", "1V/Oct", cv)
        self.gate_in = self.add_input("gate", "Gate", gate)
        self.vel_in = self.add_input("velocity", "Velocity", cv)
        self.any_gate_in = self.add_input("any_gate", "Any Gate", gate)
        self.env_in = self.add_input("env", "Env", cv)
        self.audio_out = self.add_output("out", "Voice Out", audio)

        self.add_param("viola", "Viola 8'", default=1.0)
        self.add_param("violin", "Violin 4'", default=1.0)
        self.add_param("trumpet", "Trumpet 8'", default=0.0)
        self.add_param("horn", "Horn 8'", default=0.0)
        self.add_param("tune", "Tune", default=0.0, min_val=-50.0, max_val=50.0)
        self.add_param("vel_vca", "Velocity VCA", default=0.0)

        for name in (
            "_saw8",
            "_pulse8",
            "_tri8",
            "_pulse4",
            "_mix",
            "_cv",
            "_gain_buf",
            "_tmp",
        ):
            self.add_scratch(name)

    def set_block_size(self, block_size):
        super().set_block_size(block_size)
        self._ramp = Ramp(block_size)

    def reset(self):
        self._gate_high = False
        self._latched = False
        self._choking = False
        self._closing = False
        self._gain = 0.0

    def _scatter(self, n):
        """Put each voice's oscillators at a distinct phase before the first note."""
        hz = 50.0 + _seed(self.id) % 997
        self.osc8.render(n, hz, None, pulse=self._pulse8)
        self.osc4.render(n, hz * 2.0, None, pulse=self._pulse4)
        self._scattered = True

    def process(self, block_size):
        n = block_size
        if not self._scattered:
            self._scatter(n)

        p = self.params
        viola = p["viola"] >= 0.5
        violin = p["violin"] >= 0.5
        trumpet = p["trumpet"] >= 0.5
        horn = p["horn"] >= 0.5

        gate_buf = jack_signal(self.gate_in)
        any_gate_buf = jack_signal(self.any_gate_in)
        if any_gate_buf is None:
            any_gate_buf = gate_buf
        env_buf = jack_signal(self.env_in)

        gate_high = gate_buf is not None and gate_buf[n - 1] > 0.5
        any_gate_high = any_gate_buf is not None and any_gate_buf[n - 1] > 0.5
        env_val = float(env_buf[n - 1]) if env_buf is not None else 0.0

        if gate_high and not self._gate_high:
            self._gate_high = True
            self._latched = False
            self._choking = False
            self._closing = False
            vel_buf = jack_signal(self.vel_in)
            self._velocity = float(vel_buf[0]) if vel_buf is not None else 1.0
        elif not gate_high and self._gate_high:
            self._gate_high = False
            if any_gate_high:
                self._choking = True
                self._latched = False
                self._closing = False
            else:
                self._latched = True
                self._choking = False
                self._closing = False

        if self._latched and env_val <= 0.0:
            self._latched = False
            self._closing = True

        if self._gate_high or self._latched:
            slope = 1.0 / (KEY_ON_S * self.sample_rate) if self._gain < 1.0 else 0.0
        elif self._choking:
            if self._gain > 0.0:
                slope = -1.0 / (KEY_CHOKE_S * self.sample_rate)
            else:
                slope = 0.0
                self._choking = False
        elif self._closing:
            if self._gain > 0.0:
                slope = -1.0 / (KEY_ON_S * self.sample_rate)
            else:
                slope = 0.0
                self._closing = False
        else:
            slope = 0.0

        if slope == 0.0:
            self._gain_buf[:] = self._gain
        elif slope > 0.0:
            rem = 1.0 - self._gain
            steps = int(math.ceil(rem / slope))
            if steps >= n:
                self._gain = linear_segment(self._gain_buf, self._gain, slope, self._ramp)
            else:
                if steps > 0:
                    linear_segment(self._gain_buf[0:steps], self._gain, slope, self._ramp)
                self._gain_buf[steps:n] = 1.0
                self._gain = 1.0
        else:
            rem = self._gain
            steps = int(math.ceil(rem / (-slope)))
            if steps >= n:
                self._gain = linear_segment(self._gain_buf, self._gain, slope, self._ramp)
            else:
                if steps > 0:
                    linear_segment(self._gain_buf[0:steps], self._gain, slope, self._ramp)
                self._gain_buf[steps:n] = 0.0
                self._gain = 0.0
                if self._choking:
                    self._choking = False
                if self._closing:
                    self._closing = False

        if self._gain <= 0.0 and not (self._gate_high or self._latched):
            self.audio_out.buffer[:] = 0.0
            return

        if not (viola or violin or trumpet or horn):
            self.audio_out.buffer[:] = 0.0
            return

        cv = self._cv
        pitch = jack_signal(self.pitch_in)
        if pitch is not None:
            copy_into(cv, pitch)
        else:
            cv[:] = 0.0
        tune = p["tune"]
        if tune != 0.0:
            cv += tune / 12000.0

        base = BASE_FREQ_C4
        need_saw8 = trumpet or horn
        need_pulse8 = viola
        need_tri8 = horn

        self.osc8.render(
            n,
            base,
            cv,
            pulse_width=VIOLA_WIDTH,
            saw=self._saw8 if need_saw8 else None,
            pulse=self._pulse8 if need_pulse8 else None,
            tri=self._tri8 if need_tri8 else None,
        )
        if need_pulse8:
            self._pulse8 -= VIOLA_WIDTH - 0.5

        if violin:
            self.osc4.render(
                n,
                base * 2.0,
                cv,
                pulse_width=VIOLA_WIDTH,
                pulse=self._pulse4,
            )
            self._pulse4 -= VIOLA_WIDTH - 0.5

        mix = self._mix
        mix[:] = 0.0
        tmp = self._tmp
        if viola:
            add_scaled(mix, self._pulse8, VIOLA_LEVEL, tmp)
        if trumpet:
            add_scaled(mix, self._saw8, TRUMPET_LEVEL, tmp)
        if horn:
            add_scaled(mix, self._saw8, HORN_LEVEL * HORN_SAW, tmp)
            add_scaled(mix, self._tri8, HORN_LEVEL * HORN_TRI, tmp)
        if violin:
            add_scaled(mix, self._pulse4, VIOLIN_LEVEL, tmp)

        vel_vca = p["vel_vca"]
        vel_factor = 1.0 - vel_vca * VEL_DEPTH * (1.0 - self._velocity)
        scaled_into(self.audio_out.buffer, mix, vel_factor)
        self.audio_out.buffer *= self._gain_buf

    # -- as a graph fragment ------------------------------------------------------------

    def fragment(self, f):
        import audiograph as ag

        self._ag = ag
        # the pitch wire: the key (a control, in floats) or the cable, and the tune, rounded once
        keyed = f.is_control(self.pitch_in)
        b_pcv = f.buffer()
        self._n_pcv = f.add(ag.MIX, () if keyed else (f.input(self.pitch_in),), b_pcv)
        f.set(self._n_pcv, 0, 1.0)
        self._g_key = 0.0
        if keyed:
            f.watch(self.pitch_in, self._graph_key)
        # the keyer: a CONST the LAG ramps to, at the rack's slope
        b_target = f.buffer()
        self._n_target = f.add(ag.CONST, (), b_target)
        b_key = f.buffer()
        self._n_key = f.add(ag.LAG, (b_target, None, None), b_key)
        f.set(self._n_key, ag.LAG_MODE, ag.LAG_ON)
        f.set(self._n_key, ag.LAG_SHAPE, ag.LAG_LINEAR)
        f.set(self._n_key, ag.LAG_TIME, KEY_ON_S)
        self._n_osc = []
        wires = []
        for wave, _ in GRAPH_OSCS:
            b = f.buffer()
            node = f.add(ag.OSC, (b_pcv, None, None, None), b)
            f.set(node, ag.OSC_WAVEFORM, wave)
            f.set(node, ag.OSC_PULSE_WIDTH, VIOLA_WIDTH)
            f.set(node, ag.OSC_LEVEL, 0.25)  # the node's +-0.5, as OscillatorCore's
            self._n_osc.append(node)
            wires.append(b)
        b_mix = f.buffer()
        self._n_mix = f.add(ag.MIX, tuple(wires), b_mix)
        self._n_vca = f.add(ag.VCA, (b_mix, b_key, None), f.output(self.audio_out))
        f.set(self._n_vca, ag.VCA_SELECT, 0.0)
        f.set(self._n_vca, ag.VCA_GAIN, 0.0)
        self._frozen_hz = frozen_hz(self.sample_rate, self.block_size)
        # the rack's keyer, followed a block at a time
        self._g_gate = False
        self._g_any = False
        self._g_vel = 1.0
        self._g_slope = 0.0
        self._g_lag = None  # (target, time) the LAG was last given
        self._g_run = False
        self._g_gain_set = None
        self._g_second = False  # the rack's 8' oscillator has grown a second node
        self._g_env = f.source_module(self.env_in)
        self._graph_tune()
        f.watch(self.gate_in, self._graph_gate)
        f.watch(self.any_gate_in, self._graph_any)
        if f.is_control(self.vel_in):
            f.watch(self.vel_in, self._graph_vel)
        f.bind(("viola", "violin", "trumpet", "horn", "tune", "vel_vca"), self._graph_levels)
        f.before_run(self._graph_block)
        f.on_reset(self._graph_reset)
        f.prime(self._graph_scatter)

    def _graph_key(self, value):
        self._g_key = value
        self._graph_pitch()

    def _graph_gate(self, value):
        self._g_gate = value > 0.5

    def _graph_any(self, value):
        self._g_any = value > 0.5

    def _graph_vel(self, value):
        self._g_vel = value

    def _graph_pitch(self):
        offset = self._g_key + self.params["tune"] / 12000.0
        self._fragment.set(self._n_pcv, self._ag.MIX_OFFSET, offset * BRIDGE_SCALE)

    def _graph_levels(self):
        p = self.params
        f = self._fragment
        viola = p["viola"] >= 0.5
        violin = p["violin"] >= 0.5
        trumpet = p["trumpet"] >= 0.5
        horn = p["horn"] >= 0.5
        saw = (TRUMPET_LEVEL if trumpet else 0.0) + (HORN_LEVEL * HORN_SAW if horn else 0.0)
        levels = (
            VIOLA_LEVEL if viola else 0.0,
            saw,
            HORN_LEVEL * HORN_TRI if horn else 0.0,
            VIOLIN_LEVEL if violin else 0.0,
        )
        for i, level in enumerate(levels):
            f.set(self._n_mix, i, level)
        shift = 0.5 - VIOLA_WIDTH  # each pulse is moved up to sit around 0
        f.set(self._n_mix, self._ag.MIX_OFFSET, (levels[0] + levels[3]) * shift * BRIDGE_SCALE)
        self._g_any_register = viola or violin or trumpet or horn
        self._g_three = viola and horn  # saw, pulse and triangle: two nodes on the rack
        if self._n_pcv is not None:
            self._graph_pitch()
        self._g_gain_set = None

    def _graph_tune(self):
        """The oscillators at their footages on the pitch wire, or standing still."""
        f = self._fragment
        ag = self._ag
        for node, (_, ratio) in zip(self._n_osc, GRAPH_OSCS):
            if self._g_run:
                f.set(node, ag.OSC_PITCH_OCTAVES, PITCH_OCTAVES)
                f.set(node, ag.OSC_FREQUENCY, BASE_FREQ_C4 * ratio)
            else:
                f.set(node, ag.OSC_PITCH_OCTAVES, 0.0)
                f.set(node, ag.OSC_FREQUENCY, self._frozen_hz or 0.0)

    def _graph_advance(self, frames):
        """The rack's ramp moved on by ``frames`` at the slope it was given."""
        slope = self._g_slope
        if slope == 0.0:
            return
        g = self._gain + slope * frames
        if g >= 1.0:
            g = 1.0
            self._g_slope = 0.0
        elif g <= 0.0:
            g = 0.0
            self._g_slope = 0.0
            self._choking = False
            self._closing = False
        self._gain = g

    def _graph_block(self):
        """process(), once a block, with the keyer's state machine in Python and the nodes
        doing the ramp."""
        gate = self._g_gate
        if (
            not gate
            and self._gain == 0.0
            and self._g_slope == 0.0
            and self._g_gain_set == 0.0
            and not (self._gate_high or self._latched or self._choking or self._closing)
            and not self._g_run
        ):
            return  # shut and still: most of the keys, most of the time
        f = self._fragment
        n = self.block_size
        if self._g_slope != 0.0:
            self._graph_advance(f.blocks * n)
        if gate and not self._gate_high:
            self._gate_high = True
            self._latched = False
            self._choking = False
            self._closing = False
            self._velocity = self._g_vel
        elif not gate and self._gate_high:
            self._gate_high = False
            self._latched = not self._g_any
            self._choking = self._g_any
            self._closing = False
        if self._latched and getattr(self._g_env, "graph_env_zero", True):
            self._latched = False
            self._closing = True
        sr = self.sample_rate
        if self._gate_high or self._latched:
            slope = 1.0 / (KEY_ON_S * sr) if self._gain < 1.0 else 0.0
        elif self._choking:
            slope = -1.0 / (KEY_CHOKE_S * sr) if self._gain > 0.0 else 0.0
            self._choking = slope != 0.0
        elif self._closing:
            slope = -1.0 / (KEY_ON_S * sr) if self._gain > 0.0 else 0.0
            self._closing = slope != 0.0
        else:
            slope = 0.0
        self._g_slope = slope
        if slope != 0.0:
            target = 1.0 if slope > 0.0 else 0.0
            lag = (target, abs(target - self._gain) / (abs(slope) * sr))
            if lag[0] != (self._g_lag or (None,))[0] or self._g_lag is None:
                self._g_lag = lag
                f.set(self._n_target, 0, target * BRIDGE_SCALE)
                f.set(self._n_key, self._ag.LAG_TIME, lag[1])
        # the rack renders when its keyer, a block on, is still open or a key holds it
        end = self._gain + slope * n
        held = self._gate_high or self._latched
        run = (end > 0.0 or held) and self._g_any_register
        if run != self._g_run:
            self._g_run = run
            self._graph_tune()
        if run and not self._g_second and self._g_three:
            self._g_second = True
            for node in self._n_osc[:3]:
                f.reset(node)  # the 8' waves, restarted with the rack's second node
        vel = 1.0 - self.params["vel_vca"] * VEL_DEPTH * (1.0 - self._velocity)
        gain = vel * GRAPH_VOICE_SCALE if run else 0.0
        if gain != self._g_gain_set:
            self._g_gain_set = gain
            f.set(self._n_vca, self._ag.VCA_GAIN, gain)

    def _graph_reset(self):
        # as reset(): the keyer shut, the oscillators left where they stand
        self._gate_high = False
        self._latched = False
        self._choking = False
        self._closing = False
        self._gain = 0.0
        self._g_slope = 0.0
        self._g_lag = None
        f = self._fragment
        f.set(self._n_target, 0, 0.0)
        f.set(self._n_key, self._ag.LAG_TIME, KEY_ON_S)
        if self._g_run:
            self._g_run = False
            self._graph_tune()
            f.set(self._n_vca, self._ag.VCA_GAIN, 0.0)
            self._g_gain_set = 0.0

    def _graph_scatter(self, run):
        """As ``_scatter``: one block at a frequency of this voice's own, deaf to the pitch
        wire, so the voices do not start in phase. The keyer runs too, so it starts at 0."""
        f = self._fragment
        ag = self._ag
        hz = 50.0 + _seed(self.id) % 997
        for node, (_, ratio) in zip(self._n_osc, GRAPH_OSCS):
            f.set(node, ag.OSC_PITCH_OCTAVES, 0.0)
            f.set(node, ag.OSC_FREQUENCY, hz * ratio)
        run(0 if f.group >= 32 else 1 << f.group, tuple(self._n_osc) + (self._n_key,))
        self._graph_tune()
