# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""StringEnsemble monophonic bass section."""

import audiobiquad

from ...core.bridge import NodeBridge, biquad_kwargs
from ...core.jack import SignalType
from ...core.module import Module
from ...core.signal import BASE_FREQ_C4, add, copy_into, scaled_into
from ...dsp.envelope import EnvelopeCore
from ...dsp.oscillator import OscillatorCore
from .._util import jack_signal
from .envelope import ATTACK_TO_PEAK, CRESCENDO_RANGE, slider_time

#: The bottom 20 keys of a 49-key keyboard starting at MIDI 36 (C2 to G3).
BASS_LOW = 36
BASS_HIGH = 55

#: Cello 8' pulse width: 50% square wave.
CELLO_WIDTH = 0.5

#: Fixed release time for the bass in seconds.
BASS_RELEASE_S = 0.15

#: Fixed one-pole low-pass cutoff frequency for the bass in Hz.
BASS_TONE_HZ = 1000.0

#: Bass output level scaling.
BASS_SCALE = 1.0

#: Velocity sensitivity depth in the bass: at max vel_vca, velocity scales 0.2 to 1.0.
VEL_DEPTH = 0.8


class StringEnsembleBass(Module):
    """Monophonic bass module for the lowest held key on keys 36 to 55."""

    NAME = "StringEnsembleBass"
    DISPLAY_NAME = "StringEnsemble Bass"
    HP = 12

    def _build(self):
        sr, n = self.sample_rate, self.block_size
        self.osc16 = OscillatorCore(sr)
        self.osc8 = OscillatorCore(sr)
        self.env = EnvelopeCore(sr, n)
        self._build_filters(n)

        self._velocity = 1.0

        cv, gate, audio = SignalType.CV, SignalType.GATE, SignalType.AUDIO
        self.pitch_in = self.add_input("pitch", "Pitch", cv)
        self.note_in = self.add_input("note", "Note", cv)
        self.gate_in = self.add_input("gate", "Gate", gate)
        self.vel_in = self.add_input("velocity", "Velocity", cv)
        self.audio_out = self.add_output("out", "Bass Out", audio)

        self.add_param("contrabass", "Contra-bass 16'", default=0.0)
        self.add_param("cello", "Cello 8'", default=0.0)
        self.add_param("bass_volume", "Volume Bass", default=0.5)
        self.add_param("crescendo", "Crescendo", default=0.4)
        self.add_param("tune", "Tune", default=0.0, min_val=-50.0, max_val=50.0)
        self.add_param("vel_vca", "Velocity VCA", default=0.0)

        for name in (
            "_saw16",
            "_pulse8",
            "_mix",
            "_filtered",
            "_cv",
            "_last_pitch",
            "_bass_gate_buf",
            "_env_buf",
            "_tmp",
        ):
            self.add_scratch(name)

    def _build_filters(self, n):
        self._filter_node = audiobiquad.AllPass(
            stages=1,
            frequency=BASS_TONE_HZ,
            feedback=0.0,
            mix=0.5,
            sample_rate=self.sample_rate,
            channel_count=1,
            **biquad_kwargs(n),
        )
        self.bridge = NodeBridge(n, self.sample_rate).chain(self._filter_node)

    def set_block_size(self, block_size):
        super().set_block_size(block_size)
        self.env.set_block_size(block_size)
        self._build_filters(block_size)

    def reset(self):
        self.env.reset()
        self.bridge.reset()
        self._last_pitch[:] = 0.0

    def process(self, block_size):
        n = block_size
        p = self.params

        gate_buf = jack_signal(self.gate_in)
        gate_high = gate_buf is not None and gate_buf[n - 1] > 0.5

        note_buf = jack_signal(self.note_in)
        if note_buf is not None:
            note_cv = float(note_buf[n - 1])
            key = 60.0 + note_cv * 120.0
            is_bass_key = (BASS_LOW - 0.5) <= key <= (BASS_HIGH + 0.5)
        else:
            is_bass_key = False

        bass_gate_high = gate_high and is_bass_key

        if bass_gate_high:
            vel_buf = jack_signal(self.vel_in)
            if vel_buf is not None:
                self._velocity = float(vel_buf[0])
            pitch_buf = jack_signal(self.pitch_in)
            if pitch_buf is not None:
                copy_into(self._last_pitch, pitch_buf)
            else:
                self._last_pitch[:] = 0.0
            self._bass_gate_buf[:] = 1.0
        else:
            self._bass_gate_buf[:] = 0.0

        attack = slider_time(p["crescendo"], CRESCENDO_RANGE) / ATTACK_TO_PEAK
        self.env.set_times(attack, 0.01, 1.0, BASS_RELEASE_S)
        self.env.render(self._bass_gate_buf, self._env_buf)

        if self.env.state == 0 and not bass_gate_high:
            self.audio_out.buffer[:] = 0.0
            return

        contrabass = p["contrabass"] >= 0.5
        cello = p["cello"] >= 0.5
        if not (contrabass or cello):
            self.audio_out.buffer[:] = 0.0
            return

        cv = self._cv
        copy_into(cv, self._last_pitch)
        tune = p["tune"]
        if tune != 0.0:
            cv += tune / 12000.0

        base = BASE_FREQ_C4
        if contrabass:
            self.osc16.render(n, base * 0.5, cv, saw=self._saw16)
        if cello:
            self.osc8.render(n, base, cv, pulse_width=CELLO_WIDTH, pulse=self._pulse8)
            self._pulse8 -= CELLO_WIDTH - 0.5

        mix = self._mix
        mix[:] = 0.0
        if contrabass:
            add(mix, self._saw16)
        if cello:
            add(mix, self._pulse8)

        self.bridge.process(mix, self._filtered)
        self._filtered *= self._env_buf

        vel_vca = p["vel_vca"]
        vel_factor = 1.0 - vel_vca * VEL_DEPTH * (1.0 - self._velocity)
        gain = p["bass_volume"] * BASS_SCALE * vel_factor
        scaled_into(self.audio_out.buffer, self._filtered, gain)
