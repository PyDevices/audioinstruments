#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Example: Patch2600, the semi-modular voice inspired by the ARP 2600, in the rack.

Demonstrates:
1. Playing Patch2600 out of the box with pre-normalled default routing (no cables needed).
2. Severing internal normals by inserting patch cables (e.g. Ring Mod & Noise cross-modulation).
3. Verifying stereo output with simulated spring reverb.
"""

import math

from audioinstruments._rack import MidiCVModule, Patch2600, Rack


def main():
    print("=== audioinstruments: Patch2600 semi-modular synthesizer ===")
    rack = Rack(sample_rate=48000, block_size=64)

    # Install MIDI-to-CV and Patch2600
    midi_cv = rack.add_module(MidiCVModule("midi_cv"))
    patch2600 = rack.add_module(Patch2600("patch2600"))

    # Connect master keyboard CV & Gate to Patch2600's primary inputs
    rack.connect(midi_cv.pitch_out, patch2600.kybd_cv_in, color="#9b59b6")
    rack.connect(midi_cv.gate_out, patch2600.kybd_gate_in, color="#3498db")

    # Connect Patch2600's master stereo outs to Rack Master Outs
    rack.connect(patch2600.master_l_out, rack.master_left_in, color="#e74c3c")
    rack.connect(patch2600.master_r_out, rack.master_right_in, color="#e74c3c")

    print("\n1. Testing Default Pre-Normalled Playability (0 internal patch cables)...")
    # Play a bass note (C2 = Note 36)
    midi_cv.note_on(36, 110)
    for _ in range(16):
        rack.step()

    rms_norm_l = math.sqrt(sum(x * x for x in rack.output_buffer_left) / 64)
    rms_norm_r = math.sqrt(sum(x * x for x in rack.output_buffer_right) / 64)
    print(
        "Note C2 (36): Left RMS = %.4f, Right RMS = %.4f (Spring Reverb active)"
        % (rms_norm_l, rms_norm_r)
    )
    midi_cv.note_off(36)

    print("\n2. Inserting Patch Cables: Cross-Modulation and Filter Overdrive...")
    # Patch Ring Modulator output into VCF Audio In 1 (overrides normalled VCO 1 Pulse)
    rack.connect(patch2600.ring_mod_out, patch2600.vcf_in1, color="#f1c40f")
    # Patch S&H Out into VCO 2 FM 2
    rack.connect(patch2600.sh_out, patch2600.vco2_fm2_in, color="#2ecc71")
    patch2600.set_param("vco2_fm2_lvl", 0.5)

    # Play lead note (A4 = Note 69)
    midi_cv.note_on(69, 115)
    for _ in range(16):
        rack.step()

    rms_mod_l = math.sqrt(sum(x * x for x in rack.output_buffer_left) / 64)
    print("Note A4 (69) with Ring Mod & S&H: Left RMS = %.4f" % rms_mod_l)
    midi_cv.note_off(69)

    print("\n=== Patch2600 demo completed successfully ===")


if __name__ == "__main__":
    main()
