# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Duo20, a voice inspired by the Korg MS-20: two VCOs, a high-pass into a low-pass Sallen-Key pair
with diode-clipped peak, two envelopes, a modulation generator, noise, sample
and hold, and a patch panel.

Compiled to a graph (``vrack.core.graph``), the voice is EG2, the glide (a
``LAG``), four oscillators (each VCO's wave, and the two pulses the ring
modulator reads), the ring (a ``VCA`` pushed to the rail, then scaled), the VCO
mix, the two Sallen-Key filters (``TWOPOLE``) with their CV mixes, and the
exponential VCA. White noise runs only while VCO1 plays it or a jack hears it;
EG1, EG2 reverse, the MG and the sample and hold only with a cable on their
outputs. A cable on the pink noise leaves the voice on the rack: the graph has
no pinking filter.

Where the two differ: the wires are 16-bit where the rack's blocks are float,
so a note matches to a few counts, and a filter driven near its own edge (the
LPF as a triangle's note releases, the HPF at full peak) parts by up to a
percent there. The glide's pitch matches to a count, but its rounding parts
from the rack's on some samples, so a glided note's phase drifts a few samples
away. The noise is the graph's own generator. The MG's square can land a sample
from the rack's. The rack stops a VCO that nothing reads (VCO1 on noise); the graph's keeps
running, so switching back mid-note starts at another phase.
"""

from ..core.bridge import OSC_LEVEL, PITCH_OCTAVES
from ..core.jack import SignalType
from ..core.module import Module
from ..core.signal import BASE_FREQ_C4, add, add_scaled, copy_into, mul
from ..core.signal import BRIDGE_SCALE as UNIT
from ..dsp.amplifier import AmplifierCore
from ..dsp.envelope import EnvelopeCore
from ..dsp.lfo import LFOCore
from ..dsp.noise import NoiseGenerator
from ..dsp.oscillator import OscillatorCore
from ..dsp.twopole import SallenKeyHPFCore, SallenKeyLPFCore
from ..dsp.utility import GlideCore, SampleAndHoldCore
from ._util import jack_signal, knob_hz

VCO1_OCTAVES = (-2.0, -1.0, 0.0, 1.0)  # 32', 16', 8', 4'
VCO2_OCTAVES = (-1.0, 0.0, 1.0, 2.0)  # 16', 8', 4', 2'


class Duo20(Module):
    NAME = "Duo20"
    DISPLAY_NAME = "Duo20"
    HP = 30

    MACRO_LABELS = (
        "lpf_cutoff",
        "lpf_peak",
        "hpf_cutoff",
        "hpf_peak",
        "vco2_pitch",
        "lpf_eg2_depth",
        "eg2_attack",
        "eg2_decay",
        "eg2_sustain",
        "eg2_release",
        "volume",
    )

    def _build(self):
        sr, n = self.sample_rate, self.block_size
        self.osc1 = OscillatorCore(sr)
        self.osc2 = OscillatorCore(sr)
        self.hpf = SallenKeyHPFCore(sr)
        self.lpf = SallenKeyLPFCore(sr)
        self.eg1 = EnvelopeCore(sr, n)
        self.eg2 = EnvelopeCore(sr, n)
        self.mg = LFOCore(sr, n)
        self.noise = NoiseGenerator()
        self.sh = SampleAndHoldCore(n)
        self.vca = AmplifierCore(n)
        self.glide = GlideCore(sr, n)

        cv, gate, audio, clock = SignalType.CV, SignalType.GATE, SignalType.AUDIO, SignalType.CLOCK
        self.kybd_cv_in = self.add_input("kybd_cv", "1V/Oct CV In", cv)
        self.kybd_gate_in = self.add_input("kybd_gate", "Gate In", gate)
        self.total_cutoff_cv_in = self.add_input("total_cutoff_cv", "Total Cutoff CV In", cv)
        self.hpf_cutoff_in = self.add_input("hpf_cutoff_cv", "HPF Cutoff CV In", cv)
        self.lpf_cutoff_in = self.add_input("lpf_cutoff_cv", "LPF Cutoff CV In", cv)
        self.hpf_audio_in = self.add_input("hpf_audio_in", "HPF Audio In", audio)
        self.lpf_audio_in = self.add_input("lpf_audio_in", "LPF Audio In", audio)
        self.vca_audio_in = self.add_input("vca_audio_in", "VCA Audio In", audio)
        self.vca_cv_in = self.add_input("vca_cv_in", "VCA Gain CV In", cv)
        self.sh_in = self.add_input("sh_in", "Sample & Hold In", cv)
        self.sh_clock_in = self.add_input("sh_clock", "Sample & Hold Clock In", clock)

        self.vco1_out = self.add_output("vco1_out", "VCO 1 Out", audio)
        self.vco2_out = self.add_output("vco2_out", "VCO 2 Out", audio)
        self.ring_mod_out = self.add_output("ring_mod_out", "Ring Mod Out", audio)
        self.white_noise_out = self.add_output("white_noise", "White Noise Out", audio)
        self.pink_noise_out = self.add_output("pink_noise", "Pink Noise Out", audio)
        self.mg_tri_out = self.add_output("mg_tri", "MG Triangle Out", cv)
        self.mg_pulse_out = self.add_output("mg_pulse", "MG Pulse Out", clock)
        self.eg1_out = self.add_output("eg1_out", "EG 1 Out", cv)
        self.eg2_out = self.add_output("eg2_out", "EG 2 Out", cv)
        self.eg2_rev_out = self.add_output("eg2_rev_out", "EG 2 Reverse Out", cv)
        self.hpf_out = self.add_output("hpf_out", "HPF Out", audio)
        self.lpf_out = self.add_output("lpf_out", "LPF Out", audio)
        self.vca_out = self.add_output("vca_out", "VCA Master Out", audio)
        self.sh_out = self.add_output("sh_out", "Sample & Hold Out", cv)
        self.lpf_audio_in.normal = self.hpf_out
        self.vca_audio_in.normal = self.lpf_out
        self.vca_cv_in.normal = self.eg2_out
        self.sh_in.normal = self.white_noise_out
        self.sh_clock_in.normal = self.mg_pulse_out

        self.add_param("glide", "Portamento (s)", default=0.0, min_val=0.0, max_val=1.0)
        self.add_param(
            "vco1_scale",
            "VCO 1 Scale (0=32', 1=16', 2=8', 3=4')",
            default=2.0,
            min_val=0.0,
            max_val=3.0,
        )
        self.add_param(
            "vco1_wave",
            "VCO 1 Wave (0=Tri, 1=Saw, 2=Pulse, 3=Noise)",
            default=1.0,
            min_val=0.0,
            max_val=3.0,
        )
        self.add_param("vco1_pw", "VCO 1 Pulse Width", default=0.5, min_val=0.1, max_val=0.9)
        self.add_param("vco1_level", "VCO 1 Level", default=0.8, min_val=0.0, max_val=1.0)
        self.add_param(
            "vco2_scale",
            "VCO 2 Scale (0=16', 1=8', 2=4', 3=2')",
            default=1.0,
            min_val=0.0,
            max_val=3.0,
        )
        self.add_param(
            "vco2_wave",
            "VCO 2 Wave (0=Saw, 1=Square, 2=Narrow, 3=RingMod)",
            default=1.0,
            min_val=0.0,
            max_val=3.0,
        )
        self.add_param(
            "vco2_pitch", "VCO 2 Detune (octaves)", default=0.015, min_val=-1.0, max_val=1.0
        )
        self.add_param("vco2_level", "VCO 2 Level", default=0.8, min_val=0.0, max_val=1.0)
        self.add_param("hpf_cutoff", "HPF Cutoff", default=0.10, min_val=0.0, max_val=1.0)
        self.add_param("hpf_peak", "HPF Peak", default=0.20, min_val=0.0, max_val=1.0)
        self.add_param("lpf_cutoff", "LPF Cutoff", default=0.50, min_val=0.0, max_val=1.0)
        self.add_param("lpf_peak", "LPF Peak", default=0.55, min_val=0.0, max_val=1.0)
        self.add_param("lpf_eg2_depth", "LPF EG2 Depth", default=0.75, min_val=0.0, max_val=1.0)
        self.add_param("eg1_attack", "EG 1 Attack (s)", default=0.05, min_val=0.002, max_val=5.0)
        self.add_param("eg1_release", "EG 1 Release (s)", default=0.30, min_val=0.002, max_val=5.0)
        self.add_param("eg2_attack", "EG 2 Attack (s)", default=0.008, min_val=0.002, max_val=5.0)
        self.add_param("eg2_decay", "EG 2 Decay (s)", default=0.28, min_val=0.01, max_val=5.0)
        self.add_param("eg2_sustain", "EG 2 Sustain", default=0.50, min_val=0.0, max_val=1.0)
        self.add_param("eg2_release", "EG 2 Release (s)", default=0.25, min_val=0.01, max_val=5.0)
        self.add_param("mg_rate", "MG Frequency (Hz)", default=4.5, min_val=0.1, max_val=25.0)
        self.add_param("vca_init_gain", "VCA Initial Gain", default=0.0, min_val=0.0, max_val=1.0)
        self.add_param("volume", "Master Volume", default=1.0, min_val=0.0, max_val=1.5)

        for name in (
            "_tri1",
            "_saw1",
            "_pulse1",
            "_saw2",
            "_sq2",
            "_narrow2",
            "_mix",
            "_cv",
            "_hpf_cv",
            "_lpf_cv",
            "_vca_cv",
            "_tmp",
        ):
            self.add_scratch(name)
        self.hpf_audio_in.normal = self._vco_mix

    def _vco_mix(self):
        return self._mix

    def set_block_size(self, block_size):
        super().set_block_size(block_size)
        self.eg1.set_block_size(block_size)
        self.eg2.set_block_size(block_size)
        self.mg.set_block_size(block_size)
        self.sh = SampleAndHoldCore(block_size)
        self.vca.set_block_size(block_size)
        self.glide = GlideCore(self.sample_rate, block_size)

    def reset(self):
        for core in (
            self.osc1,
            self.osc2,
            self.hpf,
            self.lpf,
            self.eg1,
            self.eg2,
            self.mg,
            self.noise,
            self.sh,
            self.glide,
        ):
            core.reset()

    def process(self, block_size):
        p = self.params
        n = block_size
        w1 = int(p["vco1_wave"]) % 4
        w2 = int(p["vco2_wave"]) % 4

        self.noise.white(self.white_noise_out.buffer)
        if self.pink_noise_out.is_connected:
            self.noise.pink(self.white_noise_out.buffer, self.pink_noise_out.buffer)
        self.mg.render(p["mg_rate"], tri=self.mg_tri_out.buffer, square=self.mg_pulse_out.buffer)
        if self.sh_out.is_connected:
            self.sh.render(
                self.sh_in.get_buffer(), self.sh_clock_in.get_buffer(), self.sh_out.buffer, lag=0.05
            )

        gate = jack_signal(self.kybd_gate_in)
        self.eg1.set_times(p["eg1_attack"], 0.01, 1.0, p["eg1_release"])
        self.eg1.render(gate, self.eg1_out.buffer)
        self.eg2.set_times(p["eg2_attack"], p["eg2_decay"], p["eg2_sustain"], p["eg2_release"])
        self.eg2.render(gate, self.eg2_out.buffer)
        rev = self.eg2_rev_out.buffer
        rev[:] = 1.0
        rev -= self.eg2_out.buffer

        self.glide.render(jack_signal(self.kybd_cv_in), self._cv, p["glide"])
        cv = self._cv

        ring_needed = w2 == 3 or self.ring_mod_out.is_connected
        self.osc1.render(
            n,
            BASE_FREQ_C4 * (2.0 ** VCO1_OCTAVES[int(p["vco1_scale"]) % 4]),
            cv,
            pulse_width=p["vco1_pw"],
            saw=self._saw1 if w1 == 1 else None,
            pulse=self._pulse1 if (w1 == 2 or ring_needed) else None,
            tri=self._tri1 if w1 == 0 else None,
        )
        base2 = BASE_FREQ_C4 * (2.0 ** (VCO2_OCTAVES[int(p["vco2_scale"]) % 4] + p["vco2_pitch"]))
        self.osc2.render(
            n,
            base2,
            cv,
            pulse_width=0.15 if w2 == 2 else 0.5,
            saw=self._saw2 if w2 == 0 else None,
            pulse=(self._narrow2 if w2 == 2 else self._sq2)
            if (w2 in (1, 2) or ring_needed)
            else None,
        )
        if ring_needed:
            # the ring modulator is an XOR of the two pulse waves: sign(a) * sign(b)
            rm = self.ring_mod_out.buffer
            copy_into(rm, self._pulse1)
            mul(rm, self._sq2)
            rm *= 1e6
            from ..core.signal import np

            np.tanh(rm, out=rm)
            rm *= 0.707
        src1 = (self._tri1, self._saw1, self._pulse1, self.white_noise_out.buffer)[w1]
        src2 = (self._saw2, self._sq2, self._narrow2, self.ring_mod_out.buffer)[w2]
        copy_into(self.vco1_out.buffer, src1)
        copy_into(self.vco2_out.buffer, src2)
        mix = self._mix
        copy_into(mix, src1)
        mix *= p["vco1_level"] * 0.707
        add_scaled(mix, src2, p["vco2_level"] * 0.707, self._tmp)

        total = jack_signal(self.total_cutoff_cv_in)
        hpf_cv = self._hpf_cv
        hpf_cv[:] = 0.0
        if total is not None:
            add(hpf_cv, total)
        ext = jack_signal(self.hpf_cutoff_in)
        if ext is not None:
            add(hpf_cv, ext)
        self.hpf.render(
            n,
            self.hpf_audio_in.get_buffer(),
            self.hpf_out.buffer,
            cutoff_hz=knob_hz(p["hpf_cutoff"], 25.0, 5000.0),
            cutoff_cv=hpf_cv,
            peak=p["hpf_peak"],
        )
        lpf_cv = self._lpf_cv
        copy_into(lpf_cv, self.eg2_out.buffer)
        lpf_cv *= p["lpf_eg2_depth"]
        if total is not None:
            add(lpf_cv, total)
        ext = jack_signal(self.lpf_cutoff_in)
        if ext is not None:
            add(lpf_cv, ext)
        self.lpf.render(
            n,
            self.lpf_audio_in.get_buffer(),
            self.lpf_out.buffer,
            cutoff_hz=knob_hz(p["lpf_cutoff"], 40.0, 12000.0),
            cutoff_cv=lpf_cv,
            peak=p["lpf_peak"],
        )

        vca_cv = self._vca_cv
        copy_into(vca_cv, self.vca_cv_in.get_buffer())
        vca_cv *= p["volume"]
        vca_cv += p["vca_init_gain"]
        self.vca.render(
            self.vca_audio_in.get_buffer(), self.vca_out.buffer, vca_cv, exponential=True
        )

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

        # The Sallen-Key pair and the exponential VCA are newer nodes: an audiograph
        # without them would have to approximate both, so the voice stays on the rack.
        if not hasattr(ag, "TWOPOLE") or not hasattr(ag, "VCA_CURVE"):
            return False
        # Pink noise is Kellet's filter run in Python, and the graph has no node for
        # it: with a cable on the pink output, the voice stays on the rack.
        if self.pink_noise_out.cables:
            return False
        self._ag = ag
        self._ring_cabled = bool(self.ring_mod_out.cables)
        self._noise_cabled = bool(self.white_noise_out.cables)

        # The nodes go in the order process() renders, so a jack patched back into the
        # voice hears what the rack's would: this block's, or the previous block's.
        gate = f.input(self.kybd_gate_in)

        # white noise, in a group of its own that runs only while something hears it
        self._n_noise = f.add(
            ag.NOISE, (), f.output(self.white_noise_out), group=f.switch("noise", False)
        )
        f.set(self._n_noise, 0, 0.5 * UNIT)

        # the sample and hold, only with a cable on its output, as process() renders it
        self._sh_from_noise = False
        self._n_sh = None
        clock_from_mg = self.sh_out.cables and self.sh_clock_in.cable is None
        # the MG: its triangle and its square, each only when something hears it
        self._n_mg_tri = self._n_mg_sq = None
        if self.mg_tri_out.cables:
            self._n_mg_tri = f.add(ag.LFO, (), f.output(self.mg_tri_out))
            f.set(self._n_mg_tri, ag.LFO_SHAPE, ag.LFO_TRIANGLE)
            f.set(self._n_mg_tri, ag.LFO_AMPLITUDE, 0.5 * UNIT)
        if self.mg_pulse_out.cables or clock_from_mg:
            self._n_mg_sq = f.add(ag.LFO, (), f.output(self.mg_pulse_out))
            f.set(self._n_mg_sq, ag.LFO_SHAPE, ag.LFO_SQUARE)
            f.set(self._n_mg_sq, ag.LFO_AMPLITUDE, 0.5 * UNIT)
        if self.sh_out.cables:
            self._sh_from_noise = self.sh_in.cable is None
            sh_in = f.input(self.sh_in)
            sh_clock = f.input(self.sh_clock_in)
            self._n_sh = f.add(ag.SAMPLE_HOLD, (sh_in, sh_clock), f.output(self.sh_out))
            # SampleAndHoldCore's lag is this per-sample one-pole coefficient too
            f.set(self._n_sh, ag.SH_LAG, 0.05)

        # the envelopes: EG1 only feeds its jack; EG2 the LPF, the VCA and EG2 reverse
        self._n_eg1 = None
        if self.eg1_out.cables:
            self._n_eg1 = f.add(ag.ENV, (gate,), f.output(self.eg1_out))
            f.set(self._n_eg1, ag.ENV_DECAY, 0.01)
            f.set(self._n_eg1, ag.ENV_SUSTAIN, 1.0)
        b_eg2 = f.output(self.eg2_out)
        self._n_eg2 = f.add(ag.ENV, (gate,), b_eg2)
        # The voice mix parks by the rack's rule (30 ms under 2 mV), so a voice the VCA
        # keeps open without EG2 plays on as it does there. This envelope also keeps the
        # voice's group sounding in the mask `run()` returns, which nothing now reads.
        self._vca_cv_cabled = self.vca_cv_in.cable is not None
        b_hold = f.buffer()
        self._n_hold_gate = f.add(ag.CONST, (), b_hold)
        self._n_hold = f.add(ag.ENV, (b_hold,), f.buffer())
        f.set(self._n_hold, ag.ENV_ATTACK, 0.002)
        f.set(self._n_hold, ag.ENV_DECAY, 0.01)
        f.set(self._n_hold, ag.ENV_SUSTAIN, 1.0)
        f.set(self._n_hold, ag.ENV_RELEASE, 0.01)
        self._n_rev = None
        if self.eg2_rev_out.cables:
            # 1 - EG2
            self._n_rev = f.add(ag.MIX, (b_eg2,), f.output(self.eg2_rev_out))
            f.set(self._n_rev, 0, -1.0)
            f.set(self._n_rev, ag.MIX_OFFSET, UNIT)

        # glide: GlideCore's one-pole toward the key's first sample each block
        b_cv = self._b_cv = f.buffer()
        self._n_glide = f.add(ag.LAG, (f.input(self.kybd_cv_in), None, None), b_cv)
        f.set(self._n_glide, ag.LAG_SHAPE, ag.LAG_ONE_POLE)

        # The VCOs. The rack draws every wave a VCO plays from one node; here each wave
        # that can sound at once is a node of its own, all of a VCO's at one frequency
        # from phase zero, so they keep in step. The ring modulator's two pulses are
        # silent (waveform 0, their phase still running) while nothing hears the ring.
        b_osc1 = f.buffer()
        b_pul1 = f.buffer()
        b_osc2 = f.buffer()
        b_sq2 = f.buffer()
        self._n_osc1 = f.add(ag.OSC, (b_cv, None, None, None), b_osc1)
        self._n_pul1 = f.add(ag.OSC, (b_cv, None, None, None), b_pul1)
        self._n_osc2 = f.add(ag.OSC, (b_cv, None, None, None), b_osc2)
        self._n_sq2 = f.add(ag.OSC, (b_cv, None, None, None), b_sq2)
        for node in (self._n_osc1, self._n_pul1, self._n_osc2, self._n_sq2):
            f.set(node, ag.OSC_LEVEL, OSC_LEVEL)
            f.set(node, ag.OSC_PITCH_OCTAVES, PITCH_OCTAVES)
        f.set(self._n_sq2, ag.OSC_PULSE_WIDTH, 0.5)

        # The ring modulator: sign(pulse1) * sign(square2) * 0.707. The VCA's product is
        # pushed to the rail whenever it is not zero, then scaled to 0.707.
        b_rail = f.buffer()
        self._n_ring_vca = f.add(ag.VCA, (b_pul1, b_sq2, None), b_rail)
        f.set(self._n_ring_vca, ag.VCA_SELECT, 0.0)
        f.set(self._n_ring_vca, ag.VCA_CURVE, ag.VCA_LINEAR)
        f.set(self._n_ring_vca, ag.VCA_GAIN, 1e9)
        b_ring = f.output(self.ring_mod_out) if self._ring_cabled else f.buffer()
        self._n_ring = f.add(ag.MIX, (b_rail,), b_ring)

        # what each VCO's jack carries: its wave, or noise, or the ring
        b_noise = f.output(self.white_noise_out)
        self._n_vco1_out = self._n_vco2_out = None
        if self.vco1_out.cables:
            self._n_vco1_out = f.add(ag.MIX, (b_osc1, b_noise), f.output(self.vco1_out))
        if self.vco2_out.cables:
            self._n_vco2_out = f.add(ag.MIX, (b_osc2, b_ring), f.output(self.vco2_out))

        # the VCO mix, normalled into the HPF
        b_mix = f.buffer()
        self._n_mix = f.add(ag.MIX, (b_osc1, b_noise, b_osc2, b_ring), b_mix)

        # The filters. Their cutoff CVs are always a node's output, as process() always
        # hands its cores a CV block: the cutoff is then worked in float32, as there.
        total = f.input(self.total_cutoff_cv_in)
        b_hpf_cv = f.buffer()
        self._n_hpf_cv = f.add(ag.MIX, (total, f.input(self.hpf_cutoff_in)), b_hpf_cv)
        f.set(self._n_hpf_cv, 0, 1.0)
        f.set(self._n_hpf_cv, 1, 1.0)
        hpf_in = f.input(self.hpf_audio_in) if self.hpf_audio_in.cable is not None else b_mix
        self._n_hpf = f.add(ag.TWOPOLE, (hpf_in, b_hpf_cv), f.output(self.hpf_out))
        b_lpf_cv = f.buffer()
        self._n_lpf_cv = f.add(ag.MIX, (b_eg2, total, f.input(self.lpf_cutoff_in)), b_lpf_cv)
        f.set(self._n_lpf_cv, 1, 1.0)
        f.set(self._n_lpf_cv, 2, 1.0)
        lpf_in = f.input(self.lpf_audio_in)
        self._n_lpf = f.add(ag.TWOPOLE, (lpf_in, b_lpf_cv), f.output(self.lpf_out))
        for node, kind in (
            (self._n_hpf, ag.TWOPOLE_SK_HIGHPASS),
            (self._n_lpf, ag.TWOPOLE_SK_LOWPASS),
        ):
            f.set(node, ag.TWOPOLE_TYPE, kind)
            # the CV moves the cutoff by ten octaves a unit, as pitch_to_frequency does
            f.set(node, ag.TWOPOLE_DEPTH, 1.0)
            f.set(node, ag.TWOPOLE_DRIVE, 1.0)

        # the VCA: exponential, its CV the VCA CV jack (EG2) times the volume plus the
        # initial gain
        b_vcv = f.buffer()
        self._n_vcv = f.add(ag.MIX, (f.input(self.vca_cv_in),), b_vcv)
        self._n_vca = f.add(
            ag.VCA, (f.input(self.vca_audio_in), b_vcv, None), f.output(self.vca_out)
        )
        f.set(self._n_vca, ag.VCA_SELECT, 0.0)
        f.set(self._n_vca, ag.VCA_CURVE, ag.VCA_EXPONENTIAL)
        f.set(self._n_vca, ag.VCA_GAIN, self.graph_fold_gain)

        f.bind(("glide",), self._graph_glide)
        f.bind(("vco1_scale", "vco2_scale", "vco2_pitch"), self._graph_pitch)
        f.bind(("vco1_wave", "vco1_pw", "vco1_level", "vco2_wave", "vco2_level"), self._graph_waves)
        f.bind(("hpf_cutoff", "hpf_peak"), self._graph_hpf)
        f.bind(("lpf_cutoff", "lpf_peak"), self._graph_lpf)
        f.bind(("lpf_eg2_depth",), self._graph_lpf_cv)
        f.bind(("eg1_attack", "eg1_release"), self._graph_eg1)
        f.bind(("eg2_attack", "eg2_decay", "eg2_sustain", "eg2_release"), self._graph_eg2)
        f.bind(("mg_rate",), self._graph_mg)
        f.bind(("volume", "vca_init_gain"), self._graph_vca)
        f.on_reset(self._graph_reset)

    def _graph_glide(self):
        self._fragment.set(self._n_glide, self._ag.LAG_TIME, self.params["glide"])

    def _graph_pitch(self):
        p = self.params
        f = self._fragment
        ag = self._ag
        hz1 = BASE_FREQ_C4 * (2.0 ** VCO1_OCTAVES[int(p["vco1_scale"]) % 4])
        hz2 = BASE_FREQ_C4 * (2.0 ** (VCO2_OCTAVES[int(p["vco2_scale"]) % 4] + p["vco2_pitch"]))
        f.set(self._n_osc1, ag.OSC_FREQUENCY, hz1)
        f.set(self._n_pul1, ag.OSC_FREQUENCY, hz1)
        f.set(self._n_osc2, ag.OSC_FREQUENCY, hz2)
        f.set(self._n_sq2, ag.OSC_FREQUENCY, hz2)

    def _graph_waves(self):
        p = self.params
        f = self._fragment
        ag = self._ag
        w1 = int(p["vco1_wave"]) % 4
        w2 = int(p["vco2_wave"]) % 4
        ring = w2 == 3 or self._ring_cabled
        # VCO1: triangle, saw, pulse, or silent while it plays noise
        f.set(self._n_osc1, ag.OSC_WAVEFORM, (4, 1, 2, 0)[w1])
        f.set(self._n_osc1, ag.OSC_PULSE_WIDTH, p["vco1_pw"])
        f.set(self._n_pul1, ag.OSC_WAVEFORM, 2 if ring else 0)
        f.set(self._n_pul1, ag.OSC_PULSE_WIDTH, p["vco1_pw"])
        # VCO2: saw, square, the narrow pulse, or silent while it plays the ring
        f.set(self._n_osc2, ag.OSC_WAVEFORM, (1, 2, 2, 0)[w2])
        f.set(self._n_osc2, ag.OSC_PULSE_WIDTH, 0.15 if w2 == 2 else 0.5)
        f.set(self._n_sq2, ag.OSC_WAVEFORM, 2 if ring else 0)
        # The rack's ring reads VCO2's square, which it does not draw while VCO2 plays
        # the narrow pulse: from a fresh voice that is silence, and so it is here.
        f.set(self._n_ring, 0, 0.0 if w2 == 2 else 0.707 * UNIT / 32767.0)
        f.enable("noise", w1 == 3 or self._noise_cabled or self._sh_from_noise)
        noise = w1 == 3
        ring_wave = w2 == 3
        if self._n_vco1_out is not None:
            f.set(self._n_vco1_out, 0, 0.0 if noise else 1.0)
            f.set(self._n_vco1_out, 1, 1.0 if noise else 0.0)
        if self._n_vco2_out is not None:
            f.set(self._n_vco2_out, 0, 0.0 if ring_wave else 1.0)
            f.set(self._n_vco2_out, 1, 1.0 if ring_wave else 0.0)
        g1 = p["vco1_level"] * 0.707
        g2 = p["vco2_level"] * 0.707
        f.set(self._n_mix, 0, 0.0 if noise else g1)
        f.set(self._n_mix, 1, g1 if noise else 0.0)
        f.set(self._n_mix, 2, 0.0 if ring_wave else g2)
        f.set(self._n_mix, 3, g2 if ring_wave else 0.0)

    def _graph_hpf(self):
        p = self.params
        f = self._fragment
        ag = self._ag
        f.set(self._n_hpf, ag.TWOPOLE_CUTOFF_HZ, knob_hz(p["hpf_cutoff"], 25.0, 5000.0))
        f.set(self._n_hpf, ag.TWOPOLE_RESONANCE, p["hpf_peak"])

    def _graph_lpf(self):
        p = self.params
        f = self._fragment
        ag = self._ag
        f.set(self._n_lpf, ag.TWOPOLE_CUTOFF_HZ, knob_hz(p["lpf_cutoff"], 40.0, 12000.0))
        f.set(self._n_lpf, ag.TWOPOLE_RESONANCE, p["lpf_peak"])

    def _graph_lpf_cv(self):
        self._fragment.set(self._n_lpf_cv, 0, self.params["lpf_eg2_depth"])

    def _graph_eg1(self):
        if self._n_eg1 is None:
            return
        p = self.params
        f = self._fragment
        ag = self._ag
        f.set(self._n_eg1, ag.ENV_ATTACK, p["eg1_attack"])
        f.set(self._n_eg1, ag.ENV_RELEASE, p["eg1_release"])

    def _graph_eg2(self):
        p = self.params
        f = self._fragment
        ag = self._ag
        f.set(self._n_eg2, ag.ENV_ATTACK, p["eg2_attack"])
        f.set(self._n_eg2, ag.ENV_DECAY, p["eg2_decay"])
        f.set(self._n_eg2, ag.ENV_SUSTAIN, p["eg2_sustain"])
        f.set(self._n_eg2, ag.ENV_RELEASE, p["eg2_release"])

    def _graph_mg(self):
        for node in (self._n_mg_tri, self._n_mg_sq):
            if node is not None:
                self._fragment.set(node, self._ag.LFO_RATE, self.params["mg_rate"])

    def _graph_vca(self):
        p = self.params
        f = self._fragment
        f.set(self._n_vcv, 0, p["volume"])
        f.set(self._n_vcv, self._ag.MIX_OFFSET, p["vca_init_gain"] * UNIT)
        held = p["vca_init_gain"] > 0.0 or self._vca_cv_cabled
        f.set(self._n_hold_gate, 0, UNIT if held else 0.0)

    def _graph_reset(self):
        # as reset(): the VCOs' phases, the filters, the envelopes, the MG, the noise,
        # the sample and hold and the glide
        f = self._fragment
        for node in (
            self._n_osc1,
            self._n_pul1,
            self._n_osc2,
            self._n_sq2,
            self._n_hpf,
            self._n_lpf,
            self._n_eg1,
            self._n_eg2,
            self._n_hold,
            self._n_mg_tri,
            self._n_mg_sq,
            self._n_noise,
            self._n_sh,
            self._n_glide,
        ):
            if node is not None:
                f.reset(node)
