# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""ParaphonicSynth, a paraphonic voice inspired by the Behringer Neutron: two wave-blending VCOs, a multimode filter,
overdrive, a bucket-brigade delay, two envelopes, an LFO and utilities."""

from ..core.jack import SignalType
from ..core.module import Module
from ..core.signal import BASE_FREQ_C4, copy_into, crossfade_into, pitch_to_frequency
from ..dsp.amplifier import AmplifierCore
from ..dsp.biquad import MultimodeFilter, resonance_to_q
from ..dsp.delay import BBDDelayCore
from ..dsp.envelope import EnvelopeCore
from ..dsp.lfo import LFOCore
from ..dsp.noise import NoiseGenerator
from ..dsp.oscillator import WaveBlenderCore
from ..dsp.saturation import OverdriveCore
from ..dsp.utility import GlideCore, SampleAndHoldCore, invert_into
from ._util import jack_signal, knob_hz

VCF_MODES = (0.0, None, 1.0)  # LP morph, BP switch, HP morph


class ParaphonicSynth(Module):
    NAME = "ParaphonicSynth"
    DISPLAY_NAME = "ParaphonicSynth"
    HP = 80

    MACRO_LABELS = (
        "vco1_shape",
        "vco2_shape",
        "vco_mix",
        "glide",
        "vcf_cutoff",
        "vcf_res",
        "vcf_mode",
        "vcf_mod_depth",
        "od_drive",
        "od_tone",
        "delay_time",
        "delay_repeats",
        "delay_mix",
        "env1_attack",
        "env1_decay",
        "env1_sustain",
        "env1_release",
        "lfo_rate",
        "lfo_shape",
    )

    def _build(self):
        sr, n = self.sample_rate, self.block_size
        self.vco1_core = WaveBlenderCore(sr)
        self.vco2_core = WaveBlenderCore(sr)
        self.vcf_core = MultimodeFilter(n, sr)
        self.overdrive_core = OverdriveCore(sr, n)
        self.delay_core = BBDDelayCore(sr, n, max_delay_sec=0.7)
        self.vca_core = AmplifierCore(n)
        self.env1_core = EnvelopeCore(sr, n)
        self.env2_core = EnvelopeCore(sr, n)
        self.lfo_core = LFOCore(sr, n)
        self.noise_core = NoiseGenerator()
        self.sh_core = SampleAndHoldCore(n)
        self.slew_core = GlideCore(sr, n)

        cv, gate, audio, trig, clock = (
            SignalType.CV,
            SignalType.GATE,
            SignalType.AUDIO,
            SignalType.TRIGGER,
            SignalType.CLOCK,
        )
        self.kybd_cv_in = self.add_input("kybd_cv", "Keyboard 1V/Oct CV", cv)
        self.kybd_gate_in = self.add_input("kybd_gate", "Keyboard Gate", gate)

        self.env1_out = self.add_output("env1_out", "ENV 1 Out", cv)
        self.env2_out = self.add_output("env2_out", "ENV 2 Out", cv)
        self.lfo_out = self.add_output("lfo_out", "LFO Out", cv)
        self.lfo_square_out = self.add_output("lfo_sq", "LFO Square Out", clock)
        self.noise_out = self.add_output("noise_out", "Pink Noise Out", audio)
        self.sh_out = self.add_output("sh_out", "S&H Out", cv)
        self.vco1_out = self.add_output("vco1_out", "VCO 1 Out", audio)
        self.vco2_out = self.add_output("vco2_out", "VCO 2 Out", audio)
        self.vco_mix_out = self.add_output("vco_mix", "VCO Mix Out", audio)
        self.vcf_out = self.add_output("vcf_out", "VCF Out", audio)
        self.overdrive_out = self.add_output("od_out", "Overdrive Out", audio)
        self.delay_out = self.add_output("delay_out", "Delay Out", audio)
        self.vca_out = self.add_output("vca_out", "VCA Out", audio)
        self.master_out = self.add_output("master_out", "Master Audio Out", audio)
        self.inv_out = self.add_output("inv_out", "Inverter Out", cv)
        self.slew_out = self.add_output("slew_out", "Slew Out", cv)
        self.att1_out = self.add_output("att1_out", "Attenuator 1 Out", cv)
        self.att2_out = self.add_output("att2_out", "Attenuator 2 Out", cv)

        self.env1_gate_in = self.add_input(
            "env1_gate", "ENV 1 Gate In", gate, normal=self.kybd_gate_in
        )
        self.env2_gate_in = self.add_input(
            "env2_gate", "ENV 2 Gate In", gate, normal=self.kybd_gate_in
        )
        self.vco1_pitch_in = self.add_input(
            "vco1_pitch", "VCO 1 1V/Oct", cv, normal=self.kybd_cv_in
        )
        self.vco1_shape_in = self.add_input("vco1_shape", "VCO 1 Shape CV", cv)
        self.vco1_sync_in = self.add_input("vco1_sync", "VCO 1 Sync In", trig)
        self.vco2_pitch_in = self.add_input(
            "vco2_pitch", "VCO 2 1V/Oct", cv, normal=self.kybd_cv_in
        )
        self.vco2_shape_in = self.add_input("vco2_shape", "VCO 2 Shape CV", cv)
        self.vco2_sync_in = self.add_input("vco2_sync", "VCO 2 Sync In", trig, normal=self.vco1_out)
        self.vcf_in = self.add_input("vcf_in", "VCF Audio In", audio, normal=self.vco_mix_out)
        self.vcf_mod_in = self.add_input("vcf_mod", "VCF Mod In", cv, normal=self.env2_out)
        self.od_in = self.add_input("od_in", "Overdrive Audio In", audio, normal=self.vcf_out)
        self.delay_in = self.add_input(
            "delay_in", "Delay Audio In", audio, normal=self.overdrive_out
        )
        self.vca_in = self.add_input("vca_in", "VCA Audio In", audio, normal=self.delay_out)
        self.vca_cv_in = self.add_input("vca_cv", "VCA CV In", cv, normal=self.env1_out)
        self.sh_in = self.add_input("sh_in", "S&H In", cv, normal=self.noise_out)
        self.sh_clock_in = self.add_input(
            "sh_clk", "S&H Clock In", clock, normal=self.lfo_square_out
        )
        self.inv_in = self.add_input("inv_in", "Invert In", cv)
        self.slew_in = self.add_input("slew_in", "Slew In", cv, normal=self.kybd_cv_in)
        self.att1_in = self.add_input("att1_in", "Attenuator 1 In", cv)
        self.att2_in = self.add_input("att2_in", "Attenuator 2 In", cv)

        self.add_param(
            "vco1_shape",
            "VCO 1 Shape (0=Tone, .25=Saw, .5=Sq, .75=Tri, 1=Sin)",
            default=0.25,
            min_val=0.0,
            max_val=1.0,
        )
        self.add_param("vco2_shape", "VCO 2 Shape", default=0.50, min_val=0.0, max_val=1.0)
        self.add_param(
            "vco1_range", "VCO 1 Range (0=32', 1=16', 2=8')", default=1.0, min_val=0.0, max_val=2.0
        )
        self.add_param("vco2_range", "VCO 2 Range", default=1.0, min_val=0.0, max_val=2.0)
        self.add_param("vco1_tune", "VCO 1 Tune (octaves)", default=0.0, min_val=-1.0, max_val=1.0)
        self.add_param("vco2_tune", "VCO 2 Tune (octaves)", default=0.0, min_val=-1.0, max_val=1.0)
        self.add_param("vco_mix", "VCO 1/2 Mix", default=0.5, min_val=0.0, max_val=1.0)
        self.add_param("vco_sync", "Oscillator Sync Switch", default=0.0, min_val=0.0, max_val=1.0)
        self.add_param(
            "paraphonic",
            "Paraphonic Mode Switch (not modelled)",
            default=0.0,
            min_val=0.0,
            max_val=1.0,
        )
        self.add_param("glide", "Portamento (s)", default=0.0, min_val=0.0, max_val=1.0)
        self.add_param("vcf_cutoff", "VCF Cutoff", default=0.65, min_val=0.0, max_val=1.0)
        self.add_param("vcf_res", "VCF Resonance", default=0.25, min_val=0.0, max_val=1.0)
        self.add_param(
            "vcf_mode", "VCF Mode (0=LP, 1=BP, 2=HP)", default=0.0, min_val=0.0, max_val=2.0
        )
        self.add_param(
            "vcf_key_track",
            "VCF Key Tracking (not modelled)",
            default=1.0,
            min_val=0.0,
            max_val=1.0,
        )
        self.add_param(
            "vcf_mod_depth", "VCF Modulation Depth", default=0.75, min_val=0.0, max_val=1.0
        )
        self.add_param("od_drive", "Overdrive Drive", default=0.35, min_val=0.0, max_val=1.0)
        self.add_param("od_tone", "Overdrive Tone", default=0.5, min_val=0.0, max_val=1.0)
        self.add_param("od_level", "Overdrive Level", default=1.0, min_val=0.0, max_val=1.0)
        self.add_param("delay_time", "Delay Time (s)", default=0.22, min_val=0.02, max_val=0.65)
        self.add_param("delay_repeats", "Delay Repeats", default=0.40, min_val=0.0, max_val=1.05)
        self.add_param("delay_mix", "Delay Mix", default=0.30, min_val=0.0, max_val=1.0)
        for e, d in (("env1", (0.01, 0.20, 0.75, 0.25)), ("env2", (0.01, 0.25, 0.40, 0.30))):
            self.add_param(e + "_attack", "Attack (s)", default=d[0], min_val=0.001, max_val=3.0)
            self.add_param(e + "_decay", "Decay (s)", default=d[1], min_val=0.01, max_val=3.0)
            self.add_param(e + "_sustain", "Sustain", default=d[2], min_val=0.0, max_val=1.0)
            self.add_param(e + "_release", "Release (s)", default=d[3], min_val=0.01, max_val=3.0)
        self.add_param("lfo_rate", "LFO Rate", default=0.35, min_val=0.0, max_val=1.0)
        self.add_param(
            "lfo_shape",
            "LFO Shape (0=Sine, 1=Tri, 2=Saw, 3=Sq)",
            default=1.0,
            min_val=0.0,
            max_val=3.0,
        )
        self.add_param("slew_rate", "Slew Time (s)", default=0.0, min_val=0.0, max_val=1.0)
        self.add_param("att1_lvl", "Attenuator 1", default=1.0, min_val=0.0, max_val=1.0)
        self.add_param("att2_lvl", "Attenuator 2", default=1.0, min_val=0.0, max_val=1.0)

        for name in ("_white", "_tmp"):
            self.add_scratch(name)

    def set_block_size(self, block_size):
        super().set_block_size(block_size)
        sr = self.sample_rate
        self.vcf_core = MultimodeFilter(block_size, sr)
        self.overdrive_core = OverdriveCore(sr, block_size)
        self.delay_core = BBDDelayCore(sr, block_size, max_delay_sec=0.7)
        self.vca_core.set_block_size(block_size)
        self.env1_core.set_block_size(block_size)
        self.env2_core.set_block_size(block_size)
        self.lfo_core.set_block_size(block_size)
        self.sh_core = SampleAndHoldCore(block_size)
        self.slew_core = GlideCore(sr, block_size)

    def reset(self):
        for core in (
            self.vco1_core,
            self.vco2_core,
            self.vcf_core,
            self.overdrive_core,
            self.delay_core,
            self.env1_core,
            self.env2_core,
            self.lfo_core,
            self.noise_core,
            self.sh_core,
            self.slew_core,
        ):
            core.reset()

    def process(self, block_size):
        p = self.params
        n = block_size

        self.noise_core.white(self._white)
        self.noise_core.pink(self._white, self.noise_out.buffer)

        shape = int(p["lfo_shape"]) % 4
        lfo = self.lfo_out.buffer
        self.lfo_core.render(
            knob_hz(p["lfo_rate"], 0.1, 50.0),
            sine=lfo if shape == 0 else None,
            tri=lfo if shape == 1 else None,
            saw=lfo if shape == 2 else None,
            square=self.lfo_square_out.buffer,
        )
        if shape == 3:
            copy_into(lfo, self.lfo_square_out.buffer)
        self.sh_core.render(
            self.sh_in.get_buffer(), self.sh_clock_in.get_buffer(), self.sh_out.buffer
        )

        self.env1_core.set_times(
            p["env1_attack"], p["env1_decay"], p["env1_sustain"], p["env1_release"]
        )
        self.env1_core.render(self.env1_gate_in.get_buffer(), self.env1_out.buffer)
        self.env2_core.set_times(
            p["env2_attack"], p["env2_decay"], p["env2_sustain"], p["env2_release"]
        )
        self.env2_core.render(self.env2_gate_in.get_buffer(), self.env2_out.buffer)

        base1 = BASE_FREQ_C4 * (2.0 ** (int(p["vco1_range"]) - 1 + p["vco1_tune"]))
        base2 = BASE_FREQ_C4 * (2.0 ** (int(p["vco2_range"]) - 1 + p["vco2_tune"]))
        self.vco1_core.render(
            n,
            base1,
            self.vco1_pitch_in.get_buffer(),
            self.vco1_out.buffer,
            shape=p["vco1_shape"],
            shape_cv=jack_signal(self.vco1_shape_in),
            sync=jack_signal(self.vco1_sync_in),
        )
        self.vco2_core.render(
            n,
            base2,
            self.vco2_pitch_in.get_buffer(),
            self.vco2_out.buffer,
            shape=p["vco2_shape"],
            shape_cv=jack_signal(self.vco2_shape_in),
            sync=self.vco2_sync_in.get_buffer() if p["vco_sync"] >= 0.5 else None,
        )
        crossfade_into(
            self.vco_mix_out.buffer,
            self.vco1_out.buffer,
            self.vco2_out.buffer,
            p["vco_mix"],
            self._tmp,
        )

        # VCF: block-rate cutoff from the knob plus the modulation input (1 V/oct, attenuated)
        mod0 = float(self.vcf_mod_in.get_buffer()[0]) * p["vcf_mod_depth"]
        self.vcf_core.set(
            pitch_to_frequency(mod0, base_freq=knob_hz(p["vcf_cutoff"], 20.0, 20000.0)),
            resonance_to_q(p["vcf_res"]),
        )
        mode = int(p["vcf_mode"]) % 3
        self.vcf_core.process(
            self.vcf_in.get_buffer(),
            out=self.vcf_out.buffer,
            morph=VCF_MODES[mode] or 0.0,
            bandpass=(mode == 1),
        )

        self.overdrive_core.render(
            self.od_in.get_buffer(),
            self.overdrive_out.buffer,
            p["od_drive"],
            p["od_tone"],
            p["od_level"],
        )
        self.delay_core.render(
            self.delay_in.get_buffer(),
            self.delay_out.buffer,
            p["delay_time"],
            p["delay_repeats"],
            p["delay_mix"],
        )
        self.vca_core.render(
            self.vca_in.get_buffer(),
            self.vca_out.buffer,
            self.vca_cv_in.get_buffer(),
            exponential=True,
        )
        copy_into(self.master_out.buffer, self.vca_out.buffer)

        if self.inv_out.is_connected:
            invert_into(self.inv_out.buffer, jack_signal(self.inv_in))
        if self.slew_out.is_connected:
            self.slew_core.render(self.slew_in.get_buffer(), self.slew_out.buffer, p["slew_rate"])
        if self.att1_out.is_connected:
            copy_into(self.att1_out.buffer, self.att1_in.get_buffer())
            self.att1_out.buffer *= p["att1_lvl"]
        if self.att2_out.is_connected:
            copy_into(self.att2_out.buffer, self.att2_in.get_buffer())
            self.att2_out.buffer *= p["att2_lvl"]
