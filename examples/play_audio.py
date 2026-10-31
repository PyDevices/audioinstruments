#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Twenty short movements, one per instrument, rendered to WAV or played live.

    python examples/play_audio.py --no-live --wav        # all twenty into wav_exports/
    python examples/play_audio.py --no-live --wav 7      # one movement
    python examples/play_audio.py                        # live via board_config.pcm_out

Each ``movement_NN()`` builds a rack, patches it and returns it with its
timed events, so the same patches drive the renders, the benchmark in
tests/mpy/bench.py and anything else that wants a ready-made rack. Runs on
CPython and MicroPython.
"""

import gc
import os
import struct
import sys
import time

if "lib" not in sys.path:
    sys.path.insert(0, "lib")

try:
    from time import sleep_ms, ticks_diff, ticks_ms
except ImportError:  # CPython

    def ticks_ms():
        return int(time.monotonic() * 1000.0)

    def ticks_diff(a, b):
        return a - b

    def sleep_ms(ms):
        time.sleep(ms / 1000.0)


from vrack import (  # noqa: E402
    Acid303,
    DrumSynth,
    Duo20,
    FunctionGenerator,
    GranularProcessor,
    HybridMono,
    MacroOscillator,
    MidiCVModule,
    ModalResonator,
    Modular55Envelope,
    Modular55LowPass,
    Modular55VCA,
    Modular55VCO,
    Modular100EnvLFO,
    Modular100VCA,
    Modular100VCF,
    Modular100VCO,
    MonoOne,
    ParaphonicSynth,
    Patch2600,
    PinMatrix3,
    PolyrhythmSynth,
    Rack,
    RandomSequencer,
    Semi32,
    StateVariableMono,
    WestCoast0,
    WestCoastSynth,
)
from vrack.core.signal import INT16_DTYPE, np  # noqa: E402

SAMPLE_RATE = 48000
BLOCK_SIZE = 64
BLOCKS_PER_SECOND = SAMPLE_RATE / BLOCK_SIZE


# -- output ---------------------------------------------------------------------


class WavWriter:
    """A small RIFF/WAVE writer; MicroPython has no wave module."""

    def __init__(self, filename, sample_rate=SAMPLE_RATE, channels=2, bits=16):
        self.sample_rate = sample_rate
        self.channels = channels
        self.bits = bits
        self.f = open(filename, "wb")  # noqa: SIM115 - closed by close()
        self.f.write(b"\x00" * 44)
        self.bytes_written = 0

    def write(self, data):
        self.f.write(data)
        self.bytes_written += len(data)

    def close(self):
        data_size = self.bytes_written
        byte_rate = self.sample_rate * self.channels * (self.bits // 8)
        header = struct.pack(
            "<4sI4s4sIHHIIHH4sI",
            b"RIFF",
            36 + data_size,
            b"WAVE",
            b"fmt ",
            16,
            1,
            self.channels,
            self.sample_rate,
            byte_rate,
            self.channels * (self.bits // 8),
            self.bits,
            b"data",
            data_size,
        )
        self.f.seek(0)
        self.f.write(header)
        self.f.close()


def stream_rack(rack, events, total_seconds, pcm=None, wav_path=None):
    """Run a rack for total_seconds, firing (block, callable) events, into a PCM device and/or a WAV.

    The float blocks are scaled to 16-bit into one preallocated bytearray
    that the WAV writer and the device read from.
    """
    total_blocks = int(total_seconds * BLOCKS_PER_SECOND)
    queue = sorted(events, key=lambda e: e[0]) if events else []
    next_event = 0
    channels = pcm.format.channels if pcm is not None else 2
    ba = bytearray(BLOCK_SIZE * channels * 2)
    interleaved = np.frombuffer(ba, dtype=INT16_DTYPE)
    if channels == 2:
        view_l = interleaved[0::2]
        view_r = interleaved[1::2]

    wav_out = WavWriter(wav_path, sample_rate=SAMPLE_RATE, channels=channels) if wav_path else None

    for block in range(total_blocks):
        while next_event < len(queue) and queue[next_event][0] <= block:
            queue[next_event][1]()
            next_event += 1
        rack.step()
        out_l = rack.output_buffer_left
        out_r = rack.output_buffer_right
        if channels == 2:
            view_l[:] = np.clip(out_l * 27000.0, -27000.0, 27000.0)
            view_r[:] = np.clip(out_r * 27000.0, -27000.0, 27000.0)
        else:
            interleaved[:] = np.clip((out_l + out_r) * 13500.0, -27000.0, 27000.0)
        if pcm is not None:
            pcm.write(ba)
        if wav_out is not None:
            wav_out.write(ba)
        if block % 128 == 0:
            gc.collect()

    if wav_out is not None:
        wav_out.close()
        try:
            size = os.stat(wav_path)[6]
        except OSError:
            size = 0
        print("  Exported WAV: %s (%d bytes)" % (wav_path, size))
    if pcm is not None:
        sleep_ms(60)
        gc.collect()


def render_rack_to_wav(rack, filename, events, total_seconds):
    stream_rack(rack, events, total_seconds, pcm=None, wav_path=filename)


# -- the movements --------------------------------------------------------------


def note_events(midi, pattern, step_blocks, hold, velocity):
    """Note on/off pairs for a pattern of MIDI notes, one every step_blocks blocks."""
    events = []
    for idx, pitch in enumerate(pattern):
        t_on = idx * step_blocks
        t_off = t_on + int(step_blocks * hold)
        events.append((t_on, lambda p=pitch: midi.note_on(p, velocity)))
        events.append((t_off, lambda p=pitch: midi.note_off(p)))
    return events


def pattern_seconds(pattern, step_blocks, tail):
    return (len(pattern) * step_blocks) / BLOCKS_PER_SECOND + tail


def keyboard_rack(voice_cls, voice_id):
    """A rack with a MIDI-CV module patched into a voice's keyboard inputs."""
    rack = Rack(sample_rate=SAMPLE_RATE, block_size=BLOCK_SIZE)
    midi = rack.add_module(MidiCVModule("midi_cv"))
    voice = rack.add_module(voice_cls(voice_id))
    rack.connect(midi.pitch_out, voice.kybd_cv_in, color="#9b59b6")
    rack.connect(midi.gate_out, voice.kybd_gate_in, color="#3498db")
    return rack, midi, voice


