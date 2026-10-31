# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""MIDI to CV: pitch, gate, velocity, wheels, transport, knobs and pads as jacks.

The CC and pad maps follow two controllers, the Donner DMK-25 Pro and the
Arturia KeyStep Pro: knobs on CC 30-53 in three banks of eight, pads on
channel 10 notes 36-59 in three banks of eight, transport on CC 16/18/19.
Feed it with ``receive_message(status, data1, data2)`` or the named
methods. Notes are monophonic. The keys held go on a stack, and ``priority``
says which of them sounds: ``"last"`` (the default, the newest key, and
letting it go returns to the one before), ``"low"`` or ``"high"``, or
``"duo"``, which sounds two keys at once (see below).

Three jacks tell a mono voice how the line is played. ``trig`` is a 2 ms pulse
when a note starts: on a fresh press (no key and no pedal holding the gate), or
on every press when ``retrigger`` is on. ``legato`` is high while the sounding
note was reached with the gate already up (a key pressed over another, or the
return to a held key when the newer one lets go), and low after a fresh press
and when the gate falls. ``note`` is ``pitch`` without the pitch bend, so a
voice can glide the note and leave the bend alone.

``pitch_hi`` and ``note_hi`` are a second line, for a voice with two oscillators
on two keys. In every priority but ``"duo"`` they equal ``pitch`` and ``note``,
so that voice plays one line on both. In ``"duo"`` the lowest key held is
``pitch`` and ``note`` and the highest is ``pitch_hi`` and ``note_hi`` (one key
held is both), a key pressed between the two sounds nothing, and letting a key
go moves the lines to the lowest and highest keys still held. ``trig`` fires
for a press only when that key is now the lowest or the highest; ``vel`` is its
velocity then. ``glide`` slides ``pitch`` and ``note`` only: the high jacks
jump, and a voice that wants a glide on them does it itself.

``press`` is the pressure on the keys, 0 to 1: the channel pressure, or the
poly pressure of the key that is sounding, whichever is larger. A key starts
at no poly pressure when it is pressed; a key's pressure stays at its last
value after the key is released, while its note dies away. Poly pressure for
a key that is not held changes nothing.

``expr`` and ``foot`` are two pedals: Expression (CC 11) and Foot Controller
(CC 4), each the value over 127, 0 to 1. Both read 1.0 before any message
arrives (a pedal fully forward), so a voice that reads them plays at full until
a pedal moves. ``reset()`` rewrites them and leaves their values.

