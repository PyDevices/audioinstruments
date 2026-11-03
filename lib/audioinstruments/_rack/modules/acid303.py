# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Acid303, a bass voice inspired by the Roland TB-303: saw or square VCO, the diode ladder with accent
circuit, a decay envelope, slide, and a 16-step sequencer with gate, accent
and slide per step.

The panel is attributes: ``bpm``, ``tuning`` (Hz), ``waveform`` (0 saw, 1
square), ``cutoff_hz``, ``resonance``, ``env_mod``, ``decay``, ``accent``,
``volume``; ``set_step(i, pitch, gate, accent, slide)`` programs a step.
"""

import math

from ..core.bridge import OSC_LEVEL, PITCH_OCTAVES
from ..core.graph import UNIT
from ..core.jack import SignalType
from ..core.module import Module
from ..core.signal import copy_into, mul
from ..dsp.blocks import EdgeDetector
from ..dsp.envelope import EnvelopeCore
from ..dsp.ladder import AcidFilterCore
from ..dsp.oscillator import OscillatorCore
from ._util import jack_signal
from .drum_synth import InternalClock

_LN2 = math.log(2.0)

#: The cables every patch after Init plugs: a hard-struck note accents, a legato note slides.
_LINE = (("voice.velocity", "velocity_in"), ("voice.legato", "slide_in"))


def _panel(name):
    """An attribute that reads and writes the parameter ``name``, so a patch and the panel agree."""
    return property(lambda self: self.params[name], lambda self, v: self.set_param(name, v))


class Acid303(Module):
    NAME = "Acid303"
    DISPLAY_NAME = "Acid303"
    HP = 24

    MACRO_LABELS = (
        "tempo_bpm",
        "tuning",
        "cutoff",
        "resonance",
        "env_mod",
        "decay",
        "accent",
        "waveform",
        "volume",
    )
    #: The parameter each macro moves, where the macro's name is not the parameter's.
    MACRO_PARAMS = (
        "bpm",
        "tuning",
        "cutoff_hz",
        "resonance",
        "env_mod",
        "decay",
        "accent",
        "waveform",
        "volume",
    )
    MACRO_MODES = {
        0: "UNIPOLAR",
        1: "UNIPOLAR",
        2: "UNIPOLAR",
        3: "UNIPOLAR",
        4: "UNIPOLAR",
        5: "UNIPOLAR",
        6: "UNIPOLAR",
        7: "TOGGLE",
        8: "UNIPOLAR",
    }

    tuning = _panel("tuning")
    waveform = _panel("waveform")
    cutoff_hz = _panel("cutoff_hz")
    resonance = _panel("resonance")
    env_mod = _panel("env_mod")
    decay = _panel("decay")
    accent = _panel("accent")
    bpm = _panel("bpm")
    volume = _panel("volume")

    #: The eleven patches after Init. Each cables the played line to the accent and slide
    #: circuits, as a step's flags do on the machine: a note struck at ``accent_velocity`` (0 to
    #: 1, 0.8 is 102) or harder accents, and a note played over the one before slides to it.
    #: Without the cables (Init) the 16 steps' own flags decide, whatever is played.
    #: ``cutoff_hz`` and ``tuning`` are in Hz, ``decay`` in seconds. Init plays note 60 at the
    #: tuning knob's 65.41 Hz, as the module always has; the others set it to 261.6 so that
    #: a key sounds at its own pitch.
    PRESETS = (
        ("Init", {}),
        (
            "Squelch",
            {
                "tuning": 261.6,
                # The sawtooth line with the filter nearly closed, a sharp envelope and the
                # resonance high: the squelch.
                "cutoff_hz": 300.0,
                "resonance": 0.85,
                "env_mod": 0.75,
                "decay": 0.3,
                "accent": 0.85,
            },
            _LINE,
        ),
        (
            "Square Acid",
            {
                "tuning": 261.6,
                # The square wave, hollower and more nasal, with a shorter decay.
                "waveform": 1,
                "cutoff_hz": 350.0,
                "resonance": 0.8,
                "env_mod": 0.7,
                "decay": 0.22,
                "accent": 0.8,
            },
            _LINE,
        ),
        (
            "Rubber Bass",
            {
                "tuning": 261.6,
                # A plain rounded bass: little resonance, a small envelope sweep.
                "cutoff_hz": 250.0,
                "resonance": 0.3,
                "env_mod": 0.35,
                "decay": 0.2,
                "accent": 0.5,
                "volume": 1.5,
            },
            _LINE,
        ),
        (
            "Screamer",
            {
                "tuning": 261.6,
                # The resonance at the edge of ringing and the filter swept far: the accents shriek.
                "cutoff_hz": 900.0,
                "resonance": 0.95,
                "env_mod": 0.85,
                "decay": 0.6,
                "accent": 1.0,
                "volume": 0.9,
            },
            _LINE,
        ),
        (
            "Sub Thump",
            {
                # A square wave low in the register, the filter mostly shut: a pulse under a kick.
                "waveform": 1,
                "tuning": 261.6,
                "cutoff_hz": 260.0,
                "resonance": 0.2,
                "env_mod": 0.45,
                "decay": 0.3,
                "accent": 0.4,
                "volume": 1.3,
            },
            _LINE,
        ),
        (
            "Bleep",
            {
                # A short bright square-wave blip, high in the register, for a stuttered top line.
                "waveform": 1,
                "tuning": 261.6,
                "cutoff_hz": 1500.0,
                "resonance": 0.5,
                "env_mod": 0.2,
                "decay": 0.08,
                "accent": 0.6,
            },
            _LINE,
        ),
        (
            "Dark Roller",
            {
                "tuning": 261.6,
                # Low and closed, the envelope slow to let go: a bass line that rolls.
                "cutoff_hz": 180.0,
                "resonance": 0.75,
                "env_mod": 0.55,
                "decay": 0.45,
                "accent": 0.7,
                "volume": 1.1,
            },
            _LINE,
        ),
        (
            "Open Wail",
            {
                "tuning": 261.6,
                # The filter well open and a long decay, so each note sings before it falls.
                "cutoff_hz": 1800.0,
                "resonance": 0.6,
                "env_mod": 0.5,
                "decay": 1.0,
                "accent": 0.9,
            },
            _LINE,
        ),
        (
            "Pluck Stab",
            {
                "tuning": 261.6,
                # The shortest decay and the full envelope sweep: a stab that snaps shut.
                "cutoff_hz": 500.0,
                "resonance": 0.55,
                "env_mod": 1.0,
                "decay": 0.06,
                "accent": 0.6,
                "volume": 1.25,
            },
            _LINE,
        ),
        (
            "Long Drone",
            {
                "tuning": 261.6,
                # A note that hardly decays, the filter half open: a line of held, sliding tones.
                "cutoff_hz": 700.0,
                "resonance": 0.45,
                "env_mod": 0.3,
                "decay": 1.5,
                "accent": 0.5,
                "volume": 1.5,
            },
            _LINE,
        ),
        (
            "Zap",
            {
                # A square wave, a full sweep and ringing resonance, over in an instant.
                "waveform": 1,
                "tuning": 261.6,
                "cutoff_hz": 600.0,
                "resonance": 0.9,
                "env_mod": 1.0,
                "decay": 0.15,
                "accent": 1.0,
                "volume": 0.9,
            },
            _LINE,
        ),
    )

    def _build(self):
        sr, n = self.sample_rate, self.block_size
        self.vco = OscillatorCore(sr)
        self.filter = AcidFilterCore(sr)
        self.env = EnvelopeCore(sr, n)
        self.clock = InternalClock(sr)
        self.clock_edges = EdgeDetector(n)

        cv, gate, audio, clk = SignalType.CV, SignalType.GATE, SignalType.AUDIO, SignalType.CLOCK
        self.pitch_in = self.add_input("pitch_in", "1V/Oct Pitch In", cv)
        self.gate_in = self.add_input("gate_in", "Gate In", gate)
        self.accent_in = self.add_input("accent_in", "Accent In", gate)
        self.slide_in = self.add_input("slide_in", "Slide In", gate)
        self.velocity_in = self.add_input("velocity_in", "Velocity In", cv)
        self.clock_in = self.add_input("clock_in", "Clock In", clk)
        self.audio_out = self.add_output("audio_out", "Audio Out", audio)
        self.accent_out = self.add_output("accent_out", "Accent Out", gate)

        self.add_param("tuning", "Tuning", 65.41, 16.0, 1100.0)
        self.add_param("waveform", "Waveform", 0, 0, 1, "TOGGLE")
        self.add_param("cutoff_hz", "Cutoff", 400.0, 20.0, 12000.0)
        self.add_param("resonance", "Resonance", 0.7, 0.0, 0.98)
        self.add_param("env_mod", "Env Mod", 0.6, 0.0, 1.0)
        self.add_param("decay", "Decay", 0.25, 0.05, 1.55)
        self.add_param("accent", "Accent", 0.7, 0.0, 1.0)
        self.add_param("bpm", "Tempo", 128.0, 40.0, 240.0)
        self.add_param("volume", "Volume", 1.0, 0.0, 1.5)
        # the lowest velocity (0..1) that accents a note, where the velocity jack is cabled
        self.add_param("accent_velocity", "Accent Velocity", 0.8, 0.0, 1.0)
        self.seq_idx = -1  # the first clock tick lands on step 0
        self.step_pitches = [
            0.0,
            0.0,
            0.1,
            0.0,
            0.0,
            0.07,
            0.0,
            0.02,
            0.1,
            0.0,
            0.0,
            0.12,
            0.0,
            0.05,
            0.0,
            0.0,
        ]
        self.step_gates = [1, 1, 1, 0, 1, 1, 0, 1, 1, 0, 1, 1, 0, 1, 1, 0]
        self.step_accents = [1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 1, 0, 0, 1, 0]
        self.step_slides = [0, 1, 0, 0, 0, 1, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0]
        self._accent = 0.0
        self._slid = 0.0
        for name in ("_saw", "_pulse", "_env", "_filt", "_gate", "_clk", "_pitch", "_gain"):
            self.add_scratch(name)

    def set_macro(self, index, value):
        v = max(0.0, min(1.0, value))
        if index == 0:
            self.bpm = 80.0 + v * 120.0
        elif index == 1:
            self.tuning = 32.7 * (2.0 ** (v * 3.0))
        elif index == 2:
            self.cutoff_hz = 50.0 * (2.0 ** (v * 7.5))
        elif index == 3:
            self.resonance = v * 0.98
        elif index == 4:
            self.env_mod = v
        elif index == 5:
            self.decay = 0.05 + (v**2) * 1.5
        elif index == 6:
            self.accent = v
        elif index == 7:
            self.waveform = 1 if v > 0.5 else 0
        elif index == 8:
            self.volume = v * 1.5

    def get_macro(self, index):
        """The panel attribute behind macro ``index``, 0..1, as ``set_macro`` takes it."""
        if index == 0:
            return (self.bpm - 80.0) / 120.0
        if index == 1:
            return math.log(self.tuning / 32.7) / _LN2 / 3.0
        if index == 2:
            return math.log(self.cutoff_hz / 50.0) / _LN2 / 7.5
        if index == 3:
            return self.resonance / 0.98
        if index == 4:
            return self.env_mod
        if index == 5:
            return ((self.decay - 0.05) / 1.5) ** 0.5
        if index == 6:
            return self.accent
        if index == 7:
            return float(self.waveform)
        if index == 8:
            return self.volume / 1.5
        return 0.0

    def _struck(self, velocity):
        """The accent a note of ``velocity`` (0..1) plays: all of it above the threshold, else none."""
        return self.accent if velocity >= self.params["accent_velocity"] else 0.0

    def set_step(self, step_idx, pitch, gate=True, accent=False, slide=False):
        """Program one of the 16 steps: pitch offset (1 V/oct) and three flags."""
        if 0 <= step_idx < 16:
            self.step_pitches[step_idx] = pitch
            self.step_gates[step_idx] = 1 if gate else 0
            self.step_accents[step_idx] = 1 if accent else 0
            self.step_slides[step_idx] = 1 if slide else 0

    def set_block_size(self, block_size):
        super().set_block_size(block_size)
        self.env.set_block_size(block_size)
        self.clock_edges = EdgeDetector(block_size)

    def reset(self):
        for core in (self.vco, self.filter, self.env, self.clock):
            core.reset()
        self.seq_idx = -1
        self.clock_edges.high = False

    def process(self, block_size):
        n = block_size
        clk = jack_signal(self.clock_in)
        if clk is None:
            self.clock.render(self._clk, self.bpm / 60.0 * 4.0)  # sixteenths
            clk = self._clk
        edge, _ = self.clock_edges.scan(clk)
        gate = self._gate
        start = 0
        if edge >= 0:
            gate[0:edge] = 1.0 if (self.seq_idx >= 0 and self.step_gates[self.seq_idx]) else 0.0
            self.seq_idx = (self.seq_idx + 1) % 16
            start = edge
        s = max(0, self.seq_idx)
        gate[start:n] = 1.0 if self.step_gates[s] else 0.0
        accent = float(self.step_accents[s]) * self.accent
        slide = bool(self.step_slides[s])
        target_pitch = self.step_pitches[s]

        # the panel jacks override the sequencer when something is plugged in
        ext = jack_signal(self.pitch_in)
        if ext is not None:
            target_pitch = float(ext[0])
        ext = jack_signal(self.gate_in)
        if ext is not None:
            gate = ext
        ext = jack_signal(self.velocity_in)
        if ext is not None:
            accent = self._struck(float(ext[0]))
        ext = jack_signal(self.accent_in)
        if ext is not None:
            accent = float(ext[0]) * self.accent
        ext = jack_signal(self.slide_in)
        if ext is not None:
            slide = float(ext[0]) > 0.5

        acc = self.accent_out.buffer
        acc[:] = accent
        self.env.set_times(0.003, self.decay * (0.6 if accent > 0.2 else 1.0), 0.0, 0.05)
        self.env.render(gate, self._env)

        pitch = self._pitch
        pitch[:] = self.filter.slide(target_pitch, slide)
        self.vco.render(
            n,
            self.tuning,
            pitch,
            saw=self._saw if self.waveform == 0 else None,
            pulse=self._pulse if self.waveform == 1 else None,
        )
        self.filter.render(
            n,
            self._pulse if self.waveform == 1 else self._saw,
            self._filt,
            self.cutoff_hz,
            self.resonance,
            self.env_mod,
            self._env,
            acc,
        )

        gain = self._gain
        copy_into(gain, self._env)
        gain *= (1.0 + accent * 0.8) * self.volume
        out = self.audio_out.buffer
        copy_into(out, self._filt)
        mul(out, gain)

    # -- as a graph fragment ------------------------------------------------------------

    def fragment(self, f):
        """The voice as nodes: OSC, ENV, ACID and VCA. The sequencer, the slide and the panel
        stay Python and move once a block (``before_run``): the steps' accent and slide flags,
        the slid pitch, the envelope's decay and the VCA's gain.

        A module with no gate cabled plays its sequencer's gates inside the block, which a node
        cannot; so does an external clock. Those stay on the rack."""
        import audiograph as ag

        if not hasattr(ag, "ACID") or self.gate_in.cable is None or self.clock_in.cable is not None:
            return False
        self._ag = ag
        self._fragment = f
        b_gate = f.input(self.gate_in)

        b_env = f.buffer()
        b_pitch = f.buffer()
        b_saw = f.buffer()
        b_acc = f.output(self.accent_out) if self.accent_out.cables else f.buffer()
        b_filt = f.buffer()

        self._n_env = f.add(ag.ENV, (b_gate,), b_env)
        f.set(self._n_env, ag.ENV_ATTACK, 0.003)
        f.set(self._n_env, ag.ENV_SUSTAIN, 0.0)
        f.set(self._n_env, ag.ENV_RELEASE, 0.05)
        self._n_pitch = f.add(ag.CONST, (), b_pitch)
        self._n_osc = f.add(ag.OSC, (b_pitch, None, None, None), b_saw)
        f.set(self._n_osc, ag.OSC_LEVEL, OSC_LEVEL)
        f.set(self._n_osc, ag.OSC_PITCH_OCTAVES, PITCH_OCTAVES)
        self._n_acc = f.add(ag.CONST, (), b_acc)
        self._n_acid = f.add(ag.ACID, (b_saw, b_env, b_acc), b_filt)
        self._n_vca = f.add(ag.VCA, (b_filt, b_env, None), f.output(self.audio_out))
        f.set(self._n_vca, ag.VCA_SELECT, 0.0)
        f.set(self._n_vca, ag.VCA_CURVE, ag.VCA_LINEAR)

        # what the panel jacks hand over when something is plugged in
        self._k_pitch = self._k_accent = self._k_slide = self._k_velocity = None
        f.watch(self.pitch_in, self._graph_pitch)
        f.watch(self.velocity_in, self._graph_velocity)
        f.watch(self.accent_in, self._graph_accent)
        f.watch(self.slide_in, self._graph_slide)
        f.before_run(self._graph_block)
        f.on_reset(self._graph_reset)
        self._graph_block()

    def _graph_pitch(self, value):
        self._k_pitch = value

    def _graph_velocity(self, value):
        self._k_velocity = value

    def _graph_accent(self, value):
        self._k_accent = value

    def _graph_slide(self, value):
        self._k_slide = value

    def _graph_block(self):
        f = self._fragment
        ag = self._ag
        # the sequencer's clock runs a step a tick, for every block that has passed, and
        # stands still while the voice is parked, as the rack's does
        for _ in range(f.blocks if self.enabled else 0):
            self.clock.render(self._clk, self.bpm / 60.0 * 4.0)
            edge, _ = self.clock_edges.scan(self._clk)
            if edge >= 0:
                self.seq_idx = (self.seq_idx + 1) % 16
            s = max(0, self.seq_idx)
            accent = float(self.step_accents[s]) * self.accent
            slide = bool(self.step_slides[s])
            target = self.step_pitches[s]
            if self._k_pitch is not None:
                target = self._k_pitch
            if self._k_velocity is not None:
                accent = self._struck(self._k_velocity)
            if self._k_accent is not None:
                accent = self._k_accent * self.accent
            if self._k_slide is not None:
                slide = self._k_slide > 0.5
            self._accent = accent
            self._slid = self.filter.slide(target, slide)
        accent = self._accent
        f.set(self._n_pitch, 0, self._slid * UNIT)
        f.set(self._n_acc, 0, accent * UNIT)
        f.set(self._n_env, ag.ENV_DECAY, self.decay * (0.6 if accent > 0.2 else 1.0))
        f.set(self._n_osc, ag.OSC_FREQUENCY, self.tuning)
        f.set(self._n_osc, ag.OSC_WAVEFORM, 2 if self.waveform == 1 else 1)
        f.set(self._n_acid, ag.ACID_CUTOFF_HZ, self.cutoff_hz)
        f.set(self._n_acid, ag.ACID_RESONANCE, self.resonance)
        f.set(self._n_acid, ag.ACID_ENVMOD, self.env_mod)
        f.set(self._n_vca, ag.VCA_GAIN, (1.0 + accent * 0.8) * self.volume)

    def _graph_reset(self):
        f = self._fragment
        for node in (self._n_osc, self._n_acid, self._n_env):
            f.reset(node)
        self.filter.reset()
        self.clock.reset()
        self.seq_idx = -1
        self.clock_edges.high = False
        self._accent = 0.0
        self._slid = 0.0