def set_params(module, **params):
    for name, value in params.items():
        module.set_param(name, value)


def movement_01():
    """Patch2600: resonant bass with the spring reverb."""
    rack, midi, voice = keyboard_rack(Patch2600, "patch2600")
    rack.connect(voice.master_l_out, rack.master_left_in, color="#e74c3c")
    rack.connect(voice.master_r_out, rack.master_right_in, color="#e74c3c")
    set_params(
        voice,
        vcf_cutoff=0.40,
        vcf_res=0.60,
        vcf_mod2_lvl=0.85,
        adsr_attack=0.005,
        adsr_decay=0.16,
        adsr_sustain=0.20,
        adsr_release=0.18,
        reverb_mix=0.35,
    )
    pattern = [36, 36, 39, 41, 36, 43, 46, 48, 46, 43, 41, 39]
    return rack, note_events(midi, pattern, 90, 0.70, 115), pattern_seconds(pattern, 90, 0.4)


def movement_02():
    """Modular100: synced dual VCO lead with LFO vibrato."""
    rack = Rack(sample_rate=SAMPLE_RATE, block_size=BLOCK_SIZE)
    midi = rack.add_module(MidiCVModule("midi_cv"))
    vco = rack.add_module(Modular100VCO("vco"))
    vcf = rack.add_module(Modular100VCF("vcf"))
    vca = rack.add_module(Modular100VCA("vca"))
    env_lfo = rack.add_module(Modular100EnvLFO("env"))
    rack.connect(vco.vco1_saw_out, vcf.vcf1_audio1, color="#e74c3c")
    rack.connect(vco.vco2_pulse_out, vcf.vcf1_audio2, color="#e67e22")
    set_params(vcf, vcf1_in1_level=0.6, vcf1_in2_level=0.6)
    rack.connect(vcf.vcf1_out, vca.vca1_audio1, color="#f1c40f")
    vca.set_param("vca1_in1_level", 1.0)
    rack.connect(vca.vca1_out, rack.master_left_in, color="#2ecc71")
    rack.connect(midi.pitch_out, vco.vco1_pitch_in, color="#9b59b6")
    rack.connect(midi.pitch_out, vco.vco2_pitch_in, color="#9b59b6")
    rack.connect(midi.gate_out, env_lfo.env1_gate_in, color="#3498db")
    rack.connect(env_lfo.env1_out, vcf.vcf1_mod2, color="#e74c3c")
    set_params(vcf, vcf1_mod2_level=0.75, vcf1_cutoff=0.45, vcf1_res=0.65)
    rack.connect(env_lfo.env2_out, vca.vca1_mod1, color="#f39c12")
    vca.set_param("vca1_mod1_level", 1.0)
    rack.connect(env_lfo.lfo_tri_out, vco.vco1_mod2_in, color="#1abc9c")
    vco.set_param("vco1_mod2_level", 0.035)
    env_lfo.set_param("lfo_rate", 0.42)
    vco.set_param("vco2_tune", 7.0 / 12.0)
    pattern = [60, 67, 72, 76, 74, 71, 67, 60]
    return rack, note_events(midi, pattern, 105, 0.85, 105), pattern_seconds(pattern, 105, 0.4)


