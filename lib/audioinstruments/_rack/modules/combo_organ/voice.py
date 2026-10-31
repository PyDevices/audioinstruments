# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""ComboOrgan voice: the key's footages summed into one table, plus the mixture's fifth and third.

A divider organ's 16', 8', 4', 2' and 1' are octaves of each other, so every
one of them is a whole harmonic of the 16' pitch. The voice sums the drawn
ones, each a band-limited square at its drawbar's level, into one single-cycle
table (``dsp.organ.DrawbarToneCore``) that a synthio note plays. The IV
mixture's 2 2/3' and 1 3/5' are not whole harmonics in equal temperament, so
each is a square of its own, a second and a third note in the same
synthesizer. One node plays the whole key, whatever is drawn.

The table is rebuilt only when the key or a drawbar moves, from squares made
once for every three keys. Each keeps only the harmonics that stay under
Nyquist across its three keys, so the top octave doesn't alias, and rolls
them off toward Nyquist as a divider's square does. Near the top of the keyboard each mixture pitch folds
back an octave, so none goes above MIDI 108.

When the bass section is on and the key lies in the lowest octave (C2 to B2),
the voice plays 16' and 8' and sends them to the bass bus instead of the
manual's.

The tone runs 256 frames late (a synthio note through a ``ChunkedBridge``),
and the key's contacts, a 3 ms ramp each way, are as late as it is.
"""

import math

import synthio

from ...core.jack import SignalType
from ...core.module import Module
from ...core.signal import (
    clear_buffer,
    copy_into,
    create_buffer,
    create_int16_buffer,
    pitch_to_frequency,
    scale,
    to_int16,
)
from ...dsp.organ import DrawbarToneCore
from .._util import jack_signal

#: The highest bass key, as a MIDI note: B2 at 8'.
BASS_TOP = 59

#: Each footage's level on its bus: a square of +-0.075 (a +-0.5 square at
#: 0.15). Forty-nine keys add on one bus, and the tone filters take their
#: input at a node's int16 scale (rails at +-2.0), so one key is kept small.
FOOTAGE_LEVEL = 0.075

#: The octave footages as harmonics of the 16' pitch: 16', 8', 4', 2', 1'.
OCTAVES = (1, 2, 4, 8, 16)
#: The mixture's octave pitches (2' and 1'): harmonic of 16', semitones above 8'.
MIXTURE_OCTAVES = ((8, 24), (16, 36))
#: Semitones above 8' of the mixture's fifth (2 2/3') and third (1 3/5').
MIXTURE_ET = (19, 28)
#: Each of the mixture's four pitches sounds at a quarter of its drawbar.
MIXTURE_SHARE = 0.25
#: No mixture pitch rises above this MIDI note; past it, it folds an octave.
TOP_PITCH = 108

#: The highest harmonic a square keeps, in Hz, at the top key of its band:
#: the band's lowest key keeps harmonics to about 18.5 kHz, and its top key
#: bent up two semitones with the vibrato on top stays about at Nyquist.
FMAX = 20800.0
#: Keys share their tables in bands this many semitones wide.
BAND = 3
#: The table's scale: a partial at level 1.0 is this much of the bridge's
#: unit, so all five footages and both ranks drawn stay under its rails.
TABLE_LEVEL = 0.25

#: A divider's square rolls off toward Nyquist: each harmonic's level against
#: an ideal square's, every 1 kHz from 0 to 24 kHz at 48 kHz.
ROLLOFF = (
    1.0,
    0.998,
    0.994,
    0.987,
    0.976,
    0.963,
    0.947,
    0.928,
    0.906,
    0.88,
    0.851,
    0.819,
    0.784,
    0.744,
    0.701,
    0.654,
    0.602,
    0.546,
    0.485,
    0.419,
    0.347,
    0.269,
    0.185,
    0.094,
    0.005,
)

#: synthio plays a full-scale table at half the bridge's unit.
SYNTH_SCALE = 0.5

#: The tone tables' length. synthio plays a table without interpolating, and
#: its steps add noise between the harmonics: 256 left it 25 dB under them
#: at middle C, 1024 keeps it 36 dB or more under at every key.
TONE_LEN = 1024

#: The squares are kept as int16, a quarter of the float tables' memory: a
#: square's 1.0 is this many counts (its Gibbs peak, about 1.18, still fits).
PARTIAL_UNIT = 16384.0

#: The bank the voices being built share: the patch sets it while it builds
#: them, and a voice built on its own makes its own.
building = None


def _band_hz(note):
    """The 8' pitches of the top and middle keys in ``note``'s band, in Hz."""
    note = 36 if note < 36 else (TOP_PITCH if note > TOP_PITCH else note)
    top = 36 + ((note - 36) // BAND) * BAND + BAND - 1
    return 440.0 * 2.0 ** ((top - 69) / 12.0), 440.0 * 2.0 ** ((top - 1 - 69) / 12.0)


def _rolloff(hz):
    """The divider's level at ``hz`` (48 kHz), from :data:`ROLLOFF`."""
    x = hz / 1000.0
    i = int(x)
    if i >= len(ROLLOFF) - 1:
        return ROLLOFF[-1]
    return ROLLOFF[i] + (ROLLOFF[i + 1] - ROLLOFF[i]) * (x - i)


