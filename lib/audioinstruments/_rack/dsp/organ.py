# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Organ cores: a footage tone generator, key click, percussion, scanner vibrato, swell pedal.

An organ voice is a few pitches a key switches on together, each at a fixed
interval from the key (a footage: 8' is the key's own pitch, 16' an octave
under it, 4' an octave over it), each at a level a drawbar or a tab sets.
:class:`DrawbarToneCore` sums those pitches into one single-cycle table at a
base pitch every footage is a whole harmonic of, and synthio plays the table.
What each footage sounds like is the ``partial`` it is given: a tonewheel's is
a near-sine (:func:`sine_partial`); a divide-down organ's is a square or a
pulse, which is one more function of the same form that sums a few odd sines.
Which harmonic each footage plays on a given key (the foldback at the ends of
the keyboard) belongs to the organ, so the voice hands the core both the
levels and the harmonics.

A tonewheel organ has 91 wheels on one shaft, each in front of a pickup, so
every pitch is a near-sine that is always turning; a key closes nine contacts
that connect nine of them to the drawbars' busbars. The nine footages and the
harmonic each takes of the 16' pitch are in :data:`TONEWHEEL_FOOTAGES`;
:func:`tonewheel_harmonics` folds them at the keyboard's ends, as the organ
does because it has no wheels past its top and bottom.
"""

import array
import math

import audiobiquad
import audioecho
import synthio

from ..core.bridge import ChunkedBridge, NodeBridge, biquad_kwargs
from ..core.signal import (
    add,
    add_scaled,
    clear_buffer,
    copy_into,
    create_buffer,
    create_int16_buffer,
    scale,
    scaled_into,
    sub,
    to_int16,
)
from .blocks import Ramp, exp_segment

TWO_PI = 2.0 * math.pi
TABLE_LEN = 256

#: Drawbar positions 0 to 8 as levels: 8 is full, each step about 3 dB down, 0 off.
DRAWBAR_LEVELS = tuple([0.0] + [10.0 ** ((i - 8) * 3.0 / 20.0) for i in range(1, 9)])

#: The tonewheel organ's nine footages, in the panel's order, as harmonics of
#: the 16' pitch: 16', 5 1/3', 8', 4', 2 2/3', 2', 1 3/5', 1 1/3', 1'.
TONEWHEEL_FOOTAGES = (1, 3, 2, 4, 6, 8, 10, 12, 16)

#: Every harmonic a folded tonewheel footage can land on.
TONEWHEEL_HARMONICS = (1, 2, 3, 4, 5, 6, 8, 10, 12, 16)

#: The highest wheel, as a MIDI note: the 91st, F#8 (about 5.9 kHz), counting
#: the first as the 16' of the bottom key (MIDI 36 at 8').
TOP_WHEEL = 114
#: The 16' folds up an octave below this key: the bottom twelve keys, from MIDI 36.
LOW_FOLD_KEY = 48

# semitones from the 8' pitch to harmonic h of the 16' pitch, 12 * log2(h / 2)
_SEMITONES = {1: -12, 2: 0, 3: 7, 4: 12, 5: 16, 6: 19, 8: 24, 10: 28, 12: 31, 16: 36}


def tonewheel_harmonics(note, out=None):
    """The harmonic of the 16' pitch each of the nine footages plays on ``note``.

    A footage whose wheel would be past the top one (``TOP_WHEEL``) folds back
    an octave, again if it has to, so the top octaves do not go thin and
    shrill: the 1' stops rising from about F#5 and the 2' from about F#6. The
    16' folds up an octave on the bottom twelve keys. ``out`` is a list of
    nine to fill in place.
    """
    note = int(note)
    if out is None:
        out = [0] * 9
    for i in range(9):
        h = TONEWHEEL_FOOTAGES[i]
        while h > 2 and h % 2 == 0 and note + _SEMITONES[h] > TOP_WHEEL:
            h //= 2
        out[i] = h
    if note < LOW_FOLD_KEY:
        out[0] = 2
    return out


_PARTIALS = {}


def sine_partial(harmonic, length=TABLE_LEN):
    """One table holding ``harmonic`` cycles of a sine: a tonewheel's near-sine.

    Another organ's footage is another function of the same form (a
    band-limited square is the odd multiples of ``harmonic`` at 1/k, as many as
    fit under ``length // 2``). Tables are built once and shared by every voice.
    """
    key = ("sine", harmonic, length)
    table = _PARTIALS.get(key)
    if table is None:
        table = create_buffer(length)
        for i in range(length):
            table[i] = math.sin(TWO_PI * harmonic * i / length)
        _PARTIALS[key] = table
    return table


_SCRATCH = {}


class DrawbarToneCore:
    """One voice's footages, summed into a single-cycle table that synthio plays.

    ``harmonics`` lists every harmonic of the base pitch a footage may be asked
    to play (their partials are fetched once, here); ``partial(h)`` gives the
    table of one footage at harmonic ``h`` (:func:`sine_partial` by default);
    ``base_ratio`` is the table's pitch against the key's (0.5: the table is at
    16', so the 8' is its second harmonic); ``level`` scales the sum;
    ``table_len`` is the table's length, which every partial shares (synthio
    plays the table without interpolating, so a longer one sounds cleaner).

    :meth:`set_levels` rebuilds the table when a level or a harmonic changes,
    in buffers the core owns. :meth:`render` plays it through a
    ``ChunkedBridge``, so the tone trails the controls by 256 frames. The
    contacts (a 3 ms ramp each way) follow the gate 256 frames late too, which
    is when the tone at the key's pitch arrives, so a note never begins on the
    voice's previous pitch. A key that comes down while the voice still sounds
    (a steal, once the pool has faded it) cuts what was left of the old note.
    """

    LATENCY_FRAMES = ChunkedBridge.FRAMES

    def __init__(
        self,
        sample_rate,
        block_size,
        harmonics=TONEWHEEL_HARMONICS,
        partial=sine_partial,
        base_ratio=0.5,
        level=0.12,
        table_len=TABLE_LEN,
    ):
        self.sample_rate = sample_rate
        self.block_size = block_size
        self.base_ratio = base_ratio
        self.level = level
        self._partials = {h: partial(h) for h in harmonics}
        self._table_i16 = create_int16_buffer(table_len)
        # the float table and its scratch serve only while one is rebuilt, so
        # every core of a length shares them
        scratch = _SCRATCH.get(table_len)
        if scratch is None:
            scratch = (create_buffer(table_len), create_buffer(table_len))
            _SCRATCH[table_len] = scratch
        self._table_f, self._tmp = scratch
        self._silence = create_buffer(block_size)
        self._raw = create_buffer(block_size)

        self.synth = synthio.Synthesizer(sample_rate=sample_rate, channel_count=1)
        self.note = synthio.Note(220.0, waveform=self._table_i16)
        self.synth.press(self.note)
        self.bridge = ChunkedBridge(block_size, sample_rate).chain(self.synth)

        self._ramp_step = 1.0 / max(1, int(0.003 * sample_rate))
        self._gate_ramp = 0.0
        self._last_gate = 0.0
        # the gate, ``_steps`` blocks late: one entry a block
        self._steps = max(1, ChunkedBridge.FRAMES // block_size)
        self._delay = [0.0] * self._steps
        self._at = 0
        #: The contacts as heard: the gate as late as the tone (1.0 or 0.0).
        self.keyed = 0.0
        self._levels = [-1.0] * 16
        self._harmonics = [0] * 16
        self._count = 0
        self._last_freq = 0.0

    def set_levels(self, levels, harmonics):
        """Footage ``i`` at linear level ``levels[i]`` on harmonic ``harmonics[i]``.

        Both are sequences of the same length, at most 16. The table is
        rebuilt only when one of them moved."""
        n = len(levels)
        same = n == self._count
        if same:
            for i in range(n):
                if levels[i] != self._levels[i] or harmonics[i] != self._harmonics[i]:
                    same = False
                    break
        if same:
            return
        self._count = n
        table = self._table_f
        clear_buffer(table)
        for i in range(n):
            level = levels[i]
            h = harmonics[i]
            self._levels[i] = level
            self._harmonics[i] = h
            if level > 0.0:
                add_scaled(table, self._partials[h], level, self._tmp)
        scale(table, self.level)
        to_int16(self._table_i16, table, self._tmp)

    def render(self, pitch_hz, gate, out, extra=None):
        """One block of the voice at ``pitch_hz`` (the key's 8' pitch), the
        contacts following ``gate``. ``extra``, when given, is a block keyed by
        the contacts with the tone (the percussion)."""
        f = pitch_hz * self.base_ratio
        f = 10.0 if f < 10.0 else (16000.0 if f > 16000.0 else f)
        if f != self._last_freq:
            self._last_freq = f
            self.note.frequency = f

        g_now = 1.0 if gate > 0.0 else 0.0
        # A key down on a voice still sounding: the pool has faded it, so what
        # is left of the old note is cut rather than played late.
        rise = g_now > 0.0 and self._last_gate <= 0.0
        if rise and (self.keyed > 0.0 or self._gate_ramp > 0.0):
            for i in range(self._steps):
                self._delay[i] = 0.0
            self._gate_ramp = 0.0
        self._last_gate = g_now
        at = self._at
        late = self._delay[at]
        self._delay[at] = g_now
        self._at = (at + 1) % self._steps
        self.keyed = late

        self.bridge.process(self._silence, self._raw)

        g = self._gate_ramp
        if late <= 0.0 and g <= 0.0:
            clear_buffer(out)
            return
        copy_into(out, self._raw)
        if extra is not None:
            add(out, extra)
        if late > 0.0 and g >= 1.0:
            return
        step = self._ramp_step
        for i in range(self.block_size):
            if late > 0.0:
                g = g + step if g + step < 1.0 else 1.0
            else:
                g = g - step if g - step > 0.0 else 0.0
            out[i] *= g
        self._gate_ramp = g

    def reset(self):
        self.bridge.reset()
        self._gate_ramp = 0.0
        self._last_gate = 0.0
        self.keyed = 0.0
        for i in range(self._steps):
            self._delay[i] = 0.0


# Key click: band-limited noise with a contact's bounce, made once.
CLICK_DOWN_LEN = 192  # 4 ms at 48 kHz
CLICK_UP_LEN = 96  # 2 ms
CLICK_DOWN = create_buffer(CLICK_DOWN_LEN)
CLICK_UP = create_buffer(CLICK_UP_LEN)


def _fill_click(buf, decay, bounces, level, seed):
    n = len(buf)
    prev = 0.0
    for i in range(n):
        seed = (seed * 1103515245 + 12345) & 0x7FFFFFFF
        noise = (seed / 0x7FFFFFFF) * 2.0 - 1.0
        prev = 0.5 * (prev + noise)  # a gentle low-pass: contacts, not hiss
        t = i / n
        env = math.exp(-decay * t) * (1.0 + 0.5 * math.sin(TWO_PI * bounces * t))
        buf[i] = prev * env * level
    return seed


_fill_click(CLICK_UP, 8.0, 2.0, 0.5, _fill_click(CLICK_DOWN, 6.0, 3.0, 1.0, 12345))


class KeyClickCore:
    """A short burst of band-limited noise and contact bounce when the key goes
    down, and a quieter, shorter one when it comes up, added to ``out``."""

    #: The click's scale at level 10.
    LEVEL = 0.05

    def __init__(self, sample_rate, block_size):
        self.sample_rate = sample_rate
        self.block_size = block_size
        self._last_gate = 0.0
        self._pos = 0
        self._buf = None

    def render(self, gate, click_level, out):
        g = 1.0 if gate > 0.0 else 0.0
        if g != self._last_gate:
            self._buf = CLICK_DOWN if g > 0.0 else CLICK_UP
            self._pos = 0
        self._last_gate = g
        buf = self._buf
        if buf is None:
            return
        level = (max(0.0, min(10.0, click_level)) / 10.0) * self.LEVEL
        pos = self._pos
        stop = min(self.block_size, len(buf) - pos)
        if level > 0.0:
            for i in range(stop):
                out[i] += buf[pos + i] * level
        pos += stop
        if pos >= len(buf):
            self._buf = None
        self._pos = pos

    def reset(self):
        self._last_gate = 0.0
        self._pos = 0
        self._buf = None


#: Percussion decay, seconds to fall 60 dB: fast, slow.
PERC_DECAY_S = (0.65, 2.0)


class PercussionCore:
    """A decaying envelope the whole manual shares, single-trigger.

    It fires when the manual's gate rises with nothing held, so a note played
    legato over another gets none and a player re-attacks for it. It falls
    60 dB in ``PERC_DECAY_S`` (fast or slow); soft is 6 dB under normal.
    """

    def __init__(self, sample_rate, block_size):
        self.sample_rate = sample_rate
        self.block_size = block_size
        self._last_gate = 0.0
        self._env = 0.0
        self._ramp = Ramp(block_size)
        self._coeff_fast = math.exp(-6.91 / (PERC_DECAY_S[0] * sample_rate))
        self._coeff_slow = math.exp(-6.91 / (PERC_DECAY_S[1] * sample_rate))

    def render(self, manual_gate, on, soft, fast, out):
        """One block of the envelope into ``out``."""
        g = 1.0 if manual_gate > 0.0 else 0.0
        fresh = g > 0.0 and self._last_gate <= 0.0
        self._last_gate = g
        if not on:
            self._env = 0.0
            clear_buffer(out)
            return
        if fresh:
            self._env = 1.0
        if self._env < 1e-4:
            self._env = 0.0
            clear_buffer(out)
            return
        coeff = self._coeff_fast if fast else self._coeff_slow
        self._env = exp_segment(out, self._env, 0.0, coeff, self._ramp)
        if soft:
            scale(out, 0.5)

    def reset(self):
        self._last_gate = 0.0
        self._env = 0.0


#: The scanner's sweep: a sine, one period a table, Q15.
SCANNER_SHAPE = array.array(
    "h", [int(round(math.sin(TWO_PI * i / TABLE_LEN) * 32767.0)) for i in range(TABLE_LEN)]
)
#: The scanner turns with the tonewheel motor, so its rate is fixed.
SCANNER_HZ = 6.9
#: Peak delay swing in ms for depths 1 to 3. A sine sweep of peak d at rate r
#: moves the pitch by 2 pi r d either way, so these are about 30, 60 and 100
#: cents peak to peak at 6.9 Hz.
SCANNER_DEPTHS_MS = (0.20, 0.40, 0.68)
SCANNER_CENTRE_MS = 1.5


class ScannerVibratoCore:
    """A scanner vibrato and chorus on one ``audioecho.FeedbackDelay`` swept per sample.

    ``set(on, depth, chorus)``: ``depth`` 1 to 3 picks ``SCANNER_DEPTHS_MS``.
    Vibrato is the swept line alone; chorus is the swept line and the dry
    signal at half level each, so a low note, where the two agree, keeps its
    level. Off, the dry signal passes. Mono in, mono out, 256 frames late (the
    bridge) in every mode.
    """

    LATENCY_FRAMES = ChunkedBridge.FRAMES

    #: FeedbackDelay's ``mix``: 0 is dry alone, 1 dry plus wet, 2 wet alone.
    DRY, BOTH, WET = 0.0, 1.0, 2.0

    def __init__(self, sample_rate, block_size):
        self.sample_rate = sample_rate
        self.block_size = block_size
        self.line = audioecho.FeedbackDelay(
            sample_rate=sample_rate,
            channel_count=1,
            max_delay_ms=20.0,
            delay_ms=SCANNER_CENTRE_MS,
            feedback=0.0,
            mix=self.DRY,
            wow_hz=SCANNER_HZ,
            wow_depth_ms=0.0,
            wow_shape=SCANNER_SHAPE,
        )
        self.bridge = ChunkedBridge(block_size, sample_rate).chain(self.line)
        self._in = create_buffer(block_size)
        self._on = None
        self._depth = None
        self._chorus = None
        self._gain = 1.0

    def set(self, on, depth, chorus):
        on = bool(on)
        if on == self._on and depth == self._depth and chorus == self._chorus:
            return
        self._on, self._depth, self._chorus = on, depth, chorus
        if not on:
            self._gain = 1.0
            self.line.set(wow_depth_ms=0.0, mix=self.DRY)
            return
        d = SCANNER_DEPTHS_MS[max(1, min(3, int(depth))) - 1]
        self._gain = 0.5 if chorus else 1.0
        self.line.set(wow_depth_ms=d, mix=self.BOTH if chorus else self.WET)

    def render(self, src, dst):
        if self._gain != 1.0:
            scaled_into(self._in, src, self._gain)
            self.bridge.process(self._in, dst)
        else:
            self.bridge.process(src, dst)

    def reset(self):
        self.line.clear()
        self.bridge.reset()


#: The swell pedal's bass cut: this share of everything under ``SWELL_BASS_HZ``
#: goes at the bottom of the pedal.
SWELL_BASS_HZ = 150.0
SWELL_BASS_CUT = 0.5


class SwellPedalCore:
    """An organ's expression pedal: the level, and a little less bass as it closes.

    ``render(src, dst, pedal)`` with ``pedal`` 0 (closed) to 1 (open). The
    level follows the pedal squared, and the low end under ``SWELL_BASS_HZ``
    falls by up to ``SWELL_BASS_CUT`` of itself as the pedal closes. Open, it
    is a wire.
    """

    def __init__(self, sample_rate, block_size):
        # an audiobiquad node, which settles to zero when the organ stops: a
        # synthio biquad this low can hold a DC step of hundreds of counts
        node = audiobiquad.Biquad(
            mode=audiobiquad.LOW_PASS,
            frequency=SWELL_BASS_HZ,
            Q=0.7071,
            sample_rate=sample_rate,
            channel_count=1,
            **biquad_kwargs(block_size),
        )
        self.low = NodeBridge(block_size, sample_rate).chain(node)
        self._low = create_buffer(block_size)

    def render(self, src, dst, pedal):
        pedal = 0.0 if pedal < 0.0 else (1.0 if pedal > 1.0 else pedal)
        self.low.process(src, self._low)  # always running, so a move is smooth
        copy_into(dst, src)
        if pedal >= 1.0:
            return
        scale(self._low, SWELL_BASS_CUT * (1.0 - pedal))
        sub(dst, self._low)
        scale(dst, pedal * pedal)

    def reset(self):
        self.low.reset()
