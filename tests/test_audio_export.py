# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Unit tests for WavWriter and audio export pipeline."""

import os
import struct
import tempfile
import wave

from audioinstruments._rack.core.rack import Rack
from audioinstruments._rack.modules.midi_cv import MidiCVModule
from audioinstruments._rack.modules.patch2600 import Patch2600

from examples.play_audio import WavWriter, render_rack_to_wav


def test_wav_writer_header_compliance():
    """Verify WavWriter generates a 100% compliant 44-byte RIFF/WAVE header."""
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        sample_rate = 48000
        channels = 2
        bits = 16
        writer = WavWriter(tmp_path, sample_rate=sample_rate, channels=channels, bits=bits)

        # Write 4 blocks of 64 stereo frames (256 frames total = 1024 bytes)
        raw_block = bytearray(64 * channels * 2)
        # Fill with a dummy ramp
        for i in range(len(raw_block)):
            raw_block[i] = i & 0xFF

        for _ in range(4):
            writer.write(raw_block)
        writer.close()

        # Check total file size: 44 bytes header + 1024 bytes data = 1068 bytes
        file_size = os.stat(tmp_path)[6]
        assert file_size == 1068

        # Validate with standard library wave module
        with wave.open(tmp_path, "rb") as wf:
            assert wf.getnchannels() == 2
            assert wf.getsampwidth() == 2
            assert wf.getframerate() == 48000
            assert wf.getnframes() == 256
            read_bytes = wf.readframes(256)
            assert len(read_bytes) == 1024

        # Verify exact RIFF header bytes
        with open(tmp_path, "rb") as f:
            header = f.read(44)
            (
                riff,
                riff_sz,
                wave_tag,
                fmt_tag,
                fmt_sz,
                pcm_tag,
                ch,
                rate,
                byte_rate,
                align,
                b_depth,
                data_tag,
                data_sz,
            ) = struct.unpack("<4sI4s4sIHHIIHH4sI", header)
            assert riff == b"RIFF"
            assert wave_tag == b"WAVE"
            assert fmt_tag == b"fmt "
            assert fmt_sz == 16
            assert pcm_tag == 1  # Uncompressed PCM
            assert ch == 2
            assert rate == 48000
            assert align == 4  # 2 channels * 2 bytes
            assert byte_rate == 48000 * 4
            assert b_depth == 16
            assert data_tag == b"data"
            assert data_sz == 1024
            assert riff_sz == 36 + 1024
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


def test_render_rack_to_wav_offline():
    """Verify render_rack_to_wav renders a rack to a playable WAV file without audio hardware."""
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        rack = Rack(sample_rate=48000, block_size=64)
        midi = rack.add_module(MidiCVModule("midi"))
        patch2600 = rack.add_module(Patch2600("patch2600"))

        rack.connect(midi.pitch_out, patch2600.kybd_cv_in)
        rack.connect(midi.gate_out, patch2600.kybd_gate_in)
        rack.connect(patch2600.master_l_out, rack.master_left_in)
        rack.connect(patch2600.master_r_out, rack.master_right_in)

        patch2600.set_param("vcf_cutoff", 0.40)
        patch2600.set_param("vcf_res", 0.60)
        patch2600.set_param("adsr_attack", 0.005)
        patch2600.set_param("adsr_decay", 0.10)
        patch2600.set_param("adsr_sustain", 0.30)
        patch2600.set_param("adsr_release", 0.10)

        events = [
            (0, lambda: midi.note_on(36, 100)),
            (50, lambda: midi.note_off(36)),
        ]

        render_rack_to_wav(rack, tmp_path, events, total_seconds=0.15)

        assert os.path.exists(tmp_path)
        assert os.stat(tmp_path)[6] > 1000

        with wave.open(tmp_path, "rb") as wf:
            assert wf.getnchannels() == 2
            assert wf.getframerate() == 48000
            nframes = wf.getnframes()
            raw_data = wf.readframes(nframes)
            # Verify data is non-zero (synthesizer generated sound)
            samples = struct.unpack(f"<{nframes * 2}h", raw_data)
            peak = max(abs(s) for s in samples)
            assert peak > 500, f"Expected audible sound, got peak={peak}"
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
