# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Poly MIDI to CV: MidiCV with a pitch, a gate, a velocity and a pressure jack per voice.

Everything MidiCV has is here unchanged, including its mono pitch, gate and
velocity (last-note priority). On top of that, each note takes a voice from a
``VoiceAllocator`` and that voice's ``pitch1``..``pitchN``, ``gate1``..``gateN``
and ``vel1``..``velN`` jacks carry it, and ``press1``..``pressN`` carry the
pressure on that voice's key (0 to 1): the larger of the key's poly pressure
and the channel pressure. A new note starts at no poly pressure; a released
key's pressure stays at its last value while the note dies away. ``note1``..``noteN`` are the same
pitches without the bend, for a voice that glides its note and adds the bend
back unslid. Patch voice 1's jacks into one copy of a synth, voice 2's into
the next, and the synth is polyphonic. ``VoicePool`` does that patching for
you.

When a note needs a voice that is still sounding, the module waits for the
voice to fade out, moves the voice's pitch and drops its gate while it is
silent, and then raises the gate on the new note: the steal takes three
blocks and makes no click. That only works when something fades the voice,
which ``VoicePool``'s mixer does; patched by hand a steal is a plain
retrigger one block late.

In mono mode (``VoicePool(..., mono=True)`` sets it) the allocator is out of
the way: no note is ever a steal, and the first ``unison`` voices (one unless
you ask for more) repeat the mono ``pitch``, ``note``, ``gate`` and ``vel``,
which carry the note stack, the priority and the legato of ``MidiCV``. With
more than one, each voice's pitch is offset by its share of the unison detune,
and the whole stack moves together on every key. The voices stay awake while
the gate is up.

