# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""HybridMono, a voice inspired by the EDP Wasp: two DCOs, a CMOS multimode filter whose inverter stages
clip, an envelope, an LFO and a VCA, with a small patch panel.

Compiled to a graph (``vrack.core.graph``), the voice is eight nodes: the
envelope, the two DCOs, their mix, the filter CV mix, the CMOS filter (a
``TWOPOLE``), the VCA's CV and the exponential VCA, and the LFO when a cable
takes its triangle. A key that is a control (a MIDI module's) tunes the DCOs in
Hz, where the rack rounds the pitch to the oscillator wire's 0.7 cent step. The
graph's wires are 16-bit where the rack's blocks are float, and the filter
clips in every stage, so a hard-driven note turns that rounding into a few
counts, now and then a sample out of step. The VCA's output saturates at 2.0
(20 V) on the wire, which only a volume above 1.1 reaches. The exponential VCA
passes 10^-3 of the filter at an envelope of zero, and a released voice plays
that until the voice mix parks it, once it falls under 2 mV for 30 ms, as the
rack's does.
"""

from ..core.bridge import OSC_LEVEL, PITCH_OCTAVES
from ..core.jack import SignalType
from ..core.module import Module
from ..core.signal import BASE_FREQ_C4, add, add_scaled, copy_into
from ..core.signal import BRIDGE_SCALE as UNIT
from ..dsp.amplifier import AmplifierCore
from ..dsp.envelope import EnvelopeCore
from ..dsp.lfo import LFOCore
from ..dsp.oscillator import OscillatorCore
from ..dsp.twopole import CMOSFilterCore
from ._util import jack_signal, knob_hz


class HybridMono(Module):
    NAME = "HybridMono"
    DISPLAY_NAME = "HybridMono"
    HP = 26

    MACRO_LABELS = (
        "filter_freq",
        "filter_res",
        "filter_mode",
        "dco2_pitch",
        "drive",
        "env_attack",
        "env_decay",
        "env_sustain",
        "lfo_rate",
        "volume",
    )

    def _build(self):
        sr, n = self.sample_rate, self.block_size
        self.dco1 = OscillatorCore(sr)
        self.dco2 = OscillatorCore(sr)
        self.filter = CMOSFilterCore(sr)
        self.env = EnvelopeCore(sr, n)
        self.lfo = LFOCore(sr, n)
        self.vca = AmplifierCore(n)

        cv, gate, audio = SignalType.CV, SignalType.GATE, SignalType.AUDIO
        self.kybd_cv_in = self.add_input("kybd_cv", "1V/Oct CV In", cv)
        self.kybd_gate_in = self.add_input("kybd_gate", "Gate In", gate)
        self.filter_cv_in = self.add_input("filter_cv", "Filter CV In", cv)
        self.audio_in = self.add_input("audio_in", "Audio In", audio)
        self.dco1_out = self.add_output("dco1_out", "DCO 1 Out", audio)
        self.dco2_out = self.add_output("dco2_out", "DCO 2 Out", audio)
        self.filter_out = self.add_output("filter_out", "Filter Out", audio)
        self.vca_out = self.add_output("vca_out", "Master Out", audio)
        self.env_out = self.add_output("env_out", "Envelope Out", cv)
        self.lfo_out = self.add_output("lfo_out", "LFO Out", cv)

        self.add_param(
            "dco1_oct",
            "DCO 1 Octave (0=32', 1=16', 2=8', 3=4')",
            default=2.0,
            min_val=0.0,
            max_val=3.0,
        )
        self.add_param(
            "dco1_wave", "DCO 1 Wave (0=Saw, 1=Pulse)", default=0.0, min_val=0.0, max_val=1.0
        )
        self.add_param("dco1_pw", "DCO 1 Pulse Width", default=0.5, min_val=0.1, max_val=0.9)
        self.add_param("dco1_level", "DCO 1 Level", default=0.75, min_val=0.0, max_val=1.0)
        self.add_param(
            "dco2_oct",
            "DCO 2 Octave (0=16', 1=8', 2=4', 3=2')",
            default=1.0,
            min_val=0.0,
            max_val=3.0,
        )
        self.add_param(
            "dco2_pitch", "DCO 2 Detune (octaves)", default=0.02, min_val=-1.0, max_val=1.0
        )
        self.add_param(
            "dco2_wave", "DCO 2 Wave (0=Saw, 1=Square)", default=1.0, min_val=0.0, max_val=1.0
        )
        self.add_param("dco2_level", "DCO 2 Level", default=0.75, min_val=0.0, max_val=1.0)
        self.add_param("filter_freq", "Filter Frequency", default=0.45, min_val=0.0, max_val=1.0)
        self.add_param("filter_res", "Filter Q", default=0.45, min_val=0.0, max_val=1.0)
        self.add_param(
            "filter_mode", "Filter Mode (0=LP, 1=BP, 2=HP)", default=0.0, min_val=0.0, max_val=2.0
        )
        self.add_param(
            "filter_env_depth", "Filter Env Depth", default=0.80, min_val=0.0, max_val=1.0
        )
        self.add_param("drive", "CMOS Drive", default=1.3, min_val=0.5, max_val=3.0)
        self.add_param("env_attack", "Attack (s)", default=0.005, min_val=0.002, max_val=3.0)
        self.add_param("env_decay", "Decay / Release (s)", default=0.22, min_val=0.01, max_val=5.0)
        self.add_param("env_sustain", "Sustain", default=0.35, min_val=0.0, max_val=1.0)
        self.add_param("lfo_rate", "LFO Frequency (Hz)", default=5.0, min_val=0.1, max_val=30.0)
        self.add_param("volume", "Master Output Level", default=1.0, min_val=0.0, max_val=1.5)
        for name in ("_saw1", "_pulse1", "_saw2", "_pulse2", "_mix", "_fcv", "_vcv", "_tmp"):
            self.add_scratch(name)

    def set_block_size(self, block_size):
        super().set_block_size(block_size)
        self.env.set_block_size(block_size)
        self.lfo.set_block_size(block_size)
        self.vca.set_block_size(block_size)

    def reset(self):
        for core in (self.dco1, self.dco2, self.filter, self.env, self.lfo):
            core.reset()

    def process(self, block_size):
        p = self.params
        n = block_size
        self.lfo.render(p["lfo_rate"], tri=self.lfo_out.buffer)
        self.env.set_times(p["env_attack"], p["env_decay"], p["env_sustain"], p["env_decay"])
        self.env.render(jack_signal(self.kybd_gate_in), self.env_out.buffer)

        cv = self.kybd_cv_in.get_buffer()
        saw1 = p["dco1_wave"] < 0.5
        saw2 = p["dco2_wave"] < 0.5
        self.dco1.render(
            n,
            BASE_FREQ_C4 * (2.0 ** (int(p["dco1_oct"]) % 4 - 2)),
            cv,
            pulse_width=p["dco1_pw"],
            saw=self._saw1 if saw1 else None,
            pulse=None if saw1 else self._pulse1,
        )
        self.dco2.render(
            n,
            BASE_FREQ_C4 * (2.0 ** (int(p["dco2_oct"]) % 4 - 1 + p["dco2_pitch"])),
            cv,
            pulse_width=0.5,
            saw=self._saw2 if saw2 else None,
            pulse=None if saw2 else self._pulse2,
        )
        src1 = self._saw1 if saw1 else self._pulse1
        src2 = self._saw2 if saw2 else self._pulse2
        copy_into(self.dco1_out.buffer, src1)
        copy_into(self.dco2_out.buffer, src2)
        mix = self._mix
        copy_into(mix, src1)
        mix *= p["dco1_level"] * 0.707
        add_scaled(mix, src2, p["dco2_level"] * 0.707, self._tmp)
        ext = jack_signal(self.audio_in)
        if ext is not None:
            add(mix, ext)

        fcv = self._fcv
        copy_into(fcv, self.env_out.buffer)
        fcv *= p["filter_env_depth"]
        ext_cv = jack_signal(self.filter_cv_in)
        if ext_cv is not None:
            add(fcv, ext_cv)
        self.filter.render(
            n,
            mix,
            self.filter_out.buffer,
            cutoff_hz=knob_hz(p["filter_freq"], 30.0, 13500.0),
            cutoff_cv=fcv,
            resonance=p["filter_res"],
            mode=CMOSFilterCore.MODES[int(p["filter_mode"]) % 3],
            drive=p["drive"],
        )
        vcv = self._vcv
        copy_into(vcv, self.env_out.buffer)
        vcv *= p["volume"]
        self.vca.render(self.filter_out.buffer, self.vca_out.buffer, vcv, exponential=True)

    # -- as a graph fragment ------------------------------------------------------------

    #: The voice mix's level, and the master's scale when nothing stands between, which
    #: ``VoiceMix`` folds into this voice's last gain so its wire is rounded once.
    graph_fold_gain = 1.0

    def graph_fold(self, gain):
        """Take ``gain`` into the voice's last gain (see ``graph_fold_gain``)."""
        self.graph_fold_gain = gain
        if getattr(self, "_fragment", None) is not None:
            self._graph_fold_gain()

    def _graph_fold_gain(self):
        self._fragment.set(self._n_vca, self._ag.VCA_GAIN, self.graph_fold_gain)

    def fragment(self, f):
        import audiograph as ag

        # The CMOS filter and the exponential VCA are newer nodes: an audiograph
        # without them would have to approximate both, so the voice stays on the rack.
        if not hasattr(ag, "TWOPOLE") or not hasattr(ag, "VCA_CURVE"):
            return False
        self._ag = ag
        # A key from a MIDI module is a control, whose value arrives in floats,
        # so the DCOs are tuned in Hz; a pitch that is a signal goes down the wire.
        self._keyed = f.is_control(self.kybd_cv_in)
        self._key = 0.0
        pitch = None if self._keyed else f.input(self.kybd_cv_in)
        gate = f.input(self.kybd_gate_in)
        ext = f.input(self.audio_in)
        ext_cv = f.input(self.filter_cv_in)
        b_env = f.output(self.env_out)
        b_dco1 = f.output(self.dco1_out)
        b_dco2 = f.output(self.dco2_out)
        b_filt = f.output(self.filter_out)
        b_mix = f.buffer()
        b_fcv = f.buffer()
        b_vcv = f.buffer()
        self._n_env = f.add(ag.ENV, (gate,), b_env)
        # The LFO only feeds the lfo_out jack: without a cable on it, it costs nothing.
        if self.lfo_out.cables:
            self._n_lfo = f.add(ag.LFO, (), f.output(self.lfo_out))
            f.set(self._n_lfo, ag.LFO_SHAPE, ag.LFO_TRIANGLE)
            f.set(self._n_lfo, ag.LFO_AMPLITUDE, 0.5 * UNIT)
        else:
            self._n_lfo = None
        self._n_dco1 = f.add(ag.OSC, (pitch, None, None, None), b_dco1)
        self._n_dco2 = f.add(ag.OSC, (pitch, None, None, None), b_dco2)
        self._n_mix = f.add(ag.MIX, (b_dco1, b_dco2, ext), b_mix)
        self._n_fcv = f.add(ag.MIX, (b_env, ext_cv), b_fcv)
        self._n_filt = f.add(ag.TWOPOLE, (b_mix, b_fcv), b_filt)
        self._n_vcv = f.add(ag.MIX, (b_env,), b_vcv)
        self._n_vca = f.add(ag.VCA, (b_filt, b_vcv, None), f.output(self.vca_out))
        for node in (self._n_dco1, self._n_dco2):
            f.set(node, ag.OSC_LEVEL, OSC_LEVEL)
            f.set(node, ag.OSC_PITCH_OCTAVES, PITCH_OCTAVES)
        f.set(self._n_dco2, ag.OSC_PULSE_WIDTH, 0.5)
        f.set(self._n_mix, 2, 1.0)
        f.set(self._n_fcv, 1, 1.0)
        # the filter's CV moves the cutoff by ten octaves a unit, as pitch_to_frequency does
        f.set(self._n_filt, ag.TWOPOLE_DEPTH, 1.0)
        f.set(self._n_vca, ag.VCA_SELECT, 0.0)
        f.set(self._n_vca, ag.VCA_CURVE, ag.VCA_EXPONENTIAL)
        f.set(self._n_vca, ag.VCA_GAIN, self.graph_fold_gain)
        f.bind(("dco1_oct", "dco2_oct", "dco2_pitch"), self._graph_pitch)
        f.bind(("dco1_wave", "dco1_pw", "dco2_wave"), self._graph_waves)
        f.bind(("dco1_level", "dco2_level"), self._graph_mix)
        f.bind(("filter_freq", "filter_res", "filter_mode", "drive"), self._graph_filter)
        f.bind(("filter_env_depth",), self._graph_fcv)
        f.bind(("volume",), self._graph_volume)
        f.bind(("env_attack", "env_decay", "env_sustain"), self._graph_env)
        f.bind(("lfo_rate",), self._graph_lfo)
        if self._keyed:
            f.watch(self.kybd_cv_in, self._graph_key)
        f.on_reset(self._graph_reset)

    def _graph_pitch(self):
        p = self.params
        f = self._fragment
        ag = self._ag
        key = 2.0 ** (10.0 * self._key)
        f.set(
            self._n_dco1,
            ag.OSC_FREQUENCY,
            BASE_FREQ_C4 * (2.0 ** (int(p["dco1_oct"]) % 4 - 2)) * key,
        )
        f.set(
            self._n_dco2,
            ag.OSC_FREQUENCY,
            BASE_FREQ_C4 * (2.0 ** (int(p["dco2_oct"]) % 4 - 1 + p["dco2_pitch"])) * key,
        )

    def _graph_key(self, value):
        self._key = value
        self._graph_pitch()

    def _graph_waves(self):
        p = self.params
        f = self._fragment
        ag = self._ag
        f.set(self._n_dco1, ag.OSC_WAVEFORM, 1 if p["dco1_wave"] < 0.5 else 2)
        f.set(self._n_dco1, ag.OSC_PULSE_WIDTH, p["dco1_pw"])
        f.set(self._n_dco2, ag.OSC_WAVEFORM, 1 if p["dco2_wave"] < 0.5 else 2)

    def _graph_mix(self):
        p = self.params
        f = self._fragment
        f.set(self._n_mix, 0, p["dco1_level"] * 0.707)
        f.set(self._n_mix, 1, p["dco2_level"] * 0.707)

    def _graph_filter(self):
        p = self.params
        f = self._fragment
        ag = self._ag
        mode = (ag.TWOPOLE_CMOS_LOWPASS, ag.TWOPOLE_CMOS_BANDPASS, ag.TWOPOLE_CMOS_HIGHPASS)
        f.set(self._n_filt, ag.TWOPOLE_TYPE, mode[int(p["filter_mode"]) % 3])
        f.set(self._n_filt, ag.TWOPOLE_CUTOFF_HZ, knob_hz(p["filter_freq"], 30.0, 13500.0))
        f.set(self._n_filt, ag.TWOPOLE_RESONANCE, p["filter_res"])
        f.set(self._n_filt, ag.TWOPOLE_DRIVE, p["drive"])

    def _graph_fcv(self):
        self._fragment.set(self._n_fcv, 0, self.params["filter_env_depth"])

    def _graph_volume(self):
        self._fragment.set(self._n_vcv, 0, self.params["volume"])

    def _graph_env(self):
        p = self.params
        f = self._fragment
        ag = self._ag
        f.set(self._n_env, ag.ENV_ATTACK, p["env_attack"])
        f.set(self._n_env, ag.ENV_DECAY, p["env_decay"])
        f.set(self._n_env, ag.ENV_SUSTAIN, p["env_sustain"])
        f.set(self._n_env, ag.ENV_RELEASE, p["env_decay"])

    def _graph_lfo(self):
        if self._n_lfo is not None:
            self._fragment.set(self._n_lfo, self._ag.LFO_RATE, self.params["lfo_rate"])

    def _graph_reset(self):
        # as reset(): the DCOs' phases, the filter, the envelope and the LFO
        f = self._fragment
        for node in (self._n_dco1, self._n_dco2, self._n_filt, self._n_env, self._n_lfo):
            if node is not None:
                f.reset(node)