def _count(f, limit=None):
    """How many odd harmonics of a square at ``f`` Hz stay under FMAX (and ``limit``)."""
    kmax = int(FMAX / f) if f > 0.0 else 1
    if limit is not None and kmax > limit:
        kmax = limit
    return max(1, (kmax + 1) // 2)


def footage_key(note, h):
    """Footage ``h`` (a harmonic of the 16' pitch) on ``note``, band-limited for its band
    and rolled off as at the band's middle."""
    top, mid = _band_hz(note)
    return (h, _count(h * top * 0.5, limit=(TONE_LEN // 2 - 1) // h), int(h * mid * 0.5))


def _every_key():
    """Every footage key a key from MIDI 36 to 108 can ask for."""
    keys = []
    for note in range(36, TOP_PITCH + 1, BAND):
        for h in OCTAVES:
            k = footage_key(note, h)
            if k not in keys:
                keys.append(k)
    return keys


class ToneBank:
    """The squares one organ's voices share: every footage's, for every band of
    keys, and every mixture rank's, all made when the bank is."""

    def __init__(self):
        self._sine = [math.sin(2.0 * math.pi * i / TONE_LEN) for i in range(TONE_LEN)]
        self.squares = {}
        self.keys = _every_key()
        for key in self.keys:
            self.partial(key)
        self.ranks = {}
        for note in range(36, TOP_PITCH + 1):
            key_hz = 440.0 * 2.0 ** ((note - 69) / 12.0)
            for semis in MIXTURE_ET:
                while note + semis > TOP_PITCH:
                    semis -= 12
                self._rank_table(_count(key_hz * 2.0 ** (semis / 12.0)))
        self._sine = None

    def partial(self, key):
        """The partial ``DrawbarToneCore`` sums for a footage key (see :func:`footage_key`)."""
        table = self.squares.get(key)
        if table is None:
            table = self._square(key[0], key[1], key[2])
            self.squares[key] = table
        return table

    def rank(self, hz):
        """The int16 square a mixture rank plays at ``hz``, band-limited (a key
        outside MIDI 36 to 108 takes the nearest the bank holds)."""
        count = _count(hz)
        table = self.ranks.get(count)
        if table is None:
            table = self.ranks[max(self.ranks) if count > max(self.ranks) else min(self.ranks)]
        return table

    def _rank_table(self, count):
        if count in self.ranks:
            return
        tmp = create_buffer(TONE_LEN)
        scaled = create_buffer(TONE_LEN)
        # rolled off as at the top of the pitches that share this count
        copy_into(scaled, self._square(1, count, int(FMAX / (2 * count - 1))))
        scale(scaled, TABLE_LEVEL / PARTIAL_UNIT)
        table = create_int16_buffer(TONE_LEN)
        to_int16(table, scaled, tmp)
        self.ranks[count] = table

    def _square(self, h, count, f1):
        """An int16 table holding ``h`` cycles of a square of ``count`` odd harmonics,
        :data:`PARTIAL_UNIT` counts high, each harmonic rolled off as a divider's
        square at ``f1`` Hz would be."""
        n = TONE_LEN
        sine = self._sine
        table = create_int16_buffer(n)
        weights = [_rolloff(k * f1) * 4.0 / (math.pi * k) for k in range(1, 2 * count, 2)]
        # One cycle is ``period`` long. A square's odd harmonics make it the same
        # either side of its quarter and negated in its second half, so only a
        # quarter is summed.
        period = n // h
        half = period // 2
        for i in range(period // 4 + 1):
            s = 0.0
            for j in range(count):
                s += sine[(h * (2 * j + 1) * i) % n] * weights[j]
            v = int(s * PARTIAL_UNIT + (0.5 if s >= 0.0 else -0.5))
            table[i] = v
            table[half - i] = v
            table[half + i] = -v
            table[(period - i) % period] = -v
        for c in range(1, h):
            for i in range(period):
                table[c * period + i] = table[i]
        return table


def _db_level(val):
    """Drawbar position 0 to 8 as linear amplitude: 8 is 1.0, 0 is 0.0, about 3 dB a step."""
    if val <= 0.0:
        return 0.0
    if val >= 8.0:
        return 1.0
    return 10.0 ** ((val - 8.0) * 3.0 / 20.0)


def _seed(text):
    """A per-voice seed from the module's id."""
    h = 5381
    for ch in text:
        h = (h * 33 + ord(ch)) & 0xFFFF
    return h


class ComboOrganVoice(Module):
    """One voice of the divide-down transistor combo organ."""

    NAME = "ComboOrganVoice"
    DISPLAY_NAME = "ComboOrgan Voice"
    HP = 12

    def _build(self):
        self.bank = building if building is not None else ToneBank()
        self._make_core(self.block_size)

        cv, gate, audio = SignalType.CV, SignalType.GATE, SignalType.AUDIO
        self.pitch_in = self.add_input("pitch", "Pitch", cv)
        self.gate_in = self.add_input("gate", "Gate", gate)
        self.note_in = self.add_input("note", "Note", cv)
        self.vibrato_in = self.add_input("vibrato", "Vibrato CV", cv)

        self.manual_out = self.add_output("manual", "Manual", audio)
        self.bass_out = self.add_output("bass", "Bass", audio)
        self.audio_out = self.add_output("out", "Audio Out", audio)

        # drawbar positions, 0 to 8; the patch sets them
        self.add_param("db16", "Drawbar 16'", default=0.0, min_val=0.0, max_val=8.0)
        self.add_param("db8", "Drawbar 8'", default=8.0, min_val=0.0, max_val=8.0)
        self.add_param("db4", "Drawbar 4'", default=6.0, min_val=0.0, max_val=8.0)
        self.add_param("db_iv", "Drawbar IV", default=4.0, min_val=0.0, max_val=8.0)
        self.add_param("bass", "Bass Active", default=0.0)
        self.add_scratch("_tmp")

    def _make_core(self, n):
        self.core = DrawbarToneCore(
            self.sample_rate,
            n,
            harmonics=self.bank.keys,
            partial=self.bank.partial,
            base_ratio=0.5,
            level=TABLE_LEVEL,
            table_len=TONE_LEN,
        )
        self.ranks = [
            synthio.Note(440.0, waveform=self.bank.rank(440.0), amplitude=0.0) for _ in MIXTURE_ET
        ]
        for rank in self.ranks:
            self.core.synth.press(rank)
        self._rank_hz = [0.0] * len(MIXTURE_ET)
        self._rank_ratio = [1.0] * len(MIXTURE_ET)
        self._rank_count = [0] * len(MIXTURE_ET)
        self._levels = [0.0] * len(OCTAVES)
        self._harms = [(1, 1, 0)] * len(OCTAVES)
        self._key = None
        self._bass_key = False
        self._scattered = False
        # blocks after the key goes up until the late contacts have closed
        self._tail = DrawbarToneCore.LATENCY_FRAMES // n + 2
        self._quiet = self._tail + 1
        self._live = True
        self._gain = FOOTAGE_LEVEL / (TABLE_LEVEL * SYNTH_SCALE)

    def set_block_size(self, block_size):
        super().set_block_size(block_size)
        self._make_core(block_size)

    def reset(self):
        self.core.reset()
        self._key = None
        self._quiet = self._tail + 1

    def _scatter(self, n):
        """Put each voice's notes at a distinct phase before its first key."""
        hz = 50.0 + _seed(self.id) % 997
        self.ranks[0].frequency = hz * 1.5
        self.ranks[1].frequency = hz * 2.5
        for _ in range(DrawbarToneCore.LATENCY_FRAMES // n):
            self.core.render(hz, 0.0, self._tmp)
        self._scattered = True

    def _register(self, note, bass, p):
        """The table and the ranks for ``note`` with the drawbars as they are."""
        levels = self._levels
        harms = self._harms
        for i in range(len(OCTAVES)):
            levels[i] = 0.0
            harms[i] = footage_key(note, OCTAVES[i])
        iv = 0.0
        if bass:
            levels[0] = 1.0 / PARTIAL_UNIT
            levels[1] = 1.0 / PARTIAL_UNIT
        else:
            levels[0] = _db_level(p["db16"]) / PARTIAL_UNIT
            levels[1] = _db_level(p["db8"]) / PARTIAL_UNIT
            levels[2] = _db_level(p["db4"]) / PARTIAL_UNIT
            iv = _db_level(p["db_iv"]) * MIXTURE_SHARE
            if iv > 0.0:
                for i in range(len(MIXTURE_OCTAVES)):
                    h, semis = MIXTURE_OCTAVES[i]
                    while note + semis > TOP_PITCH:
                        h //= 2
                        semis -= 12
                    levels[3 + i] = iv / PARTIAL_UNIT
                    harms[3 + i] = footage_key(note, h)
        self.core.set_levels(levels, harms)

        key_hz = 440.0 * 2.0 ** ((note - 69) / 12.0)
        for i in range(len(MIXTURE_ET)):
            rank = self.ranks[i]
            if iv > 0.0:
                semis = MIXTURE_ET[i]
                while note + semis > TOP_PITCH:
                    semis -= 12
                ratio = 2.0 ** (semis / 12.0)
                self._rank_ratio[i] = ratio
                count = _count(key_hz * ratio)
                if count != self._rank_count[i]:
                    self._rank_count[i] = count
                    rank.waveform = self.bank.rank(key_hz * ratio)
            if rank.amplitude != iv:
                rank.amplitude = iv
        self._bass_key = bass

    def _silence(self):
        if self._live:
            clear_buffer(self.manual_out.buffer)
            clear_buffer(self.bass_out.buffer)
            clear_buffer(self.audio_out.buffer)
            self._live = False

    def process(self, block_size):
        n = block_size
        if not self._scattered:
            self._scatter(n)

        gate_buf = jack_signal(self.gate_in)
        gate = 1.0 if gate_buf is not None and gate_buf[n - 1] > 0.5 else 0.0
        if gate > 0.0:
            self._quiet = 0
        else:
            self._quiet += 1
            if self._quiet > self._tail:
                self._silence()
                return

        # The key's pitch, bend and vibrato, once a block at its middle: synthio
        # takes one frequency a block, and the vibrato moves under 3 cents a block.
        mid = n >> 1
        pitch_buf = jack_signal(self.pitch_in)
        cv = float(pitch_buf[mid]) if pitch_buf is not None else 0.0
        note_buf = jack_signal(self.note_in)
        note_cv = float(note_buf[0]) if note_buf is not None else cv
        vib_buf = jack_signal(self.vibrato_in)
        if vib_buf is not None:
            cv += float(vib_buf[mid])
        hz = pitch_to_frequency(cv)

        p = self.params
        note = int(round(60.0 + note_cv * 120.0))
        bass = p["bass"] >= 0.5 and note <= BASS_TOP
        key = (note, bass, p["db16"], p["db8"], p["db4"], p["db_iv"])
        if key != self._key:
            self._key = key
            self._register(note, bass, p)

        for i in range(len(MIXTURE_ET)):
            f = hz * self._rank_ratio[i]
            if f != self._rank_hz[i]:
                self._rank_hz[i] = f
                self.ranks[i].frequency = f

        if self._bass_key:
            out = self.bass_out.buffer
            other = self.manual_out.buffer
        else:
            out = self.manual_out.buffer
            other = self.bass_out.buffer
        self.core.render(hz, gate, out)
        scale(out, self._gain)
        clear_buffer(other)
        copy_into(self.audio_out.buffer, out)
        self._live = True
