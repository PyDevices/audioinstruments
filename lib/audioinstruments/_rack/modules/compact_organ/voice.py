# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""CompactOrgan voice: divide-down footage oscillators and keyer gate.

Each key runs 16', 8' and 4' square-wave oscillators at fixed footages,
gated by a short ramp on note start and stop. When the bass section is
active and the key lies in the lowest octave (C2 to B2), 16' and 8' route
to the bass buses and leave the treble buses.

A footage no tab listens to is not rendered: the ``use_*`` parameters, which
the patch sets from the tabs, say which ones are heard. Its bus carries
silence until a tab asks for it again.

Compiled to a graph, the keyer is a linear ``LAG`` on the gate, which is also
the voice's own output (the mix listens to it for silence), and each footage
an ``OSC`` whose five ``VCA``s, one a bus, take the keyer at the voice's level
or at 0 where the footage is not routed. In the blocks the rack would not
render the oscillators (the key up and the keyer shut), they stand still:
the graph has no way to stop one node, so each turns a whole number of
cycles a block, deaf to the pitch wire (``frozen_hz``). That matters when two
keys share a group and one plays while the other is parked. A parked voice's
oscillators go back to phase 0 when it plays again, where ``reset()`` leaves
them on the rack.
"""

import math
from array import array

from ...core.jack import SignalType
from ...core.module import Module
from ...core.signal import BASE_FREQ_C4, BRIDGE_SCALE, add, clear_buffer, copy_into, mul, scale
from ...dsp.blocks import Ramp, linear_segment
from ...dsp.oscillator import OscillatorCore
from .._util import jack_signal

#: Gate opening and closing ramp time in seconds (fast switch keyboard).
KEY_RAMP_S = 0.003

#: Pitch CV threshold separating bass keys (MIDI <= 59, C2 to B2) from treble keys.
BASS_KEY_THRESHOLD = -0.005

#: Each footage's level on its bus. Forty-nine keys add on one bus, and the tab
#: filters take their input at a node's int16 scale (rails at +-2.0), so one
#: key's square is kept small: a full forearm cluster peaks near 1.1 on a bus.
VOICE_LEVEL = 0.15


# the outputs, in the order the voice keeps track of which are silent
B16, B8, B4, BASS16, BASS8, OUT = 0, 1, 2, 3, 4, 5


OSC_LEVEL = 0.25  # the node's +-0.5, as OscillatorCore's
PITCH_OCTAVES = 20.0  # the pitch wire's full scale, as the rack's bridge has it
RATIOS = (0.5, 1.0, 2.0)  # 16', 8' and 4'


_F32 = array("f", [0.0])


def _f32(x):
    _F32[0] = x
    return _F32[0]


def _exp2_poly_zero():
    """audiodsp's 2^x at 0, as the node computes it in float32: a hair off 1."""
    g = -0.5
    p = _f32(0.00015404)
    for c in (0.00133336, 0.00961813, 0.05550411, 0.24022651, 0.69314718, 1.0):
        p = _f32(_f32(c) + _f32(g * p))
    return _f32(_f32(1.41421356) * p)


def frozen_hz(sample_rate, frames):
    """A frequency that brings an oscillator back to the phase it started a block at.

    The node's step a sample, with the pitch wire's depth at 0, is
    ``frequency / sample_rate * 2^0`` in float32, and its 2^0 is a hair off 1: the
    frequency is picked so the step is a power of two exactly, the smallest that turns
    a whole number of times in a block. None when no step under the node's limit (0.49 a
    sample) divides the block."""
    step = 1.0
    n = frames
    while n % 2 == 0 and step > 1.0 / frames:
        n //= 2
        step *= 0.5
    if step > 0.49:
        return None
    inv_rate = _f32(1.0 / sample_rate)
    ratio = _exp2_poly_zero()
    hz = _f32(step * sample_rate / ratio)
    for _ in range(64):
        dt = _f32(_f32(hz * inv_rate) * ratio)
        if dt == step:
            break
        hz = _f32(hz * (1.0 + (step - dt) / step))  # nudge it by about the error
    return hz


def _seed(text):
    """A per-voice seed from the module's id."""
    h = 5381
    for ch in text:
        h = (h * 33 + ord(ch)) & 0xFFFF
    return h