Compiled to a graph (``vrack.core.graph``), the module's jacks are controls:
each carries one value a block, set only when it changes, so a held note
costs the graph nothing. The mono line is the same note stack in either form
(the priority, the legato and the retrigger are decided when a key goes down or
up, not once a sample), so a pool built mono compiles, and a pool compiled in
poly mode can be switched to mono and back while it plays (a chord or unison
patch). A portamento of the module's own ``glide`` moves in one step a block
rather than a curve. ``trig`` is a control that reads the share of the block the
2 ms pulse covers (1.0 for a whole block, less for the block it ends in), and a voice
that wants the pulse itself makes it from that.
"""

import math

from ..core.jack import SignalType
from ..core.poly import HELD, VoiceAllocator
from ..core.signal import copy_into
from .midi_cv import MidiCVModule

IDLE = 0
FADE = 1  # the stolen voice fades out this block
GAP = 2  # silent: gate low, pitch moves to the new note
START = 3  # the gate rises on the new note


class PolyMidiCV(MidiCVModule):
    NAME = "PolyMidiCV"
    DISPLAY_NAME = "Poly MIDI to CV"
    HP = 26

    def __init__(self, id_tag=None, sample_rate=48000, block_size=64, voices=8):
        self.max_voices = int(voices)
        if self.max_voices < 1:
            raise ValueError("voices must be at least 1")
        super().__init__(id_tag, sample_rate=sample_rate, block_size=block_size)

    def _build(self):
        super()._build()
        n = self.max_voices
        self.pitch_outs = [
            self.add_output("pitch%d" % (i + 1), "1V/Oct %d" % (i + 1), SignalType.CV)
            for i in range(n)
        ]
        self.gate_outs = [
            self.add_output("gate%d" % (i + 1), "Gate %d" % (i + 1), SignalType.GATE)
            for i in range(n)
        ]
        self.vel_outs = [
            self.add_output("vel%d" % (i + 1), "Velocity %d" % (i + 1), SignalType.CV)
            for i in range(n)
        ]
        self.note_outs = [
            self.add_output("note%d" % (i + 1), "1V/Oct %d, no bend" % (i + 1), SignalType.CV)
            for i in range(n)
        ]
        self.press_outs = [
            self.add_output("press%d" % (i + 1), "Pressure %d" % (i + 1), SignalType.CV)
            for i in range(n)
        ]
        self.alloc = VoiceAllocator(n)
        self.alloc.on_start = self._on_start
        self.alloc.on_release = self._on_release
        self.alloc.on_cut = self._on_cut
        #: Whatever fades and parks the voices; ``VoicePool`` sets it.
        self.listener = None
        self._mono = False
        self.reset_voices()

    @property
    def mono(self):
        """True for a monophonic pool: the first ``unison`` voices play the mono jacks."""
        return self._mono

    @mono.setter
    def mono(self, on):
        on = bool(on)
        if on == self._mono:
            return
        # Every note lets go: the voices fade out over a block and stop (the
        # gate falls once they are silent, as in a steal), and the next key
        # plays in the new mode.
        if on:
            self.alloc.reset()
            self.alloc.pedal = self._sustain_pedal
        else:
            for i in range(self._line):
                self._leave_line(i)
        self._release_all()
        self._line = 0
        self._mono = on

    def reset_voices(self):
        """Forget every pending note and drop every gate."""
        n = self.max_voices
        self._v_pitch = [0.0] * n
        self._v_vel = [0.0] * n
        self._v_gate = [False] * n
        #: The poly pressure the voice's jack shows (it follows a steal's fade like ``_v_vel``),
        #: and the live pressure of the key the voice is allocated to.
        self._v_press = [0.0] * n
        self._key_press = [0.0] * n
        self._phase = [IDLE] * n
        self._pending = [None] * n
        self._release_next = [False] * n
        #: How many voices the mono line played last block.
        self._line = 0
        self._forget_written()
        self._release_all()

    def _forget_written(self):
        n = self.max_voices
        self._w_pitch = [None] * n
        self._w_gate = [None] * n
        self._w_vel = [None] * n
        self._w_note = [None] * n
        self._w_press = [None] * n

    def set_block_size(self, block_size):
        super().set_block_size(block_size)
        if hasattr(self, "_w_pitch"):
            self._forget_written()

    def busy(self, voice):
        """True while a steal or a cut is still in flight on ``voice``."""
        return (
            self._phase[voice] != IDLE
            or self._pending[voice] is not None
            or self._release_next[voice]
        )

    # -- MIDI in -------------------------------------------------------------------

    @staticmethod
    def _key(channel, note, note_id):
        return (channel, note_id) if note_id >= 0 else (channel, note)

    def note_on(self, note, velocity=64, detune=0.0, channel=0, note_id=-1):
        if velocity == 0:
            self.note_off(note, channel, note_id)
            return
        super().note_on(note, velocity)
        if self._mono:
            self._wake_mono()
            return
        self.alloc.note_on(self._key(channel, note, note_id), note, velocity / 127.0, detune)

    def note_off(self, note, channel=0, note_id=-1):
        super().note_off(note)
        if not self._mono:
            self.alloc.note_off(self._key(channel, note, note_id))

    def all_notes_off(self):
        """Release every note, whatever the pedal says."""
        self._release_all()
        self.alloc.all_notes_off()

    def control_change(self, cc, value):
        super().control_change(cc, value)
        if cc == 64:
            self.alloc.sustain(value >= 64)
        elif cc in (120, 123):
            self.all_notes_off()

    def poly_pressure(self, note, value, channel=0, note_id=-1):
        """Pressure on one key, 0 to 127: only the voice playing that held key changes."""
        super().poly_pressure(note, value)
        if self._mono:
            return
        key = self._key(channel, note, note_id)
        alloc = self.alloc
        x = value / 127.0
        for v in range(self.max_voices):
            if alloc.key[v] == key and alloc.state[v] == HELD:
                self._key_press[v] = x
                if self._pending[v] is None:
                    self._v_press[v] = x

    def receive_message(self, status, data1, data2=0):
        msg_type = status & 0xF0
        channel = status & 0x0F
        if channel != 9 and msg_type in (0x90, 0x80):
            if msg_type == 0x90 and data2 > 0:
                self.note_on(data1, data2, channel=channel)
            else:
                self.note_off(data1, channel=channel)
            return
        if channel != 9 and msg_type == 0xA0:
            self.poly_pressure(data1, data2, channel)
            return
        super().receive_message(status, data1, data2)

    # -- the mono line -----------------------------------------------------------------

    def _line_size(self):
        """How many voices the mono line plays: the unison, within the voice count."""
        alloc = self.alloc
        return alloc.unison if alloc.unison < alloc.count else alloc.count

    def _side(self, i, k):
        """Voice ``i``'s place in a stack of ``k``, from -1 to 1 (0 for one voice)."""
        return 2.0 * i / (k - 1) - 1.0 if k > 1 else 0.0

    def _wake_mono(self):
        listener = self.listener
        alloc = self.alloc
        k = self._line_size()
        for i in range(k):
            alloc.gated[i] = True
            pan = self._side(i, k) * alloc.spread
            if listener is None:
                continue
            listener.wake(i)
            if self._phase[i] == IDLE:
                listener.open_channel(i, pan)
            else:
                # Still fading out from before the mode changed: it fades in
                # on the line once the gap is over.
                off = self._side(i, k) * alloc.detune / 120.0
                self._pending[i] = (self._target_pitch + off, self._velocity, pan, False)
                self._key_press[i] = self._key_pressure()
                self._release_next[i] = False

    def _leave_line(self, i):
        """Voice ``i`` stops playing the line: it fades out and parks."""
        k = self._line
        self._v_pitch[i] = self._current_pitch + self._side(i, k) * self.alloc.detune / 120.0
        self._v_vel[i] = self._velocity
        self._v_gate[i] = self._gate_active
        self._v_press[i] = self._key_pressure()
        self._w_pitch[i] = self._w_gate[i] = self._w_vel[i] = self._w_note[i] = None
        self._w_press[i] = None
        self.alloc.gated[i] = False
        self._pending[i] = None
        self._release_next[i] = False
        if self._phase[i] == IDLE:
            self._phase[i] = FADE

    def _mono_block(self, bend):
        alloc = self.alloc
        gated = alloc.gated
        k = self._line_size()
        if k < self._line:
            for i in range(k, self._line):
                self._leave_line(i)
        self._line = k
        phase = self._phase
        gate = self._gate_active
        detune = alloc.detune / 120.0
        for i in range(self.max_voices):
            if phase[i] != IDLE:
                self._advance(i)
                self._write(i, bend)
                continue
            if i >= k:
                continue
            gated[i] = gate
            copy_into(self.pitch_outs[i].buffer, self.pitch_out.buffer)
            copy_into(self.note_outs[i].buffer, self.note_out.buffer)
            copy_into(self.gate_outs[i].buffer, self.gate_out.buffer)
            copy_into(self.vel_outs[i].buffer, self.vel_out.buffer)
            copy_into(self.press_outs[i].buffer, self.press_out.buffer)
            off = self._side(i, k) * detune
            if off != 0.0:
                self.pitch_outs[i].buffer += off
                self.note_outs[i].buffer += off
            self._w_pitch[i] = self._w_gate[i] = self._w_vel[i] = self._w_note[i] = None
            self._w_press[i] = None

    # -- the allocator's decisions ---------------------------------------------------

    def _on_start(self, v, pitch, velocity, detune, pan, stolen):
        cv = (pitch + detune - 60.0) / 120.0
        listener = self.listener
        if listener is not None:
            listener.wake(v)
        self._key_press[v] = 0.0
        if stolen or self._phase[v] != IDLE:
            # The voice is sounding, or still finishing a steal: the new note
            # waits for the fade, and replaces any note that was waiting.
            self._pending[v] = (cv, velocity, pan, False)
            self._release_next[v] = False
            if self._phase[v] == IDLE:
                self._phase[v] = FADE
        else:
            self._v_pitch[v] = cv
            self._v_vel[v] = velocity
            self._v_press[v] = 0.0
            self._v_gate[v] = True
            if listener is not None:
                listener.open_channel(v, pan)

    def _on_release(self, v):
        pending = self._pending[v]
        if pending is not None:
            # The key came up before the note began: it still plays, one
            # block long, rather than being lost.
            self._pending[v] = (pending[0], pending[1], pending[2], True)
        elif self._phase[v] == IDLE:
            self._v_gate[v] = False

    def _on_cut(self, v):
        self._pending[v] = None
        self._release_next[v] = False
        if self._phase[v] == IDLE:
            self._phase[v] = FADE

    # -- block -----------------------------------------------------------------------

    def _advance(self, i):
        """One block of a steal or a cut on voice ``i``."""
        listener = self.listener
        phase = self._phase
        ph = phase[i]
        pending = self._pending[i]
        if ph == FADE:
            if listener is not None:
                listener.fade_out(i)
            phase[i] = GAP
        elif ph == GAP:
            self._v_gate[i] = False
            if pending is None:
                phase[i] = IDLE
                if listener is not None:
                    listener.park(i)
            else:
                self._v_pitch[i] = pending[0]
                self._v_vel[i] = pending[1]
                self._v_press[i] = self._key_press[i]
                phase[i] = START
        else:
            phase[i] = IDLE
            if pending is None:
                self._v_gate[i] = False
                if listener is not None:
                    listener.park(i)
            else:
                self._v_pitch[i] = pending[0]
                self._v_vel[i] = pending[1]
                self._v_press[i] = self._key_press[i]
                self._v_gate[i] = True
                self._pending[i] = None
                self._release_next[i] = pending[3]
                if listener is not None:
                    listener.fade_in(i, pending[2])

    def _write(self, i, bend):
        """Voice ``i``'s jacks from its note, written only when they change."""
        note = self._v_pitch[i]
        p = note + bend
        if p != self._w_pitch[i]:
            self.pitch_outs[i].buffer[:] = p
            self._w_pitch[i] = p
        if note != self._w_note[i]:
            self.note_outs[i].buffer[:] = note
            self._w_note[i] = note
        g = 1.0 if self._v_gate[i] else 0.0
        if g != self._w_gate[i]:
            self.gate_outs[i].buffer[:] = g
            self._w_gate[i] = g
        vel = self._v_vel[i]
        if vel != self._w_vel[i]:
            self.vel_outs[i].buffer[:] = vel
            self._w_vel[i] = vel
        pr = self._v_press[i]
        if self._chan_press > pr:
            pr = self._chan_press
        if pr != self._w_press[i]:
            self.press_outs[i].buffer[:] = pr
            self._w_press[i] = pr

    def _poly_block(self):
        """One block of every voice's steal and release bookkeeping."""
        phase = self._phase
        for i in range(self.max_voices):
            if phase[i] != IDLE:
                self._advance(i)
            elif self._release_next[i]:
                self._release_next[i] = False
                self._v_gate[i] = False

    def process(self, block_size):
        super().process(block_size)
        bend = self._pitch_bend * (self.params["bend_range"] / 12.0) * 0.1
        if self._mono:
            self._mono_block(bend)
            return
        self._poly_block()
        for i in range(self.max_voices):
            self._write(i, bend)

    # -- as a graph fragment ------------------------------------------------------------

    def fragment(self, f):
        n = self.max_voices
        self._c_pitch = [f.control(self.pitch_outs[i], 0.0) for i in range(n)]
        self._c_note = [f.control(self.note_outs[i], 0.0) for i in range(n)]
        self._c_gate = [f.control(self.gate_outs[i], 0.0) for i in range(n)]
        self._c_vel = [f.control(self.vel_outs[i], 0.0) for i in range(n)]
        self._c_press = [f.control(self.press_outs[i], 0.0) for i in range(n)]
        self._c_any_press = f.control(self.press_out, 0.0)
        self._c_any_gate = f.control(self.gate_out, 0.0)
        self._c_any_vel = f.control(self.vel_out, 0.0)
        self._c_legato = f.control(self.legato_out, 0.0)
        self._c_bend = f.control(self.bend_out, 0.0)
        self._c_mod = f.control(self.mod_out, 0.0)
        self._c_pedal = f.control(self.pedal_out, 0.0)
        self._c_trig = f.control(self.trig_out, 0.0)
        # the second line, for a voice with two oscillators on two keys (``"duo"``)
        self._c_pitch_hi = f.control(self.pitch_hi_out, 0.0)
        self._c_note_hi = f.control(self.note_hi_out, 0.0)
        f.before_run(self._graph_block)
        f.on_reset(self.reset)

    def _graph_block(self):
        bend = self._pitch_bend * (self.params["bend_range"] / 12.0) * 0.1
        if self._mono:
            self._graph_mono_block(bend)
        else:
            self._poly_block()
            for i in range(self.max_voices):
                self._graph_write(i, bend)
        # the second line never glides: the high key's pitch, or the line's
        self._c_note_hi.set(self._target_hi)
        self._c_pitch_hi.set(self._target_hi + bend)
        self._c_any_gate.set(1.0 if self._gate_active else 0.0)
        self._c_any_vel.set(self._velocity)
        self._c_any_press.set(self._pressure())
        self._c_legato.set(1.0 if self._legato else 0.0)
        self._c_bend.set(self._pitch_bend * 0.5)
        self._c_mod.set(self._mod_wheel)
        self._c_pedal.set(1.0 if self._sustain_pedal else 0.0)
        # the trig pulse, as a level for the blocks it covers: a voice that wants the pulse
        # itself starts one on the control's rise (see Mono101Voice)
        pulse = self._trig_pulse
        n = self.block_size
        self._c_trig.set(min(pulse.left, n) / float(n) if pulse.left > 0 else 0.0)
        pulse.left = max(0, pulse.left - n * self._fragment.blocks)

    def _graph_write(self, i, bend):
        """Voice ``i``'s controls from its own note."""
        note = self._v_pitch[i]
        self._c_pitch[i].set(note + bend)
        self._c_note[i].set(note)
        self._c_gate[i].set(1.0 if self._v_gate[i] else 0.0)
        self._c_vel[i].set(self._v_vel[i])
        pr = self._v_press[i]
        self._c_press[i].set(self._chan_press if self._chan_press > pr else pr)

    def _graph_mono_block(self, bend):
        """``_mono_block`` with the line's value in controls, not copied into jacks."""
        alloc = self.alloc
        gated = alloc.gated
        k = self._line_size()
        if k < self._line:
            for i in range(k, self._line):
                self._leave_line(i)
        self._line = k
        glide = self.params["glide"]
        if glide > 0.001 and self._current_pitch != self._target_pitch:
            coeff = math.exp(-1.0 / (glide * self.sample_rate * 0.1))
            target = self._target_pitch
            now = target + (self._current_pitch - target) * coeff**self.block_size
            self._current_pitch = target if abs(now - target) < 1e-7 else now
        else:
            self._current_pitch = self._target_pitch
        phase = self._phase
        gate = self._gate_active
        detune = alloc.detune / 120.0
        for i in range(self.max_voices):
            if phase[i] != IDLE:
                self._advance(i)
                self._graph_write(i, bend)
                continue
            if i >= k:
                continue
            gated[i] = gate
            off = self._side(i, k) * detune
            self._c_pitch[i].set(self._current_pitch + bend + off)
            self._c_note[i].set(self._current_pitch + off)
            self._c_gate[i].set(1.0 if gate else 0.0)
            self._c_vel[i].set(self._velocity)
            self._c_press[i].set(self._pressure())

    def reset(self):
        super().reset()
        self.alloc.reset()
        self.reset_voices()
        self._sustain_pedal = False

    def get_state(self):
        state = super().get_state()
        state["voices"] = self.max_voices
        return state