def movement_03():
    """ParaphonicSynth: overdrive, wave morphing and the BBD delay."""
    rack, midi, voice = keyboard_rack(ParaphonicSynth, "paraphonic_synth")
    rack.connect(voice.master_out, rack.master_left_in, color="#e74c3c")
    set_params(
        voice,
        vco1_shape=0.25,
        vco2_shape=0.05,
        vco2_tune=0.03,
        vco_mix=0.5,
        vcf_cutoff=0.48,
        vcf_res=0.50,
        vcf_mod_depth=0.80,
        od_drive=0.65,
        od_tone=0.60,
        delay_time=0.16,
        delay_repeats=0.55,
        delay_mix=0.40,
    )
    pattern = [50, 50, 53, 55, 50, 60, 57, 55, 53, 50]
    return rack, note_events(midi, pattern, 85, 0.70, 120), pattern_seconds(pattern, 85, 0.8)


def movement_04():
    """Modular55: two VCOs into the low-pass ladder and the VCA."""
    rack = Rack(sample_rate=SAMPLE_RATE, block_size=BLOCK_SIZE)
    midi = rack.add_module(MidiCVModule("midi_cv"))
    vco1 = rack.add_module(Modular55VCO("vco1"))
    vco2 = rack.add_module(Modular55VCO("vco2"))
    lpf = rack.add_module(Modular55LowPass("lpf"))
    env = rack.add_module(Modular55Envelope("env"))
    vca = rack.add_module(Modular55VCA("vca"))
    rack.connect(midi.pitch_out, vco1.freq_cv1, color="#9b59b6")
    rack.connect(midi.pitch_out, vco2.freq_cv1, color="#9b59b6")
    rack.connect(midi.gate_out, env.trigger_in, color="#3498db")
    set_params(vco1, range=1.0, fine=0.0)
    set_params(vco2, range=0.0, pw=0.40, fine=0.02)
    rack.connect(vco1.saw_out, lpf.audio_in, color="#e74c3c")
    rack.connect(lpf.audio_out, vca.audio_in_pos, color="#2ecc71")
    rack.connect(vco2.rect_out, vca.audio_in_neg, color="#3498db")
    rack.connect(env.env_out, lpf.cv1_in, color="#f1c40f")
    set_params(lpf, fixed_cv=-0.4, regen=0.65, drive=1.6)
    rack.connect(env.env_out, vca.cv1_in, color="#f39c12")
    set_params(vca, mode=1.0, fixed_cv=0.0)
    set_params(env, t1=0.006, t2=0.22, es=0.18, t3=0.15)
    rack.connect(vca.audio_out_pos, rack.master_left_in, color="#2ecc71")
    rack.connect(vca.audio_out_pos, rack.master_right_in, color="#2ecc71")
    pattern = [43, 43, 46, 48, 43, 41, 43, 55, 53, 50, 48, 46]
    return rack, note_events(midi, pattern, 85, 0.72, 125), pattern_seconds(pattern, 85, 0.6)