class CompactOrganVoice(Module):
    """One voice of the divide-down transistor organ."""

    NAME = "CompactOrganVoice"
    #: takes CompactOrganVibrato's graph wire at its ``graph_wire_scale``
    graph_vibrato = True
    DISPLAY_NAME = "CompactOrgan Voice"
    HP = 10

    def _build(self):
        n = self.block_size
        sr = self.sample_rate
        self.osc16 = OscillatorCore(sr)
        self.osc8 = OscillatorCore(sr)
        self.osc4 = OscillatorCore(sr)
        self._ramp = Ramp(n)
        self._scattered = False

        self._gain = 0.0

        cv, gate, audio = SignalType.CV, SignalType.GATE, SignalType.AUDIO
        self.pitch_in = self.add_input("pitch", "Pitch", cv)
        self.gate_in = self.add_input("gate", "Gate", gate)
        self.note_in = self.add_input("note", "Note", cv)
        self.vibrato_in = self.add_input("vibrato", "Vibrato CV", cv)

        self.bus_16_out = self.add_output("bus_16", "Bus 16'", audio)
        self.bus_8_out = self.add_output("bus_8", "Bus 8'", audio)
        self.bus_4_out = self.add_output("bus_4", "Bus 4'", audio)
        self.bass_16_out = self.add_output("bass_16", "Bass 16'", audio)
        self.bass_8_out = self.add_output("bass_8", "Bass 8'", audio)
        self.audio_out = self.add_output("out", "Audio Out", audio)

        self.add_param("bass", "Bass Active", default=0.0)
        # which footages a tab listens to (the patch sets them from the tabs)
        self.add_param("use_16", "Use 16'", default=1.0)
        self.add_param("use_8", "Use 8'", default=1.0)
        self.add_param("use_4", "Use 4'", default=1.0)
        self.add_param("use_bass_16", "Use Bass 16'", default=1.0)
        self.add_param("use_bass_8", "Use Bass 8'", default=1.0)

        for name in ("_pitch", "_gain_buf", "_tmp"):
            self.add_scratch(name)
        # per output (B16..OUT), written since it was last cleared: a silent one is not
        # cleared again
        self._live = [True] * 6

    def set_block_size(self, block_size):
        super().set_block_size(block_size)
        self._ramp = Ramp(block_size)
        self._live = [True] * 6

    def reset(self):
        self.osc16.reset()
        self.osc8.reset()
        self.osc4.reset()
        self._gain = 0.0

    def _scatter(self, n):
        """Put each voice's oscillators at a distinct phase before the first note."""
        hz = 50.0 + _seed(self.id) % 997
        self.osc16.render(n, hz * 0.5, None, pulse_width=0.5, pulse=self._tmp)
        self.osc8.render(n, hz, None, pulse_width=0.5, pulse=self._tmp)
        self.osc4.render(n, hz * 2.0, None, pulse_width=0.5, pulse=self._tmp)
        self._scattered = True

    def _silence(self, i, out):
        """Clear output ``i`` (its buffer ``out``) unless it is silent already."""
        if self._live[i]:
            clear_buffer(out)
            self._live[i] = False

    def _clear(self):
        self._silence(B16, self.bus_16_out.buffer)
        self._silence(B8, self.bus_8_out.buffer)
        self._silence(B4, self.bus_4_out.buffer)
        self._silence(BASS16, self.bass_16_out.buffer)
        self._silence(BASS8, self.bass_8_out.buffer)
        self._silence(OUT, self.audio_out.buffer)

    def _footage(self, n, used, osc, ratio, i, out, gain):
        """One footage into output ``i`` at the voice's level, or silence; True if it sounds."""
        if not used:
            self._silence(i, out)
            return False
        self._live[i] = True
        osc.render(n, BASE_FREQ_C4 * ratio, self._pitch, pulse_width=0.5, pulse=out)
        if gain is None:
            scale(out, VOICE_LEVEL)
        else:
            mul(out, gain)
        return True

    def process(self, block_size):
        n = block_size
        if not self._scattered:
            self._scatter(n)

        gate_buf = jack_signal(self.gate_in)
        gate_high = gate_buf is not None and gate_buf[n - 1] > 0.5

        if gate_high:
            slope = 1.0 / (KEY_RAMP_S * self.sample_rate) if self._gain < 1.0 else 0.0
        else:
            slope = -1.0 / (KEY_RAMP_S * self.sample_rate) if self._gain > 0.0 else 0.0

        if slope == 0.0:
            if self._gain <= 0.0:
                self._clear()
                return
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

        # the keyer's ramp, at the voice's level; None when the key is fully down
        gain = None
        if slope != 0.0:
            gain = self._gain_buf
            scale(gain, VOICE_LEVEL)

        pitch_buf = jack_signal(self.pitch_in)
        if pitch_buf is not None:
            copy_into(self._pitch, pitch_buf)
        else:
            self._pitch[:] = 0.0

        vib_buf = jack_signal(self.vibrato_in)
        if vib_buf is not None:
            add(self._pitch, vib_buf)

        note_buf = jack_signal(self.note_in)
        note_val = (
            float(note_buf[0])
            if note_buf is not None
            else (float(pitch_buf[0]) if pitch_buf is not None else 0.0)
        )
        p = self.params
        if note_val < BASS_KEY_THRESHOLD and p["bass"] >= 0.5:
            b16 = self.bass_16_out.buffer
            b8 = self.bass_8_out.buffer
            s16 = self._footage(n, p["use_bass_16"] >= 0.5, self.osc16, 0.5, BASS16, b16, gain)
            s8 = self._footage(n, p["use_bass_8"] >= 0.5, self.osc8, 1.0, BASS8, b8, gain)
            self._silence(B16, self.bus_16_out.buffer)
            self._silence(B8, self.bus_8_out.buffer)
            self._silence(B4, self.bus_4_out.buffer)
            heard = (b8 if s8 else b16) if (s8 or s16) else None
        else:
            t16 = self.bus_16_out.buffer
            t8 = self.bus_8_out.buffer
            t4 = self.bus_4_out.buffer
            s16 = self._footage(n, p["use_16"] >= 0.5, self.osc16, 0.5, B16, t16, gain)
            s8 = self._footage(n, p["use_8"] >= 0.5, self.osc8, 1.0, B8, t8, gain)
            s4 = self._footage(n, p["use_4"] >= 0.5, self.osc4, 2.0, B4, t4, gain)
            self._silence(BASS16, self.bass_16_out.buffer)
            self._silence(BASS8, self.bass_8_out.buffer)
            heard = t8 if s8 else (t16 if s16 else (t4 if s4 else None))
        # the voice's own output is what the pool listens to for silence
        if heard is None:
            self._silence(OUT, self.audio_out.buffer)
        else:
            self._live[OUT] = True
            copy_into(self.audio_out.buffer, heard)

    # -- as a graph fragment ------------------------------------------------------------

    def fragment(self, f):
        import audiograph as ag

        self._ag = ag
        # The pitch wire is the key and the vibrato, rounded once. A key from a MIDI module
        # is a control, which goes into the sum's offset in floats.
        vib = f.input(self.vibrato_in)
        keyed = f.is_control(self.pitch_in)
        self._n_pcv = None
        if vib is None:
            b_pcv = f.input(self.pitch_in)
        else:
            source = f.source_module(self.vibrato_in)
            pitch = None if keyed else f.input(self.pitch_in)
            b_pcv = f.buffer()
            self._n_pcv = f.add(ag.MIX, (vib, pitch), b_pcv)
            f.set(self._n_pcv, 0, 1.0 / getattr(source, "graph_wire_scale", 1.0))
            f.set(self._n_pcv, 1, 1.0)
            if keyed:
                f.watch(self.pitch_in, self._graph_key)
        b_key = f.output(self.audio_out)
        self._n_key = f.add(ag.LAG, (f.input(self.gate_in), None, None), b_key)
        f.set(self._n_key, ag.LAG_TIME, KEY_RAMP_S)
        f.set(self._n_key, ag.LAG_MODE, ag.LAG_ON)
        f.set(self._n_key, ag.LAG_SHAPE, ag.LAG_LINEAR)
        self._frozen_hz = frozen_hz(self.sample_rate, self.block_size)
        self._n_osc = []
        wires = []
        for _ in RATIOS:
            b = f.buffer()
            node = f.add(ag.OSC, (b_pcv, None, None, None), b)
            f.set(node, ag.OSC_WAVEFORM, 2)
            f.set(node, ag.OSC_PULSE_WIDTH, 0.5)
            f.set(node, ag.OSC_LEVEL, OSC_LEVEL)
            self._n_osc.append(node)
            wires.append(b)
        # the five outputs, from the footage each one carries
        self._n_vca = []
        for jack, src in (
            (self.bus_16_out, wires[0]),
            (self.bus_8_out, wires[1]),
            (self.bus_4_out, wires[2]),
            (self.bass_16_out, wires[0]),
            (self.bass_8_out, wires[1]),
        ):
            node = f.add(ag.VCA, (src, b_key, None), f.output(jack))
            f.set(node, ag.VCA_SELECT, 0.0)
            self._n_vca.append(node)
        # the rack's keyer, followed a block at a time: whether it renders the oscillators
        self._g_gate = False
        self._g_was = False
        self._g_gain = 0.0
        self._g_run = False
        self._g_played = False  # the first note keeps the phases the prime scattered
        self._g_parked = False
        self._g_rate = 1.0 / (KEY_RAMP_S * self.sample_rate)
        self._note = 0.0
        self._graph_tune()
        f.watch(self.gate_in, self._graph_gate)
        if f.is_control(self.note_in):
            f.watch(self.note_in, self._graph_note)
        elif f.is_control(self.pitch_in):
            f.watch(self.pitch_in, self._graph_note)
        f.bind(("bass", "use_16", "use_8", "use_4", "use_bass_16", "use_bass_8"), self._graph_route)
        f.before_run(self._graph_block)
        f.on_reset(self._graph_reset)
        f.prime(self._graph_scatter)

    def _graph_key(self, value):
        self._fragment.set(self._n_pcv, self._ag.MIX_OFFSET, value * BRIDGE_SCALE)

    def _graph_gate(self, value):
        self._g_gate = value > 0.5

    def _graph_note(self, value):
        self._note = value
        self._graph_route()

    def _graph_tune(self, hz=None):
        """The oscillators at their footages on the pitch wire, or standing still."""
        f = self._fragment
        ag = self._ag
        octaves = 0.0  # a frequency of its own is deaf to the pitch wire
        ratios = RATIOS
        if hz is None:
            if self._g_run:
                hz = BASE_FREQ_C4
                octaves = PITCH_OCTAVES
            else:
                hz = self._frozen_hz or 0.0  # 0: the node's slowest, 0.1 Hz
                ratios = (1.0, 1.0, 1.0)  # every footage at the one that comes round
        for node, ratio in zip(self._n_osc, ratios):
            f.set(node, ag.OSC_PITCH_OCTAVES, octaves)
            f.set(node, ag.OSC_FREQUENCY, hz * ratio)

    def _graph_route(self):
        p = self.params
        bass = self._note < BASS_KEY_THRESHOLD and p["bass"] >= 0.5
        used = (
            not bass and p["use_16"] >= 0.5,
            not bass and p["use_8"] >= 0.5,
            not bass and p["use_4"] >= 0.5,
            bass and p["use_bass_16"] >= 0.5,
            bass and p["use_bass_8"] >= 0.5,
        )
        f = self._fragment
        for node, on in zip(self._n_vca, used):
            f.set(node, self._ag.VCA_GAIN, VOICE_LEVEL if on else 0.0)

    def _graph_block(self):
        """The rack's keyer moved on by the blocks gone; the oscillators run while it would
        render them (a key down, or the keyer still closing) and stand still otherwise."""
        gate = self._g_gate
        if not gate and not self._g_was and not self._g_run:
            return  # shut and still
        g = self._g_gain
        k = self._fragment.blocks
        if k:
            span = k * self.block_size * self._g_rate
            if self._g_was:
                g = 1.0 if g + span >= 1.0 else g + span
            elif g > 0.0:
                g = 0.0 if g - span <= 0.0 else g - span
        self._g_gain = g
        self._g_was = gate
        if gate and self._g_parked:
            # parked since it last played: the rack's reset() put the oscillators at 0
            self._g_parked = False
            f = self._fragment
            for node in self._n_osc:
                f.reset(node)
        if gate:
            self._g_played = True
        run = gate or g > 0.0
        if run != self._g_run:
            self._g_run = run
            self._graph_tune()

    def _graph_reset(self):
        # as reset(): the keyer shut, the oscillators back to phase 0 when it next plays
        self._g_gain = 0.0
        self._g_was = False
        self._g_parked = self._g_played
        if self._g_run:
            self._g_run = False
            self._graph_tune()

    def _graph_scatter(self, run):
        """As ``_scatter``: one block at a frequency of this voice's own, deaf to the pitch
        wire as the rack's is, so the voices do not start in phase. The keyer runs too, on a
        low gate, so the first note ramps it up from 0."""
        f = self._fragment
        self._graph_tune(50.0 + _seed(self.id) % 997)
        run(0 if f.group >= 32 else 1 << f.group, tuple(self._n_osc) + (self._n_key,))
        self._graph_tune()
