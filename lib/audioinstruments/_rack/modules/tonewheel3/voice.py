# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Tonewheel3 voice: one key's nine footages, its percussion harmonic and its key click.

The nine drawbars (0 to 8, about 3 dB a step) set the footages' levels; the
footages fold at the keyboard's ends (``dsp.organ.tonewheel_harmonics``) and
are summed into one table that a synthio note plays. While percussion is on,
the 1' is silent (the organ borrows its busbar for the percussion) and, at
normal percussion volume, the drawbars drop by about 3 dB. The percussion
itself is a sine at the second (4') or third (2 2/3') harmonic, folded as
those footages are, scaled by the envelope the whole manual shares
(``Tonewheel3Percussion``, patched into ``perc_env``) and keyed by the same
contacts as the tone. An organ key is a switch: velocity changes nothing.

The tone runs 256 frames late (a synthio note through a ``ChunkedBridge``), and
the contacts and the key click are as late as it is, so they line up on every
note; the percussion sounds through the same contacts.
"""

from ...core.bridge import ChunkedBridge
from ...core.graph import UNIT
from ...core.jack import SignalType
from ...core.module import Module
from ...core.signal import BASE_FREQ_C4, create_buffer, mul, scale
from ...dsp.organ import DRAWBAR_LEVELS, DrawbarToneCore, KeyClickCore, tonewheel_harmonics
from ...dsp.oscillator import OscillatorCore
from .._util import jack_signal

DRAWBARS = ("db16", "db5_13", "db8", "db4", "db2_23", "db2", "db1_35", "db1_13", "db1")
LABELS = ("16'", "5 1/3'", "8'", "4'", "2 2/3'", "2'", "1 3/5'", "1 1/3'", "1'")

#: Each footage's own level against the drawbar's: the 5 1/3' wheels sit about
#: 8 dB under the 16' and 8' on a held note, the middle of what the drawbar
#: organ study reference has across the keyboard (1 to 16 dB).
FOOTAGE_TRIM = (1.0, 0.4, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0)
#: Normal percussion volume takes the drawbars down about 3 dB.
PERC_NORMAL_DROP = 0.7079
#: The percussion oscillator's scale: it puts the normal-volume peak at twice a
#: full footage (+6 dB) and soft, 6 dB under it, at a full footage, about where
#: the percussive study reference has it.
PERC_LEVEL = 0.24
#: Which footage the percussion harmonic shares: second (4') or third (2 2/3').
PERC_FOOTAGE = (3, 4)

#: The graph's click: the rack's tables decay as exp(-6 t) over 4 ms down and
#: exp(-8 t) over 2 ms up, which falls 40 dB in these many seconds.
CLICK_DOWN_SEC = 4.60517 / 6.0 * 0.004
CLICK_UP_SEC = 4.60517 / 8.0 * 0.002
CLICK_DOWN_LEVEL = 1.0
CLICK_UP_LEVEL = 0.62
#: Fitted so the graph's click carries the rack's energy, down and up, averaged over
#: thirty keys (the rack's click is one fixed table; the graph's noise is new each time).
CLICK_GAIN = 1.11
#: The rack's percussion sine peaks at 0.5 of a rack unit; an OSC at level 0.25 does too.
PERC_OSC_SCALE = 1.0


class Tonewheel3Voice(Module):
    NAME = "Tonewheel3Voice"
    DISPLAY_NAME = "Tonewheel3 Voice"
    HP = 20

    MACRO_LABELS = ("db16", "db8", "db4", "db2", "perc_harmonic")

    def _build(self):
        self._make_cores(self.block_size)

        cv = SignalType.CV
        self.pitch_in = self.add_input("pitch", "1V/Oct", cv)
        self.note_in = self.add_input("note", "Key (no bend)", cv)
        self.gate_in = self.add_input("gate", "Gate", SignalType.GATE)
        self.perc_env_in = self.add_input("perc_env", "Percussion Envelope", cv)
        self.audio_out = self.add_output("out", "Audio", SignalType.AUDIO)

        fresh = (8.0, 8.0, 8.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
        for name, label, value in zip(DRAWBARS, LABELS, fresh):
            self.add_param(name, label, default=value, min_val=0.0, max_val=8.0)
        self.add_param("click", "Key Click", default=5.0, min_val=0.0, max_val=10.0)
        self.add_param("percussion", "Percussion On", default=1.0, min_val=0.0, max_val=1.0)
        # 1 normal, 0 soft
        self.add_param("perc_volume", "Percussion Volume", default=1.0, min_val=0.0, max_val=1.0)
        # 1 third, 0 second
        self.add_param(
            "perc_harmonic", "Percussion Harmonic", default=1.0, min_val=0.0, max_val=1.0
        )

        self._levels = [0.0] * 9
        self._harmonics = [0] * 9

    def _make_cores(self, n):
        sr = self.sample_rate
        self.tone_core = DrawbarToneCore(sr, n)
        self.click_core = KeyClickCore(sr, n)
        self.perc_osc = OscillatorCore(sr)
        self._perc = create_buffer(n)

    def set_block_size(self, block_size):
        super().set_block_size(block_size)
        self._make_cores(block_size)

    def reset(self):
        self.tone_core.reset()
        self.click_core.reset()
        self.perc_osc.reset()

    def process(self, block_size):
        pitch = jack_signal(self.pitch_in)
        p = pitch[0] if pitch is not None else 0.0
        pitch_hz = BASE_FREQ_C4 * 2.0 ** (p * 10.0)
        key = jack_signal(self.note_in)
        k = key[0] if key is not None else p
        note = int(60.5 + k * 120.0) if k > -0.5 else 0
        gate = jack_signal(self.gate_in)
        g = gate[0] if gate is not None else 0.0

        params = self.params
        perc_on = params["percussion"] >= 0.5
        drop = PERC_NORMAL_DROP if perc_on and params["perc_volume"] >= 0.5 else 1.0

        harmonics = tonewheel_harmonics(note, self._harmonics)
        levels = self._levels
        for i in range(9):
            pos = params[DRAWBARS[i]]
            pos = 0 if pos <= 0.0 else (8 if pos >= 8.0 else int(pos + 0.5))
            levels[i] = DRAWBAR_LEVELS[pos] * FOOTAGE_TRIM[i] * drop
        if perc_on:
            levels[8] = 0.0  # the 1' busbar carries the percussion
        self.tone_core.set_levels(levels, harmonics)

        out = self.audio_out.buffer
        extra = None
        env = jack_signal(self.perc_env_in)
        if perc_on and env is not None and env[0] > 1e-4:
            h = harmonics[PERC_FOOTAGE[1 if params["perc_harmonic"] >= 0.5 else 0]]
            f = pitch_hz * 0.5 * h
            self.perc_osc.render(block_size, base_freq_hz=f, sine=self._perc)
            mul(self._perc, env)
            scale(self._perc, PERC_LEVEL)
            extra = self._perc
        self.tone_core.render(pitch_hz, g, out, extra)
        self.click_core.render(self.tone_core.keyed, params["click"], out)

    # -- as a graph fragment ------------------------------------------------------------

    def fragment(self, f):
        """The tone, percussion and key click as graph nodes, with no bridge latency.

        A ``WAVETABLE`` plays the drawbar table through the contacts, with the
        percussion (an ``OSC`` sine under the manual's envelope) added before them.
        The click is white noise through a one-pole, under a ``DECAY`` on the gate's
        rising edge and another, quieter and shorter, on its falling edge; the rack's
        click is a fixed table of the same shape, so the two agree in level and
        length and not sample for sample.
        """
        import audiograph as ag

        self._ag = ag
        self._fragment = f
        gate = f.input(self.gate_in)
        env = f.input(self.perc_env_in)
        out = f.output(self.audio_out)

        b_osc, b_perc, b_tone = f.buffer(), f.buffer(), f.buffer()
        self._n_osc = f.add(ag.OSC, (None, None, None, None), b_osc)
        f.set(self._n_osc, ag.OSC_WAVEFORM, 8)
        f.set(self._n_osc, ag.OSC_LEVEL, 0.25)
        self._n_perc = f.add(ag.VCA, (b_osc, env, None), b_perc)
        f.set(self._n_perc, ag.VCA_SELECT, 0.0)

        self._n_tone = f.add(ag.WAVETABLE, (None, gate, b_perc), b_tone)

        b_up, b_white, b_lp = f.buffer(), f.buffer(), f.buffer()
        b_down_env, b_up_env, b_env, b_click = f.buffer(), f.buffer(), f.buffer(), f.buffer()
        self._n_up = f.add(ag.MIX, (gate,), b_up)
        f.set(self._n_up, 0, -1.0)
        f.set(self._n_up, ag.MIX_OFFSET, UNIT)
        self._n_down_env = f.add(ag.DECAY, (gate,), b_down_env)
        self._n_up_env = f.add(ag.DECAY, (b_up,), b_up_env)
        for node, seconds in ((self._n_down_env, CLICK_DOWN_SEC), (self._n_up_env, CLICK_UP_SEC)):
            f.set(node, ag.DECAY_DECAY, seconds)
            f.set(node, ag.DECAY_RESTRIKE, seconds)
        self._n_env = f.add(ag.MIX, (b_down_env, b_up_env), b_env)
        f.set(self._n_env, 0, CLICK_DOWN_LEVEL)
        f.set(self._n_env, 1, CLICK_UP_LEVEL)
        self._n_white = f.add(ag.NOISE, (), b_white)
        f.set(self._n_white, 0, UNIT)
        self._n_lp = f.add(ag.SAMPLE_HOLD, (b_white, None), b_lp)
        f.set(self._n_lp, ag.SH_RATE, float(self.sample_rate))
        f.set(self._n_lp, ag.SH_LAG, 0.5)
        self._n_click = f.add(ag.VCA, (b_lp, b_env, None), b_click)
        f.set(self._n_click, ag.VCA_SELECT, 0.0)

        self._n_sum = f.add(ag.MIX, (b_tone, b_click), out)
        f.set(self._n_sum, 0, 1.0)
        f.set(self._n_sum, 1, 1.0)

        self._cv = 0.0
        self._key = 0.0
        self._shown = None
        self._dirty = True
        f.watch(self.pitch_in, self._graph_pitch)
        f.watch(self.note_in, self._graph_note)
        f.bind(DRAWBARS + ("click", "percussion", "perc_volume", "perc_harmonic"), self._graph_dirty)
        f.before_run(self._graph_block)
        f.on_reset(self._graph_reset)
        f.prime(self._graph_prime)
        self._graph_update()

    def _graph_prime(self, run):
        """Start the table where the rack's tone core starts it.

        ``DrawbarToneCore`` chains its synth to a bridge that pulls 256 frames
        of the note's 220 Hz before the first block, so every voice begins that
        far into the table; the node begins there too.
        """
        f = self._fragment
        f.set(self._n_tone, self._ag.WAVETABLE_FREQUENCY, 220.0)
        for _ in range(max(1, ChunkedBridge.FRAMES // self.block_size)):
            run(f.bits, (self._n_tone,))
        self._graph_update()

    def _graph_pitch(self, val):
        self._cv = val
        self._dirty = True

    def _graph_note(self, val):
        self._key = val
        self._dirty = True

    def _graph_dirty(self):
        self._dirty = True

    def _graph_reset(self):
        f = self._fragment
        self._shown = None
        self._dirty = True
        for node in (
            self._n_osc,
            self._n_tone,
            self._n_down_env,
            self._n_up_env,
            self._n_white,
            self._n_lp,
        ):
            f.reset(node)

    def _graph_block(self):
        if self._dirty:
            self._graph_update()

    def _graph_update(self):
        self._dirty = False
        f = self._fragment
        ag = self._ag
        params = self.params
        p = self._cv
        pitch_hz = BASE_FREQ_C4 * 2.0 ** (p * 10.0)
        k = self._key
        note = int(60.5 + k * 120.0) if k > -0.5 else 0

        perc_on = params["percussion"] >= 0.5
        drop = PERC_NORMAL_DROP if perc_on and params["perc_volume"] >= 0.5 else 1.0
        harmonics = tonewheel_harmonics(note, self._harmonics)
        levels = self._levels
        for i in range(9):
            pos = params[DRAWBARS[i]]
            pos = 0 if pos <= 0.0 else (8 if pos >= 8.0 else int(pos + 0.5))
            levels[i] = DRAWBAR_LEVELS[pos] * FOOTAGE_TRIM[i] * drop
        if perc_on:
            levels[8] = 0.0  # the 1' busbar carries the percussion
        shown = (tuple(levels), tuple(harmonics))
        if shown != self._shown:
            self._shown = shown
            self.tone_core.set_levels(levels, harmonics)
            f.table(self._n_tone, self.tone_core._table_i16)

        f0 = pitch_hz * self.tone_core.base_ratio
        f.set(self._n_tone, ag.WAVETABLE_FREQUENCY, 10.0 if f0 < 10.0 else (16000.0 if f0 > 16000.0 else f0))
        h = harmonics[PERC_FOOTAGE[1 if params["perc_harmonic"] >= 0.5 else 0]]
        f.set(self._n_osc, ag.OSC_FREQUENCY, pitch_hz * 0.5 * h)
        f.set(self._n_perc, ag.VCA_GAIN, PERC_OSC_SCALE * PERC_LEVEL if perc_on else 0.0)
        f.set(self._n_click, ag.VCA_GAIN, params["click"] / 10.0 * KeyClickCore.LEVEL * CLICK_GAIN)