def movement_05():
    """StateVariableMono: a multimode filter sweep on a brass lead."""
    rack, midi, voice = keyboard_rack(StateVariableMono, "state_variable_mono")
    rack.connect(voice.vca_out, rack.master_left_in, color="#f1c40f")
    rack.connect(voice.vca_out, rack.master_right_in, color="#f1c40f")
    set_params(
        voice,
        vco1_wave=0.0,
        vco2_wave=0.0,
        vco2_fine=0.02,
        vco_mix=0.5,
        vcf_cutoff=0.38,
        vcf_res=0.40,
        vcf_mode=0.20,
        vcf_env1_depth=0.85,
        env1_attack=0.012,
        env1_decay=0.28,
        env1_sustain=0.35,
        env2_attack=0.008,
        env2_decay=0.25,
        env2_sustain=0.50,
    )
    pattern = [64, 67, 71, 74, 76, 74, 71, 67]
    return rack, note_events(midi, pattern, 100, 0.80, 115), pattern_seconds(pattern, 100, 0.6)


def movement_06():
    """Duo20: high-pass into low-pass with both peaks up."""
    rack, midi, voice = keyboard_rack(Duo20, "duo20")
    rack.connect(voice.vca_out, rack.master_left_in, color="#e74c3c")
    rack.connect(voice.vca_out, rack.master_right_in, color="#e74c3c")
    set_params(
        voice,
        vco1_scale=1.0,
        vco1_wave=1.0,
        vco2_scale=1.0,
        vco2_wave=2.0,
        vco2_pitch=0.02,
        hpf_cutoff=0.18,
        hpf_peak=0.45,
        lpf_cutoff=0.42,
        lpf_peak=0.70,
        lpf_eg2_depth=0.85,
        eg2_attack=0.005,
        eg2_decay=0.16,
        eg2_sustain=0.15,
        eg2_release=0.14,
    )
    pattern = [36, 48, 36, 39, 41, 36, 48, 51, 48, 41, 39, 36]
    return rack, note_events(midi, pattern, 75, 0.65, 125), pattern_seconds(pattern, 75, 0.6)


def movement_07():
    """WestCoastSynth: wavefolded plucks through the low-pass gates."""
    rack, midi, voice = keyboard_rack(WestCoastSynth, "west_coast_synth")
    rack.connect(voice.lpg2_out, rack.master_left_in, color="#1abc9c")
    rack.connect(voice.lpg2_out, rack.master_right_in, color="#1abc9c")
    set_params(voice, timbre=0.70, fm_index=0.35, lpg1_decay=0.18, lpg2_decay=0.22, func1_fall=0.20)
    pattern = [48, 51, 55, 58, 60, 63, 60, 58, 55, 51]
    return rack, note_events(midi, pattern, 80, 0.50, 125), pattern_seconds(pattern, 80, 0.6)


def movement_08():
    """PinMatrix3: the diode ladder with the trapezoid pinned to its cutoff, and the reverb."""
    rack, midi, voice = keyboard_rack(PinMatrix3, "pin_matrix3")
    rack.connect(voice.out_left, rack.master_left_in, color="#e67e22")
    rack.connect(voice.out_right, rack.master_right_in, color="#e67e22")
    set_params(voice, filter_freq=0.42, filter_res=0.55, reverb_mix=0.35, trap_decay=0.25)
    voice.set_pin(8, 4, 0.75)
    pattern = [45, 48, 52, 57, 52, 48, 45, 40]
    return rack, note_events(midi, pattern, 80, 0.60, 115), pattern_seconds(pattern, 80, 0.6)


