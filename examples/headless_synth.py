#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Example: Headless Modular100 modular synthesizer in vrack.

Demonstrates:
- Creating a virtual Eurorack frame (Rack).
- Installing the MIDI-to-CV interface (profiled for Donner DMK-25 / KeyStep Pro).
- Installing the Modular100 modules (dual VCO, dual VCF, dual VCA, envelopes and LFO, utility).
- Patching virtual cables between modules.
- Playing synthetic notes and inspecting synthesized audio blocks.
"""

import math

from vrack import Rack
from vrack.modules import (
    MidiCVModule,
    Modular100EnvLFO,
    Modular100Utility,
    Modular100VCA,
    Modular100VCF,
    Modular100VCO,
)


def main():
    print("=== vrack: Virtual Eurorack Synthesizer ===")
    rack = Rack(sample_rate=48000, block_size=64)

    # 1. Install Modules into the Rack
    midi_cv = rack.add_module(MidiCVModule("midi_cv"))
    vco = rack.add_module(Modular100VCO("vco"))
    vcf = rack.add_module(Modular100VCF("vcf"))
    vca = rack.add_module(Modular100VCA("vca"))
    env_lfo = rack.add_module(Modular100EnvLFO("env"))
    rack.add_module(Modular100Utility("util"))

    print("Installed modules:", [m.id for m in rack.modules])

    # 2. Patch Audio Path
    # VCO1 Saw + VCO2 Pulse -> VCF1 In 1 & 2
    rack.connect(vco.vco1_saw_out, vcf.vcf1_audio1, color="#e74c3c")
    rack.connect(vco.vco2_pulse_out, vcf.vcf1_audio2, color="#e67e22")
    vcf.set_param("vcf1_in1_level", 0.7)
    vcf.set_param("vcf1_in2_level", 0.7)

    # VCF1 Out -> VCA1 In 1
    rack.connect(vcf.vcf1_out, vca.vca1_audio1, color="#f1c40f")
    vca.set_param("vca1_in1_level", 1.0)

    # VCA1 Out -> Master Left & Right
    rack.connect(vca.vca1_out, rack.master_left_in, color="#2ecc71")

    # 3. Patch Control Voltages & Envelopes
    # 1V/Oct Pitch -> VCO 1 & 2 Pitch Ins
    rack.connect(midi_cv.pitch_out, vco.vco1_pitch_in, color="#9b59b6")
    rack.connect(midi_cv.pitch_out, vco.vco2_pitch_in, color="#9b59b6")

    # Gate -> Envelope 1 Gate
    rack.connect(midi_cv.gate_out, env_lfo.env1_gate_in, color="#3498db")

    # Envelope 1 -> VCF1 Filter Cutoff Mod 2
    rack.connect(env_lfo.env1_out, vcf.vcf1_mod2, color="#e74c3c")
    vcf.set_param("vcf1_mod2_level", 0.75)

    # Envelope 2 -> VCA1 Amplitude Mod 1
    rack.connect(env_lfo.env2_out, vca.vca1_mod1, color="#f39c12")
    vca.set_param("vca1_mod1_level", 1.0)

    # LFO Triangle -> VCO1 Pitch Mod 2 (Vibrato)
    rack.connect(env_lfo.lfo_tri_out, vco.vco1_mod2_in, color="#1abc9c")
    vco.set_param("vco1_mod2_level", 0.04)

    print("Connected %d patch cables." % len(rack.cables))

    # 4. Play an Arpeggio sequence
    melody = [(60, "C4"), (64, "E4"), (67, "G4"), (71, "B4"), (72, "C5")]

    print("\nSynthesizing arpeggio sequence...")
    for note, name in melody:
        midi_cv.note_on(note, velocity=100)
        # Render ~85ms of audio per note (64 blocks * 64 samples @ 48kHz)
        for _ in range(64):
            rack.step()

        rms = math.sqrt(sum(x * x for x in rack.output_buffer_left) / 64)
        print("Note %s (%d): rendered block RMS level = %.4f" % (name, note, rms))
        midi_cv.note_off(note)

    # 5. Serialize patch
    saved_state = rack.save_patch("Modular100 Lead")
    print("\nPatch state serialized successfully (%d bytes in dict)" % len(str(saved_state)))
    print("=== vrack demo completed successfully ===")


if __name__ == "__main__":
    main()
