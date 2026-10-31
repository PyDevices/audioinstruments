# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""WestCoastSynth, a West Coast voice inspired by the Buchla Music Easel: a complex oscillator (modulation and
principal oscillators with FM or AM), a timbre wavefolder, two vactrol
low-pass gates, two function generators and a random voltage source."""

import random

from ..core.bridge import FM_HZ_PER_DEPTH, OSC_LEVEL, PITCH_OCTAVES
from ..core.jack import SignalType
from ..core.module import Module
from ..core.signal import BASE_FREQ_C4, copy_into, fill, mul
from ..core.signal import BRIDGE_SCALE as UNIT
from ..dsp.function_generator import FunctionGeneratorCore
from ..dsp.lpg import LowPassGateCore
from ..dsp.oscillator import OscillatorCore
from ..dsp.wavefolder import WavefolderCore
from ._util import jack_signal

LPG_MODES = ("VCF", "VCA", "BOTH")

# audiooscillator's waveform flags
_SAW, _TRI, _SINE = 1, 4, 8


class WestCoastSynth(Module):
    NAME = "WestCoastSynth"
    DISPLAY_NAME = "WestCoastSynth"
    HP = 32

    MACRO_LABELS = (
        "timbre",
        "fm_index",
        "lpg1_decay",
        "lpg2_decay",
        "mod_freq",
        "mod_wave",
        "lpg1_mode",
        "lpg2_mode",
        "func1_rise",
        "func1_fall",
        "volume",
    )

    def _build(self):
        sr, n = self.sample_rate, self.block_size
        self.mod_osc = OscillatorCore(sr)
        self.princ_osc = OscillatorCore(sr)
        self.wavefolder = WavefolderCore(n)
        self.lpg1 = LowPassGateCore(sr, n)
        self.lpg2 = LowPassGateCore(sr, n)
        self.func1 = FunctionGeneratorCore(sr, n)
        self.func2 = FunctionGeneratorCore(sr, n)
        self.random_val = 0.0

        cv, gate, audio, trig = SignalType.CV, SignalType.GATE, SignalType.AUDIO, SignalType.TRIGGER
        self.kybd_cv_in = self.add_input("kybd_cv", "1V/Oct CV In", cv)
        self.kybd_gate_in = self.add_input("kybd_gate", "Gate In", gate)
        self.strike_in = self.add_input(
            "strike_in", "Strike Trigger In", trig, normal=self.kybd_gate_in
        )
        self.princ_pitch_in = self.add_input(
            "princ_pitch", "Principal Pitch In", cv, normal=self.kybd_cv_in
        )
        self.mod_pitch_in = self.add_input(
            "mod_pitch", "Modulation Pitch In", cv, normal=self.kybd_cv_in
        )
        self.timbre_cv_in = self.add_input("timbre_cv", "Timbre CV In", cv)
        self.fm_index_cv_in = self.add_input("fm_index_cv", "FM Index CV In", cv)
        self.lpg1_audio_in = self.add_input("lpg1_audio", "LPG 1 Audio In", audio)
        self.lpg1_ctrl_in = self.add_input("lpg1_ctrl", "LPG 1 Control In", cv)
        self.lpg2_audio_in = self.add_input("lpg2_audio", "LPG 2 Audio In", audio)
        self.lpg2_ctrl_in = self.add_input("lpg2_ctrl", "LPG 2 Control In", cv)

        self.princ_raw_out = self.add_output("princ_raw", "Principal Raw Out", audio)
        self.timbre_out = self.add_output("timbre_out", "Timbre Folded Out", audio)
        self.mod_osc_out = self.add_output("mod_osc_out", "Modulation Osc Out", audio)
        self.lpg1_out = self.add_output("lpg1_out", "LPG 1 Out", audio)
        self.lpg2_out = self.add_output("lpg2_out", "LPG 2 Out", audio)
        self.func1_out = self.add_output("func1_out", "Function 1 Out", cv)
        self.func2_out = self.add_output("func2_out", "Function 2 Out", cv)
        self.random_out = self.add_output("random_out", "Random Voltage Out", cv)
        self.lpg1_ctrl_in.normal = self.func1_out
        self.lpg2_ctrl_in.normal = self.func2_out
        self.lpg1_audio_in.normal = self.timbre_out
        self.lpg2_audio_in.normal = self.lpg1_out

        self.add_param(
            "princ_freq", "Principal Pitch Offset (octaves)", default=0.0, min_val=-3.0, max_val=3.0
        )
        self.add_param(
            "princ_wave", "Principal Wave (0=Sine, 1=Tri)", default=0.0, min_val=0.0, max_val=1.0
        )
        self.add_param(
            "mod_freq", "Mod Osc Pitch Offset (octaves)", default=0.0, min_val=-4.0, max_val=4.0
        )
        self.add_param(
            "mod_wave", "Mod Osc Wave (0=Saw, 1=Sine)", default=0.0, min_val=0.0, max_val=1.0
        )
        self.add_param("fm_index", "FM Index", default=0.0, min_val=0.0, max_val=2.0)
        self.add_param("mod_mode", "Mod Mode (0=FM, 1=AM)", default=0.0, min_val=0.0, max_val=1.0)
        self.add_param("timbre", "Timbre (fold)", default=0.20, min_val=0.0, max_val=1.0)
        self.add_param("symmetry", "Wavefolder Symmetry", default=0.0, min_val=-1.0, max_val=1.0)
        self.add_param(
            "lpg1_mode", "LPG 1 Mode (0=VCF, 1=VCA, 2=BOTH)", default=2.0, min_val=0.0, max_val=2.0
        )
        self.add_param("lpg1_decay", "LPG 1 Decay (s)", default=0.25, min_val=0.02, max_val=2.0)
        self.add_param(
            "lpg2_mode", "LPG 2 Mode (0=VCF, 1=VCA, 2=BOTH)", default=2.0, min_val=0.0, max_val=2.0
        )
        self.add_param("lpg2_decay", "LPG 2 Decay (s)", default=0.35, min_val=0.02, max_val=2.0)
        self.add_param("func1_rise", "Func 1 Rise (s)", default=0.005, min_val=0.002, max_val=3.0)
        self.add_param("func1_fall", "Func 1 Fall (s)", default=0.20, min_val=0.01, max_val=5.0)
        self.add_param("func2_rise", "Func 2 Rise (s)", default=0.01, min_val=0.002, max_val=3.0)
        self.add_param("func2_fall", "Func 2 Fall (s)", default=0.35, min_val=0.01, max_val=5.0)
        self.add_param("volume", "Master Output Level", default=1.0, min_val=0.0, max_val=1.5)
        for name in ("_mod_sine", "_mod_saw", "_sine", "_tri", "_fm", "_trig"):
            self.add_scratch(name)

    def set_block_size(self, block_size):
        super().set_block_size(block_size)
        sr = self.sample_rate
        self.wavefolder.set_block_size(block_size)
        self.lpg1 = LowPassGateCore(sr, block_size)
        self.lpg2 = LowPassGateCore(sr, block_size)
        self.func1.set_block_size(block_size)
        self.func2.set_block_size(block_size)

    def reset(self):
        for core in (self.mod_osc, self.princ_osc, self.lpg1, self.lpg2, self.func1, self.func2):
            core.reset()

    def process(self, block_size):
        p = self.params
        n = block_size

        # function generators fire from the gate or the strike input
        gate = jack_signal(self.kybd_gate_in)
        strike = jack_signal(self.strike_in)
        trig = gate if strike is None else strike
        if gate is not None and strike is not None and strike is not gate:
            copy_into(self._trig, gate)
            self._trig += strike
            trig = self._trig
        before = self.func1.state
        self.func1.render(trig, self.func1_out.buffer, p["func1_rise"], p["func1_fall"])
        if before == 0 and self.func1.state != 0:
            self.random_val = (random.random() * 2.0 - 1.0) * 0.5
        self.random_out.buffer[:] = self.random_val
        self.func2.render(trig, self.func2_out.buffer, p["func2_rise"], p["func2_fall"])

        # modulation oscillator
        self.mod_osc.render(
            n,
            BASE_FREQ_C4 * (2.0 ** p["mod_freq"]),
            self.mod_pitch_in.get_buffer(),
            saw=self._mod_saw,
            sine=self._mod_sine,
        )
        mod_sig = self._mod_sine if p["mod_wave"] >= 0.5 else self._mod_saw
        copy_into(self.mod_osc_out.buffer, mod_sig)

        # principal oscillator, FM or AM by the modulation oscillator
        index = p["fm_index"]
        fm_cv = jack_signal(self.fm_index_cv_in)
        if fm_cv is not None:
            index += float(fm_cv[0])
        am = p["mod_mode"] >= 0.5
        fm = None
        if not am and index != 0.0:
            fm = self._fm
            copy_into(fm, mod_sig)
            fm *= index
        self.princ_osc.render(
            n,
            BASE_FREQ_C4 * (2.0 ** p["princ_freq"]),
            self.princ_pitch_in.get_buffer(),
            fm_cv=fm,
            fm_depth=1.0 if fm is not None else 0.0,
            sine=self._sine,
            tri=self._tri,
        )
        raw = self.princ_raw_out.buffer
        copy_into(raw, self._tri if p["princ_wave"] >= 0.5 else self._sine)
        if am and index != 0.0:
            # raw *= 1 + mod * index
            fm = self._fm
            copy_into(fm, mod_sig)
            fm *= index
            fm += 1.0
            mul(raw, fm)

        self.wavefolder.render(
            raw,
            self.timbre_out.buffer,
            fold=p["timbre"],
            symmetry=p["symmetry"],
            fold_cv=jack_signal(self.timbre_cv_in),
        )

        self.lpg1.render(
            self.lpg1_audio_in.get_buffer(),
            self.lpg1_out.buffer,
            control=self.lpg1_ctrl_in.get_buffer(),
            strike=strike,
            decay_time=p["lpg1_decay"],
            mode=LPG_MODES[int(p["lpg1_mode"]) % 3],
        )
        self.lpg2.render(
            self.lpg2_audio_in.get_buffer(),
            self.lpg2_out.buffer,
            control=self.lpg2_ctrl_in.get_buffer(),
            strike=strike,
            decay_time=p["lpg2_decay"],
            mode=LPG_MODES[int(p["lpg2_mode"]) % 3],
        )
        if p["volume"] != 1.0:
            self.lpg2_out.buffer *= p["volume"]

    # -- the graph form ------------------------------------------------------------------

    def fragment(self, f):
        import audiograph as ag

        # The wavefolder and the low-pass gates are newer nodes; without them
        # the module stays on the rack.
        if not hasattr(ag, "WAVEFOLD") or not hasattr(ag, "LPG"):
            return False
        # The function generators run in Python, so their trigger must be a
        # value a block (a MIDI module's gate) and their outputs must not be
        # cabled as audio-rate signals; the FM index CV is read once a block
        # from Python too. Anything else stays on the rack.
        if self.kybd_gate_in.is_connected and not f.is_control(self.kybd_gate_in):
            return False
        for jack in (self.strike_in, self.fm_index_cv_in):
            if jack.is_connected:
                return False
        for jack in (self.func1_out, self.func2_out):
            if jack.cables:
                return False
        self._ag = ag
        self._gate = 0.0
        b_mod = f.output(self.mod_osc_out)
        b_fm = f.buffer()
        b_osc = f.buffer()
        b_am = f.buffer()
        strike = f.input(self.strike_in)
        self._n_mod = f.add(ag.OSC, (f.input(self.mod_pitch_in), None, None, None), b_mod)
        self._n_fm = f.add(ag.MIX, (b_mod,), b_fm)
        self._n_princ = f.add(ag.OSC, (f.input(self.princ_pitch_in), b_fm, None, None), b_osc)
        # AM: raw * (1 + mod * index), as a VCA at gain 2 on half of that
        self._n_am = f.add(ag.MIX, (b_mod,), b_am)
        b_raw = f.output(self.princ_raw_out)
        self._n_raw = f.add(ag.VCA, (b_osc, b_am, None), b_raw)
        self._n_fold = f.add(
            ag.WAVEFOLD,
            (b_raw, f.input(self.timbre_cv_in)),
            f.output(self.timbre_out),
        )
        # A control input cabled is the gate's control; otherwise the
        # function generator's level reaches the gate as its manual level.
        self._ctrl1 = self.lpg1_ctrl_in.is_connected
        self._ctrl2 = self.lpg2_ctrl_in.is_connected
        self._n_lpg1 = f.add(
            ag.LPG,
            (
                f.input(self.lpg1_audio_in),
                f.input(self.lpg1_ctrl_in) if self._ctrl1 else None,
                strike,
            ),
            f.output(self.lpg1_out),
        )
        self._n_lpg2 = f.add(
            ag.LPG,
            (
                f.input(self.lpg2_audio_in),
                f.input(self.lpg2_ctrl_in) if self._ctrl2 else None,
                strike,
            ),
            f.output(self.lpg2_out),
        )
        for node in (self._n_mod, self._n_princ):
            f.set(node, ag.OSC_LEVEL, OSC_LEVEL)
            f.set(node, ag.OSC_PITCH_OCTAVES, PITCH_OCTAVES)
        f.set(self._n_am, ag.MIX_OFFSET, 0.5 * UNIT)
        f.set(self._n_raw, ag.VCA_SELECT, 0.0)
        f.set(self._n_raw, ag.VCA_GAIN, 2.0)
        self._random = (
            f.control(self.random_out, self.random_val) if self.random_out.cables else None
        )
        f.bind(("mod_freq", "mod_wave", "princ_freq", "princ_wave"), self._graph_oscillators)
        f.bind(("fm_index", "mod_mode"), self._graph_modulation)
        f.bind(("timbre", "symmetry"), self._graph_fold)
        f.bind(("lpg1_mode", "lpg1_decay", "lpg2_mode", "lpg2_decay", "volume"), self._graph_gates)
        if self.kybd_gate_in.is_connected:
            f.watch(self.kybd_gate_in, self._graph_gate)
        f.before_run(self._graph_block)
        f.on_reset(self._graph_reset)

    def _graph_oscillators(self):
        p = self.params
        f = self._fragment
        ag = self._ag
        f.set(self._n_mod, ag.OSC_FREQUENCY, BASE_FREQ_C4 * (2.0 ** p["mod_freq"]))
        f.set(self._n_mod, ag.OSC_WAVEFORM, _SINE if p["mod_wave"] >= 0.5 else _SAW)
        f.set(self._n_princ, ag.OSC_FREQUENCY, BASE_FREQ_C4 * (2.0 ** p["princ_freq"]))
        f.set(self._n_princ, ag.OSC_WAVEFORM, _TRI if p["princ_wave"] >= 0.5 else _SINE)

    def _graph_modulation(self):
        p = self.params
        f = self._fragment
        ag = self._ag
        index = p["fm_index"]
        am = p["mod_mode"] >= 0.5
        fm = not am and index != 0.0
        f.set(self._n_fm, 0, index if fm else 0.0)
        f.set(self._n_princ, ag.OSC_FM_DEPTH, FM_HZ_PER_DEPTH if fm else 0.0)
        f.set(self._n_am, 0, index * 0.5 if am else 0.0)

    def _graph_fold(self):
        p = self.params
        f = self._fragment
        f.set(self._n_fold, self._ag.WAVEFOLD_FOLD, p["timbre"])
        f.set(self._n_fold, self._ag.WAVEFOLD_SYMMETRY, p["symmetry"])

    def _graph_gates(self):
        p = self.params
        f = self._fragment
        ag = self._ag
        f.set(self._n_lpg1, ag.LPG_MODE, int(p["lpg1_mode"]) % 3)
        f.set(self._n_lpg1, ag.LPG_DECAY, p["lpg1_decay"])
        f.set(self._n_lpg2, ag.LPG_MODE, int(p["lpg2_mode"]) % 3)
        f.set(self._n_lpg2, ag.LPG_DECAY, p["lpg2_decay"])
        f.set(self._n_lpg2, ag.LPG_LEVEL, p["volume"])

    def _graph_gate(self, value):
        self._gate = value

    def _graph_block(self):
        # process()'s function generators and random voltage, once a block
        p = self.params
        trig = None
        if self.kybd_gate_in.is_connected:
            trig = self._trig
            fill(trig, self._gate)
        before = self.func1.state
        self.func1.render(trig, self.func1_out.buffer, p["func1_rise"], p["func1_fall"])
        if before == 0 and self.func1.state != 0:
            self.random_val = (random.random() * 2.0 - 1.0) * 0.5
            if self._random is not None:
                self._random.set(self.random_val)
        self.func2.render(trig, self.func2_out.buffer, p["func2_rise"], p["func2_fall"])
        f = self._fragment
        ag = self._ag
        if not self._ctrl1:
            f.set(self._n_lpg1, ag.LPG_MANUAL, float(self.func1_out.buffer[0]))
        if not self._ctrl2:
            f.set(self._n_lpg2, ag.LPG_MANUAL, float(self.func2_out.buffer[0]))

    def _graph_reset(self):
        # as reset(): the oscillators, the gates and the function generators
        f = self._fragment
        for node in (self._n_mod, self._n_princ, self._n_lpg1, self._n_lpg2):
            f.reset(node)
        self.func1.reset()
        self.func2.reset()