def movement_09():
    """MonoOne: synced VCOs and poly-mod into the four-pole filter."""
    rack, midi, voice = keyboard_rack(MonoOne, "pro1")
    rack.connect(voice.vca_out, rack.master_left_in, color="#34495e")
    rack.connect(voice.vca_out, rack.master_right_in, color="#34495e")
    set_params(
        voice,
        filter_cutoff=0.42,
        filter_res=0.60,
        filter_env_amt=0.85,
        polymod_filtenv=0.30,
        polymod_dest_freq_a=0.25,
        vco_a_sync=1.0,
    )
    pattern = [36, 36, 48, 39, 41, 36, 46, 48]
    return rack, note_events(midi, pattern, 75, 0.70, 120), pattern_seconds(pattern, 75, 0.6)


def movement_10():
    """HybridMono: the CMOS filter driven hard."""
    rack, midi, voice = keyboard_rack(HybridMono, "hybrid_mono")
    rack.connect(voice.vca_out, rack.master_left_in, color="#f39c12")
    rack.connect(voice.vca_out, rack.master_right_in, color="#f39c12")
    set_params(voice, filter_freq=0.45, filter_res=0.55, drive=1.8, env_decay=0.20)
    pattern = [50, 53, 57, 62, 57, 53, 50, 48]
    return rack, note_events(midi, pattern, 75, 0.65, 115), pattern_seconds(pattern, 75, 0.6)


def movement_11():
    """Semi32: its own sequencer running a sixteen-step groove."""
    rack = Rack(sample_rate=SAMPLE_RATE, block_size=BLOCK_SIZE)
    m32 = rack.add_module(Semi32("m32"))
    rack.connect(m32.vca_out, rack.master_left_in, color="#c0392b")
    rack.connect(m32.vca_out, rack.master_right_in, color="#c0392b")
    set_params(
        m32, seq_running=1.0, tempo_bpm=132.0, cutoff=0.42, resonance=0.55, filter_env_amt=0.85
    )
    m32.set_pattern([36, 48, 36, 39, 41, 36, 46, 48, 51, 48, 41, 39, 36, 48, 46, 43])
    return rack, [], 1.6


def movement_12():
    """FunctionGenerator: two cycling channels modulate a Modular100 voice."""
    rack = Rack(sample_rate=SAMPLE_RATE, block_size=BLOCK_SIZE)
    function_generator = rack.add_module(FunctionGenerator("function_generator"))
    vco = rack.add_module(Modular100VCO("vco_m"))
    vcf = rack.add_module(Modular100VCF("vcf_m"))
    vca = rack.add_module(Modular100VCA("vca_m"))
    function_generator.ch1_cycle = True
    function_generator.ch1_rise = 0.05
    function_generator.ch1_fall = 0.08
    function_generator.ch4_cycle = True
    function_generator.ch4_rise = 0.4
    function_generator.ch4_fall = 0.6
    rack.connect(function_generator.ch1_out, vco.vco1_mod1_in)
    rack.connect(function_generator.ch4_out, vcf.vcf1_mod1)
    rack.connect(vco.vco1_saw_out, vcf.vcf1_audio1)
    rack.connect(vcf.vcf1_out, vca.vca1_audio1)
    rack.connect(vca.vca1_out, rack.master_left_in)
    rack.connect(vca.vca1_out, rack.master_right_in)
    vco.set_param("vco1_tune", 0.0)
    set_params(vcf, vcf1_cutoff=0.4, vcf1_res=0.7)
    vca.set_param("vca1_init_gain", 0.7)
    return rack, [], 1.4