The sustain pedal holds the gate when the last key goes up, and the note
keeps sounding; a key pressed under the held gate is a legato note. Lifting
the pedal with no key down drops the gate.
"""

import math

from ..core.jack import SignalType
from ..core.module import Module
from ..core.signal import copy_into, midi_note_to_pitch
from ..dsp.blocks import Ramp, exp_segment
from ..dsp.sequencers import PulseTrain
from ..midi_cc import EXPRESSION, FOOT_CONTROLLER

PRIORITIES = ("last", "low", "high", "duo")


class MidiCVModule(Module):
    NAME = "MidiCV"
    DISPLAY_NAME = "MIDI to CV"
    HP = 18

    MACRO_LABELS = ("knob_bank", "pad_bank", "glide", "bend_range")
    MACRO_MODES = {0: "TOGGLE", 1: "TOGGLE", 2: "UNIPOLAR", 3: "UNIPOLAR"}

    def _build(self):
        self.pitch_out = self.add_output("pitch", "1V/Oct", SignalType.CV)
        self.gate_out = self.add_output("gate", "Gate", SignalType.GATE)
        self.vel_out = self.add_output("vel", "Velocity", SignalType.CV)
        self.bend_out = self.add_output("bend", "Pitch Bend", SignalType.CV)
        self.mod_out = self.add_output("mod", "Mod Wheel", SignalType.CV)
        self.pedal_out = self.add_output("pedal", "Sustain", SignalType.GATE)
        self.trig_out = self.add_output("trig", "Note Trig", SignalType.TRIGGER)
        self.legato_out = self.add_output("legato", "Legato", SignalType.GATE)
        self.note_out = self.add_output("note", "1V/Oct, no bend", SignalType.CV)
        self.pitch_hi_out = self.add_output("pitch_hi", "1V/Oct, high key", SignalType.CV)
        self.note_hi_out = self.add_output("note_hi", "1V/Oct, high key, no bend", SignalType.CV)
        self.press_out = self.add_output("press", "Pressure", SignalType.CV)
        self.expr_out = self.add_output("expr", "Expression", SignalType.CV)
        self.foot_out = self.add_output("foot", "Foot Controller", SignalType.CV)

        self.run_out = self.add_output("run", "Run/Play", SignalType.GATE)
        self.stop_out = self.add_output("stop", "Stop Trig", SignalType.TRIGGER)
        self.reset_out = self.add_output("reset", "Reset Trig", SignalType.TRIGGER)
        self.clock_out = self.add_output("clock", "Clock Out", SignalType.CLOCK)

        # eight live knob/pad jacks follow the selected bank; all 24 are also jacks
        self.knob_outs = [
            self.add_output("knob%d" % (i + 1), "Knob %d" % (i + 1), SignalType.CV)
            for i in range(8)
        ]
        self.pad_outs = [
            self.add_output("pad%d" % (i + 1), "Pad %d" % (i + 1), SignalType.TRIGGER)
            for i in range(8)
        ]
        self.knob_banks = {}
        self.pad_banks = {}
        for bank, letter in enumerate("abc"):
            self.knob_banks[bank] = [
                self.add_output(
                    "knob_%s%d" % (letter, i + 1),
                    "Knob %s%d" % (letter.upper(), i + 1),
                    SignalType.CV,
                )
                for i in range(8)
            ]
            self.pad_banks[bank] = [
                self.add_output(
                    "pad_%s%d" % (letter, i + 1),
                    "Pad %s%d" % (letter.upper(), i + 1),
                    SignalType.TRIGGER,
                )
                for i in range(8)
            ]

        self.add_param("knob_bank", "Knob Bank", default=0.0, min_val=0.0, max_val=2.0)
        self.add_param("pad_bank", "Pad Bank", default=0.0, min_val=0.0, max_val=2.0)
        self.add_param("glide", "Portamento (s)", default=0.0, min_val=0.0, max_val=1.0)
        self.add_param(
            "bend_range", "Bend Range (semitones)", default=2.0, min_val=1.0, max_val=24.0
        )

        self.ramp = Ramp(self.block_size)
        self._current_pitch = 0.0
        self._target_pitch = 0.0
        self._target_hi = 0.0
        self._hi_note = None
        self._gate_active = False
        self._velocity = 0.0
        self._pitch_bend = 0.0
        self._mod_wheel = 0.0
        self._chan_press = 0.0
        self._expr = 1.0
        self._foot = 1.0
        self._note_press = [0.0] * 128
        self._lo_note = None
        self._sustain_pedal = False
        self._is_running = False
        self._held_notes = []
        self._sounding_note = None
        self._legato = False
        self._priority = "last"
        self._retrigger = False
        self._trig_pulse = PulseTrain(int(self.sample_rate * 0.002))

        pulse_10ms = int(self.sample_rate * 0.010)
        self._stop_pulse = PulseTrain(pulse_10ms)
        self._reset_pulse = PulseTrain(pulse_10ms)
        self._clock_pulse = PulseTrain(int(self.sample_rate * 0.002))
        self._knob_values = [[0.0] * 8 for _ in range(3)]
        self._pad_pulses = [
            [PulseTrain(int(self.sample_rate * 0.005)) for _ in range(8)] for _ in range(3)
        ]
        self._forget_jacks()

    def set_block_size(self, block_size):
        super().set_block_size(block_size)
        self.ramp = Ramp(block_size)
        self._forget_jacks()

    def reset(self):
        super().reset()
        self._forget_jacks()
        for i in range(128):
            self._note_press[i] = 0.0

    def _forget_jacks(self):
        """Every jack's last written value is unknown: write each one next block.

        ``process()`` writes a one-value jack only when its value differs from
        the last one it wrote, so anything else that touches those buffers (or
        replaces them) has to come through here.
        """
        self._w = [None] * 10
        self._w_mono_note = None
        self._w_mono_pitch = None
        self._w_hi_note = None
        self._w_hi_pitch = None
        self._w_knobs = [[None] * 8 for _ in range(3)]
        self._w_live_knobs = [None] * 8
        self._w_pad_bank = None
        for pulse in (self._trig_pulse, self._stop_pulse, self._reset_pulse, self._clock_pulse):
            pulse._hot = True
        for bank in self._pad_pulses:
            for pulse in bank:
                pulse._hot = True

    # -- MIDI in -------------------------------------------------------------------

    @property
    def priority(self):
        """Which held key sounds: ``"last"``, ``"low"``, ``"high"`` or ``"duo"`` (two)."""
        return self._priority

    @priority.setter
    def priority(self, priority):
        if priority not in PRIORITIES:
            raise ValueError(
                "priority must be one of %s, not %r" % (", ".join(PRIORITIES), priority)
            )
        self._priority = priority
        self._follow(None)

    @property
    def retrigger(self):
        """True to pulse ``trig`` on every key press, not only a fresh one."""
        return self._retrigger

    @retrigger.setter
    def retrigger(self, on):
        self._retrigger = bool(on)

    def note_on(self, note, velocity=64):
        if velocity == 0:
            self.note_off(note)
            return
        fresh = not self._gate_active
        self._note_press[note & 127] = 0.0
        self._held_notes = [n for n in self._held_notes if n[0] != note]
        self._held_notes.append((note, velocity))
        self._follow(note, fresh)

    def note_off(self, note):
        self._held_notes = [n for n in self._held_notes if n[0] != note]
        if self._held_notes:
            self._follow(None)
        elif not self._sustain_pedal:
            self._gate_off()

    def _chosen(self):
        """The held (note, velocity) the priority picks, or None."""
        held = self._held_notes
        if not held:
            return None
        if self._priority == "last":
            return held[-1]
        best = held[0]
        for entry in held:
            if (entry[0] < best[0]) if self._priority == "low" else (entry[0] > best[0]):
                best = entry
        return best

    def _follow_duo(self, pressed, fresh):
        """``"duo"``: the lowest held key is the line, the highest is the second line."""
        held = self._held_notes
        if not held:
            return
        low = high = held[0][0]
        for entry in held:
            if entry[0] < low:
                low = entry[0]
            elif entry[0] > high:
                high = entry[0]
        starts = pressed in (low, high)  # None, a release, is in neither
        if pressed is not None and not starts:
            return  # a key between the two ends sounds nothing
        if not starts and low == self._sounding_note and high == self._hi_note:
            return
        self._sounding_note = self._lo_note = low
        self._hi_note = high
        self._target_pitch = midi_note_to_pitch(low)
        self._target_hi = midi_note_to_pitch(high)
        if starts:
            self._velocity = held[-1][1] / 127.0  # the key just pressed is the newest
        self._gate_active = True
        self._legato = not fresh
        if starts and (fresh or self._retrigger):
            self._trig_pulse.fire()
        if self.params["glide"] <= 0.001:
            self._current_pitch = self._target_pitch

    def _follow(self, pressed, fresh=False):
        """Sound the note the priority picks. ``pressed`` is the key just pushed, if any."""
        if self._priority == "duo":
            self._follow_duo(pressed, fresh)
            return
        entry = self._chosen()
        if entry is None:
            return
        note, velocity = entry
        starts = note == pressed
        if not starts and note == self._sounding_note and note == self._hi_note:
            return
        self._sounding_note = self._lo_note = note
        self._hi_note = note
        self._target_pitch = midi_note_to_pitch(note)
        self._target_hi = self._target_pitch
        self._velocity = velocity / 127.0
        self._gate_active = True
        self._legato = not fresh
        if starts and (fresh or self._retrigger):
            self._trig_pulse.fire()
        if self.params["glide"] <= 0.001:
            self._current_pitch = self._target_pitch

    def _gate_off(self):
        self._gate_active = False
        self._sounding_note = None
        self._legato = False

    def _release_all(self):
        """Forget every key and drop the gate, whatever the pedal says."""
        self._held_notes = []
        self._gate_off()

    def pad_hit(self, bank, index, velocity=100):
        if 0 <= bank < 3 and 0 <= index < 8:
            self._pad_pulses[bank][index].fire()

    def control_change(self, cc, value):
        norm = value / 127.0
        if cc == 1:
            self._mod_wheel = norm
        elif cc == EXPRESSION:
            self._expr = norm
        elif cc == FOOT_CONTROLLER:
            self._foot = norm
        elif cc == 64:
            self._sustain_pedal = value >= 64
            if not self._sustain_pedal and not self._held_notes:
                self._gate_off()
        elif cc == 19:
            self._is_running = True
        elif cc == 18:
            self._is_running = False
            self._stop_pulse.fire()
        elif cc == 16:
            self._reset_pulse.fire()
        elif 30 <= cc <= 53:
            bank, k = divmod(cc - 30, 8)
            self._knob_values[bank][k] = norm

    def poly_pressure(self, note, value):
        """Pressure on one key, 0 to 127. Nothing happens unless the key is held."""
        for held in self._held_notes:
            if held[0] == note:
                self._note_press[note & 127] = value / 127.0
                return

    def channel_pressure(self, value):
        """Pressure on the whole keyboard, 0 to 127."""
        self._chan_press = value / 127.0

    def _key_pressure(self):
        """The poly pressure of the key (or the two keys, in ``"duo"``) last sounded."""
        v = 0.0
        if self._lo_note is not None:
            v = self._note_press[self._lo_note & 127]
        if self._hi_note is not None:
            hi = self._note_press[self._hi_note & 127]
            if hi > v:
                v = hi
        return v

    def _pressure(self):
        """``press``: the channel pressure or the sounding key's, whichever is larger."""
        v = self._key_pressure()
        return v if v > self._chan_press else self._chan_press

    def pitch_bend(self, value):
        """Bend as -1..1, or as the 14-bit MIDI value centred on 8192."""
        norm = (value - 8192) / 8192.0 if isinstance(value, int) and value > 1 else float(value)
        self._pitch_bend = max(-1.0, min(1.0, norm))

    def clock_pulse(self):
        self._clock_pulse.fire()

    def receive_message(self, status, data1, data2=0):
        msg_type = status & 0xF0
        channel = status & 0x0F
        if channel == 9 and msg_type in (0x90, 0x80):
            if msg_type == 0x90 and data2 > 0 and 36 <= data1 <= 59:
                bank, index = divmod(data1 - 36, 8)
                self.pad_hit(bank, index, data2)
            return
        if msg_type == 0x90:
            self.note_on(data1, data2) if data2 > 0 else self.note_off(data1)
        elif msg_type == 0x80:
            self.note_off(data1)
        elif msg_type == 0xB0:
            self.control_change(data1, data2)
        elif msg_type == 0xE0:
            self.pitch_bend((data2 << 7) | data1)
        elif msg_type == 0xA0:
            self.poly_pressure(data1, data2)
        elif msg_type == 0xD0:
            self.channel_pressure(data1)

    # -- block ---------------------------------------------------------------------

    def process(self, block_size):
        p = self.params
        bend = self._pitch_bend * (p["bend_range"] / 12.0) * 0.1
        glide = p["glide"]
        pitch = self.pitch_out.buffer
        note = self.note_out.buffer
        if glide > 0.001 and self._current_pitch != self._target_pitch:
            coeff = math.exp(-1.0 / (glide * self.sample_rate * 0.1))
            self._current_pitch = exp_segment(
                note, self._current_pitch, self._target_pitch, coeff, self.ramp
            )
            copy_into(pitch, note)
            pitch += bend
            self._w_mono_note = self._w_mono_pitch = None
        else:
            self._current_pitch = self._target_pitch
            if self._w_mono_note != self._current_pitch:
                note[:] = self._current_pitch
                self._w_mono_note = self._current_pitch
            p_now = self._current_pitch + bend
            if self._w_mono_pitch != p_now:
                pitch[:] = p_now
                self._w_mono_pitch = p_now

        # The second line never glides: it is the high key's pitch, or the line's.
        hi = self._target_hi
        if self._w_hi_note != hi:
            self.note_hi_out.buffer[:] = hi
            self._w_hi_note = hi
        p_hi = hi + bend
        if self._w_hi_pitch != p_hi:
            self.pitch_hi_out.buffer[:] = p_hi
            self._w_hi_pitch = p_hi

        # Every other jack holds one value a block. Each is written only when
        # its value changes, so an idle block costs a comparison per jack,
        # not a fill.
        w = self._w
        g = 1.0 if self._gate_active else 0.0
        if w[0] != g:
            self.gate_out.buffer[:] = g
            w[0] = g
        g = 1.0 if self._legato else 0.0
        if w[1] != g:
            self.legato_out.buffer[:] = g
            w[1] = g
        if w[2] != self._velocity:
            self.vel_out.buffer[:] = self._velocity
            w[2] = self._velocity
        g = self._pitch_bend * 0.5
        if w[3] != g:
            self.bend_out.buffer[:] = g
            w[3] = g
        if w[4] != self._mod_wheel:
            self.mod_out.buffer[:] = self._mod_wheel
            w[4] = self._mod_wheel
        g = 1.0 if self._sustain_pedal else 0.0
        if w[5] != g:
            self.pedal_out.buffer[:] = g
            w[5] = g
        g = 1.0 if self._is_running else 0.0
        if w[6] != g:
            self.run_out.buffer[:] = g
            w[6] = g
        g = self._pressure()
        if w[7] != g:
            self.press_out.buffer[:] = g
            w[7] = g
        if w[8] != self._expr:
            self.expr_out.buffer[:] = self._expr
            w[8] = self._expr
        if w[9] != self._foot:
            self.foot_out.buffer[:] = self._foot
            w[9] = self._foot
        self._trig_pulse.fill_changed(self.trig_out.buffer)
        self._stop_pulse.fill_changed(self.stop_out.buffer)
        self._reset_pulse.fill_changed(self.reset_out.buffer)
        self._clock_pulse.fill_changed(self.clock_out.buffer)

        k_bank = int(p["knob_bank"]) % 3
        p_bank = int(p["pad_bank"]) % 3
        wk = self._w_knobs
        live_k = self._w_live_knobs
        for bank in range(3):
            knobs = self.knob_banks[bank]
            values = self._knob_values[bank]
            pads = self.pad_banks[bank]
            pulses = self._pad_pulses[bank]
            written = wk[bank]
            for i in range(8):
                v = values[i]
                if written[i] != v:
                    knobs[i].buffer[:] = v
                    written[i] = v
                wrote = pulses[i].fill_changed(pads[i].buffer)
                if bank == p_bank and (wrote or self._w_pad_bank != p_bank):
                    copy_into(self.pad_outs[i].buffer, pads[i].buffer)
        self._w_pad_bank = p_bank
        values = self._knob_values[k_bank]
        for i in range(8):
            v = values[i]
            if live_k[i] != v:
                self.knob_outs[i].buffer[:] = v
                live_k[i] = v