def movement_13():
    """MacroOscillator: the chord model."""
    rack = Rack(sample_rate=SAMPLE_RATE, block_size=BLOCK_SIZE)
    macro_oscillator = rack.add_module(MacroOscillator("macro_oscillator"))
    macro_oscillator.model = 5
    macro_oscillator.harmonics = 0.6
    macro_oscillator.timbre = 0.4
    macro_oscillator.morph = 0.5
    macro_oscillator.base_freq = 130.81
    rack.connect(macro_oscillator.out, rack.master_left_in)
    rack.connect(macro_oscillator.aux_out, rack.master_right_in)
    return rack, [], 1.4


def movement_14():
    """RandomSequencer: a locked eight-step loop clocked by an LFO, into a Modular100 voice."""
    rack = Rack(sample_rate=SAMPLE_RATE, block_size=BLOCK_SIZE)
    tm = rack.add_module(RandomSequencer("tm"))
    lfo = rack.add_module(Modular100EnvLFO("lfo_tm"))
    vco = rack.add_module(Modular100VCO("vco_tm"))
    vcf = rack.add_module(Modular100VCF("vcf_tm"))
    vca = rack.add_module(Modular100VCA("vca_tm"))
    lfo.set_param("lfo_rate", 0.6)
    rack.connect(lfo.lfo_square_out, tm.clock_in)
    rack.connect(tm.cv_out, vco.vco1_pitch_in)
    rack.connect(tm.gate_out, vca.vca1_mod1)
    rack.connect(vco.vco1_saw_out, vcf.vcf1_audio1)
    rack.connect(vcf.vcf1_out, vca.vca1_audio1)
    rack.connect(vca.vca1_out, rack.master_left_in)
    rack.connect(vca.vca1_out, rack.master_right_in)
    set_params(vcf, vcf1_cutoff=0.55, vcf1_res=0.4)
    tm.probability = 1.0
    tm.length = 8
    return rack, [], 1.4


def movement_15():
    """DrumSynth: an eight-step percussion groove with FM."""
    rack = Rack(sample_rate=SAMPLE_RATE, block_size=BLOCK_SIZE)
    drum_synth = rack.add_module(DrumSynth("drum_synth"))
    drum_synth.bpm = 135.0
    drum_synth.vco1_freq = 55.0
    drum_synth.vco2_freq = 110.0
    drum_synth.fm_amount = 0.65
    drum_synth.resonance = 0.55
    drum_synth.vcf_decay = 0.12
    drum_synth.vca_decay = 0.22
    pitches = [0.0, 0.05, -0.02, 0.08, 0.0, 0.12, -0.05, 0.03]
    velocities = [1.0, 0.7, 0.85, 0.6, 0.95, 0.75, 0.8, 0.65]
    for step in range(8):
        drum_synth.set_step(step, pitches[step], velocities[step])
    rack.connect(drum_synth.audio_out, rack.master_left_in)
    rack.connect(drum_synth.audio_out, rack.master_right_in)
    return rack, [], 1.6


def movement_16():
    """PolyrhythmSynth: polyrhythmic undertone chords."""
    rack = Rack(sample_rate=SAMPLE_RATE, block_size=BLOCK_SIZE)
    sub = rack.add_module(PolyrhythmSynth("sub"))
    sub.bpm = 118.0
    sub.vco1_freq = 110.0
    sub.vco2_freq = 164.81
    sub.sub1a_div = 2
    sub.sub1b_div = 3
    sub.sub2a_div = 2
    sub.sub2b_div = 4
    sub.cutoff_hz = 1400.0
    sub.resonance = 0.4
    sub.vca_decay = 0.35
    rack.connect(sub.audio_out, rack.master_left_in)
    rack.connect(sub.audio_out, rack.master_right_in)
    return rack, [], 1.6


def movement_17():
    """Acid303: a sixteen-step acid line with accents and slides."""
    rack = Rack(sample_rate=SAMPLE_RATE, block_size=BLOCK_SIZE)
    tb = rack.add_module(Acid303("acid303"))
    tb.bpm = 138.0
    tb.tuning = 65.41
    tb.cutoff_hz = 450.0
    tb.resonance = 0.85
    tb.env_mod = 0.75
    tb.decay = 0.22
    tb.accent = 0.85
    tb.waveform = 0
    steps = [
        (0.0, 1, 1, 0), (0.0, 1, 0, 1), (0.1, 1, 0, 0), (0.0, 0, 0, 0),
        (0.0, 1, 1, 0), (0.07, 1, 0, 1), (0.0, 1, 0, 0), (0.02, 1, 0, 0),
        (0.12, 1, 1, 1), (0.0, 1, 0, 0), (0.0, 0, 0, 0), (0.05, 1, 0, 1),
        (0.0, 1, 1, 0), (0.1, 1, 0, 0), (0.0, 1, 0, 0), (0.02, 1, 1, 0),
    ]  # fmt: skip
    for idx, (pitch, gate, accent, slide) in enumerate(steps):
        tb.set_step(idx, pitch, gate=bool(gate), accent=bool(accent), slide=bool(slide))
    rack.connect(tb.audio_out, rack.master_left_in)
    rack.connect(tb.audio_out, rack.master_right_in)
    return rack, [], 1.8


def movement_18():
    """WestCoast0: overtones and folding, cycled by Slope."""
    rack = Rack(sample_rate=SAMPLE_RATE, block_size=BLOCK_SIZE)
    zc = rack.add_module(WestCoast0("0c"))
    zc.base_freq = 110.0
    zc.overtone = 0.55
    zc.multiply = 0.70
    zc.balance = 0.65
    zc.dynamics = 0.85
    zc.slope_rise = 0.015
    zc.slope_fall = 0.12
    zc.slope_cycle = True
    rack.connect(zc.audio_out, rack.master_left_in)
    rack.connect(zc.audio_out, rack.master_right_in)
    return rack, [], 1.4


def movement_19():
    """ModalResonator: the modal resonator struck three times."""
    rack = Rack(sample_rate=SAMPLE_RATE, block_size=BLOCK_SIZE)
    modal_resonator = rack.add_module(ModalResonator("modal_resonator"))
    modal_resonator.model = 0
    modal_resonator.base_freq = 220.0
    modal_resonator.structure = 0.65
    modal_resonator.brightness = 0.7
    modal_resonator.damping = 0.8
    rack.connect(modal_resonator.out, rack.master_left_in)
    rack.connect(modal_resonator.aux_out, rack.master_right_in)
    return (
        rack,
        [(0, modal_resonator.strum), (150, modal_resonator.strum), (300, modal_resonator.strum)],
        1.4,
    )


def movement_20():
    """GranularProcessor: a saw granulated and shimmered into the reverb."""
    rack = Rack(sample_rate=SAMPLE_RATE, block_size=BLOCK_SIZE)
    vco = rack.add_module(Modular100VCO("vco_cl"))
    granular_processor = rack.add_module(GranularProcessor("granular_processor"))
    vco.set_param("vco1_tune", -0.1)
    granular_processor.position = 0.4
    granular_processor.size = 0.3
    granular_processor.pitch = 0.25
    granular_processor.density = 0.8
    granular_processor.reverb = 0.65
    rack.connect(vco.vco1_saw_out, granular_processor.audio_in_l)
    rack.connect(granular_processor.audio_out_l, rack.master_left_in)
    rack.connect(granular_processor.audio_out_r, rack.master_right_in)
    return rack, [], 1.6


MOVEMENTS = (
    ("patch2600", "Patch2600: resonant bass with the spring reverb", movement_01),
    ("modular100", "Modular100: synced dual VCO lead with LFO vibrato", movement_02),
    (
        "paraphonic_synth",
        "ParaphonicSynth: overdrive, wave morphing and the BBD delay",
        movement_03,
    ),
    (
        "modular55",
        "Modular55: two VCOs into the low-pass ladder and the VCA",
        movement_04,
    ),
    (
        "state_variable_mono",
        "StateVariableMono: a multimode filter sweep on a brass lead",
        movement_05,
    ),
    ("duo20", "Duo20: high-pass into low-pass with both peaks up", movement_06),
    (
        "west_coast_synth",
        "WestCoastSynth: wavefolded plucks through the low-pass gates",
        movement_07,
    ),
    (
        "pin_matrix3",
        "PinMatrix3: the diode ladder under the trapezoid, and the reverb",
        movement_08,
    ),
    (
        "mono_one",
        "MonoOne: synced VCOs and poly-mod into the four-pole filter",
        movement_09,
    ),
    ("hybrid_mono", "HybridMono: the CMOS filter driven hard", movement_10),
    ("semi32", "Semi32: its own sequencer running a sixteen-step groove", movement_11),
    (
        "function_generator",
        "FunctionGenerator: two cycling channels modulate a Modular100 voice",
        movement_12,
    ),
    ("macro_oscillator", "MacroOscillator: the chord model", movement_13),
    (
        "random_sequencer",
        "RandomSequencer: a locked eight-step loop clocked by an LFO",
        movement_14,
    ),
    ("drum_synth", "DrumSynth: an eight-step percussion groove with FM", movement_15),
    ("polyrhythm_synth", "PolyrhythmSynth: polyrhythmic undertone chords", movement_16),
    ("acid303", "Acid303: a sixteen-step acid line with accents and slides", movement_17),
    ("west_coast0", "WestCoast0: overtones and folding, cycled by Slope", movement_18),
    ("modal_resonator", "ModalResonator: the modal resonator struck three times", movement_19),
    (
        "granular_processor",
        "GranularProcessor: a saw granulated and shimmered into the reverb",
        movement_20,
    ),
)


def build_movement(number):
    """(name, rack, events, seconds) for movement 1..20; MOVEMENTS holds (name, title, builder)."""
    name, _title, build = MOVEMENTS[number - 1]
    rack, events, seconds = build()
    return name, rack, events, seconds


# -- the show -------------------------------------------------------------------


def open_pcm():
    """A live output through the pydevices audio stack, or None."""
    try:
        import board_config
        from audiodev import AudioFormat
    except ImportError:
        return None
    pcm = board_config.pcm_out(AudioFormat(SAMPLE_RATE, 2, 16), latency="low")
    pcm.open()
    pcm.set_volume(90)
    pcm.mute(False)
    print("Live output: %s" % (pcm.format,))
    return pcm


def run_showcase(argv):
    wav_dir = None
    live = True
    target = None
    for arg in argv:
        if arg in ("--wav", "--export-wav"):
            wav_dir = "wav_exports"
        elif arg.startswith("--wav-dir="):
            wav_dir = arg.split("=", 1)[1]
        elif arg == "--no-live":
            live = False
        elif arg.isdigit():
            target = int(arg)

    pcm = open_pcm() if live else None
    if pcm is None and wav_dir is None:
        print("No live output available; writing WAVs to wav_exports/")
        wav_dir = "wav_exports"
    if wav_dir:
        try:
            os.mkdir(wav_dir)
        except OSError:
            pass

    started = ticks_ms()
    for number in range(1, len(MOVEMENTS) + 1):
        if target is not None and target != number:
            continue
        name, rack, events, seconds = build_movement(number)
        print("\n--- Movement %d: %s ---" % (number, MOVEMENTS[number - 1][1]))
        wav_path = "%s/movement_%02d_%s.wav" % (wav_dir, number, name) if wav_dir else None
        stream_rack(rack, events, seconds, pcm=pcm, wav_path=wav_path)

    if pcm is not None:
        try:
            pcm.drain()
        except Exception:  # noqa: BLE001 - whatever the device raises on drain
            pass
        pcm.close()
    print("\nTotal session duration: %.2f seconds" % (ticks_diff(ticks_ms(), started) / 1000.0,))


if __name__ == "__main__":
    run_showcase(sys.argv[1:])
