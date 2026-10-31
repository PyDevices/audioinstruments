# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""A SoundFont 2 bank as an instrument: every melodic preset under one
program change, played through `audiosampler`.

    inst = audioinstruments._rack.adapter.create(48000, voice="soundfont", bank="/sd/FluidR3_GM.sf2")
    inst.program_change(48)        # Strings in bank 0
    inst.note_on(60, 100)

Patch n is Program Change n in the bank's melodic bank (bank 0 for a General
MIDI set), named from the bank; a program the bank lacks is a silent patch
so the numbers stay MIDI's. Bank Select (CC 0 and CC 32) picks another
melodic bank for the next program change, falling back to bank 0 when the
bank has no such preset, as a GM player does. The kit, bank 128, is the
`soundfont_drums` instrument.

The bank is found in this order: the `bank` option to `create()` (a path, or
an open `SoundFont`), the `SOUNDFONT` environment variable, then the
first `.sf2` in `~/soundfonts/` (`%USERPROFILE%\\soundfonts` on Windows). The
hydra is read at `create()`; samples are read from the file the first time a
note needs them and kept, so a 148 MB bank costs only the presets you play.
Instruments made from the same path share the open bank and its samples.

The samples kept are bounded: `CACHE_BYTES` of them (8 MB on a board, 64 MB
on a desktop), or what `open_bank(path, cache_bytes=...)` asks for. They
live in an arena of a few large buffers, taken once (when the bound is set,
else at the first note) and never given back, so a long, dense piece plays
in fixed memory and leaves the rest of the heap whole: on a board, hundreds
of samples allocated and freed one by one break the heap into pieces too
small for the next one, however much is free. Each sample is read from the
file straight into the arena, and voices play views of it. When the arena
is full the oldest samples read are let go, and read again if a note wants
them later. A voice still playing a sample keeps it, and so does a stopped
note's fade for `TAIL_MS`. A note whose sample can't fit beside the ones
sounding reads it outside the arena, just for that note. Where audiosampler
has `SampleBuffer`, the arena's buffers sit outside the collected heap, so
a `gc.collect()` doesn't read megabytes of samples looking for pointers.

Attenuation. A region's `initialAttenuation` is applied scaled by
`ATTENUATION_SCALE` (0.4): the banks in circulation were voiced on players
that scale it so, and played per the specification's centibels they come out
far quieter and more uneven between presets than their authors heard. The
one constant is the whole convention. Velocity is a square law on top.

Five macros: Volume, Attack and Release (scaling the bank's own envelope,
64 is as written), Tune (bipolar, two semitones each way) and Pan. Pan is
bipolar too: 64 is centre, 0 hard left, 127 hard right. It is an offset
added to each region's own pan, so a stereo pair keeps its spread around
the new centre, clamped at the edges. Moving it re-pans the voices already
sounding, with the engine's ramp, and Control Change 10 on the instrument
drives it, as it does Bank Select; the other GM controllers are the
host's. A program change puts every macro back to the patch's defaults,
Pan at centre.

Thirty-two engine voices, one per region a note resolves to (a stereo pair
is two). A new note with every voice busy steals the oldest releasing voice,
then the oldest. A note in an exclusive class stops the sounding notes of
that class first, which is how the closed hi-hat chokes the open one. Note
off releases a voice through its own release stage; loop mode 3 lets the
sample run on to its end.

Several instruments can share one pool of voices instead, as a General MIDI
module's sixteen parts do: make a `Voices`, pass it as `voice_pool=` to
every `create()`, and play its `output` once. A busy part then takes the voices
an idle one isn't using, a new note anywhere steals the oldest releasing
voice in the whole pool, and there is one sampler to render rather than one
per instrument and a mixer to sum them.

Pure Python over the reader and the engine, so it imports on MicroPython;
`audiosampler` is imported when an instrument is created.
"""

import os
import sys

try:
    from time import ticks_diff, ticks_ms
except ImportError:  # CPython
    import time as _time

    def ticks_ms():
        return int(_time.monotonic() * 1000)

    def ticks_diff(a, b):
        return a - b


from ._component import (
    EVENT_CONTROL_CHANGE,
    EVENT_NOTE_OFF,
    EVENT_NOTE_ON,
    EVENT_PARAMETER,
    EVENT_PITCH_BEND,
    Instrument,
    key_of,
)
from ._sf2 import SoundFont as _SoundFont

try:
    from audiopump import park as _park
    from audiopump import unpark as _unpark
except ImportError:  # no pump: every write goes straight to the engine
    _park = _unpark = None

try:
    from audiosampler import SampleBuffer as _SampleBuffer
except ImportError:  # an audiodsp from before it: the arena is bytearrays
    _SampleBuffer = None

NAME = "soundfont"
DISPLAY_NAME = "SoundFont"
CATEGORIES = ("Sampler",)
VERSION = "0.0.1"
VENDOR = "PyDevices"

MACRO_LABELS = ("Volume", "Attack", "Release", "Tune", "Pan")
MACRO_MODES = {
    0: "UNIPOLAR",
    1: "UNIPOLAR",
    2: "UNIPOLAR",
    3: "BIPOLAR",
    4: "BIPOLAR",
}

#: The macro values every patch carries: the bank's own envelope (Attack and
#: Release at 64 scale it by 1.0), no detune, centre pan, volume a little
#: under full.
DEFAULT_MACROS = (100, 64, 64, 64, 64)

#: Patch 0 as a literal for the scanners; a live instrument's `patches` are
#: the bank's presets, built in `create()`.
PATCHES = {
    0: ("Program 0", (100, 64, 64, 64, 64)),
}

#: The Pan macro's index, for hosts that drive it by number.
PAN_MACRO = 4

#: The power `initialAttenuation`'s linear gain is raised to. See the module
#: docstring.
ATTENUATION_SCALE = 0.4

#: Engine voices. A note is one voice per region, so this is 32 mono notes
#: or 16 stereo ones.
MAX_VOICES = 32

#: The percussion bank, by the specification.
PERCUSSION_BANK = 128

#: The drum pads, keys 36 to 51: the sixteen a pad controller sends. A kit
#: answers each of them, with the nearest voice it has when a pad has none.
PAD_LOW, PAD_HIGH = 36, 51

#: A voice's state in its slot: the key is down, the key is up and the
#: release is sounding, or faded to silence for the reserve.
HELD, RELEASING, FADED = 0, 1, 2

#: Voices a shared pool has unless told otherwise: what a General MIDI
#: module of the SC-88's generation has, and the engine's ceiling.
SHARED_VOICES = 64

#: Bytes of samples a bank keeps read from its file: 8 MB on a board, where
#: RAM is counted in tens of megabytes, 64 MB on a desktop.
CACHE_BYTES = (64 if sys.implementation.name == "cpython" else 8) * 1048576

#: The size of each of the arena's buffers, or the bank's largest sample
#: when that is bigger: a sample never straddles two. Small enough to find
#: room for in a heap that has been running a while.
SLAB_BYTES = 1048576

#: Milliseconds a sample stays in the arena after the voice playing it stops
#: or moves to another note: a stopped note fades out over 5 ms, still
#: reading it, and the audio is rendered a block or two ahead.
TAIL_MS = 100


def _slab(nbytes):
    """One of the arena's buffers: outside the collected heap where
    audiosampler can give one, so a gc.collect() never reads the samples,
    else a bytearray."""
    if _SampleBuffer is not None:
        try:
            return _SampleBuffer(nbytes)
        except MemoryError:
            pass
    return bytearray(nbytes)


#: Semitones of pitch bend at full deflection, either way.
BEND_RANGE = 2.0

_CC_BANK_MSB = 0
_CC_BANK_LSB = 32
_CC_PAN = 10
_CC_SUSTAIN = 64


def _bipolar(value0):
    """A bipolar macro's -1..1 from the 0..1 the event carries, with a
    centre detent: MIDI 64 is exactly 0 and 0 and 127 are the ends."""
    midi = value0 * 127.0
    if midi >= 64.0:
        return (midi - 64.0) / 63.0
    return (midi - 64.0) / 64.0


def _panned(region_pan, offset):
    pan = region_pan + offset
    if pan < -1.0:
        return -1.0
    if pan > 1.0:
        return 1.0
    return pan


# --- finding and sharing a bank --------------------------------------------


def _getenv(name):
    getenv = getattr(os, "getenv", None)
    if getenv is None:
        return None
    return getenv(name)


def find_bank(path=None):
    """The `.sf2` to play: `path` when given, else `$SOUNDFONT`, else the
    first `.sf2` in `~/soundfonts/`. Raises OSError naming all three when
    none of them yields a file."""
    if path:
        return path
    env = _getenv("SOUNDFONT")
    if env:
        return env
    home = _getenv("USERPROFILE") or _getenv("HOME") or ""
    folder = home + "/soundfonts"
    try:
        names = sorted(n for n in os.listdir(folder) if n.lower().endswith(".sf2"))
    except OSError:
        names = []
    if names:
        return folder + "/" + names[0]
    raise OSError(
        "no SoundFont found: pass bank=<path> to create(), set the "
        "SOUNDFONT environment variable, or put a .sf2 in %s" % folder
    )


class _Bank(object):
    """An open bank and the samples read from it, at most `cache_bytes` of
    them, in an arena of buffers taken once.

    `cached` is the bytes kept now; `reads` counts the samples read from
    the file and `evicted` the ones let go, so `reads` above the number of
    distinct samples played is the re-reading a small cache costs.
    `outside` counts the reads that found no room beside the samples
    sounding, and played from a buffer of their own, and `dropped` those
    the heap had no room for either, whose notes went without that sample
    rather than stop the music. `arena_bytes` is the
    arena's size once it is taken: less than `cache_bytes` for a bank whose
    samples are smaller, or a heap that couldn't give it all.
    """

    def __init__(self, font, cache_bytes=None):
        self.font = font
        self.samples = {}  # shdr index -> [offset, frames, index] in the arena
        self.presets = {}  # (bank, program) -> name
        for bank, program, name in font.presets():
            self.presets[(bank, program)] = name
        self._cache_bytes = CACHE_BYTES if cache_bytes is None else int(cache_bytes)
        self._slabs = None  # the arena's buffers, once taken
        self._frames = []  # a view of each in frames, for the voices
        self._bytes = []  # and in bytes, to read into
        self._unit = 1  # items of a frames view per frame: 2 where views can't cast
        self._slab = 0  # frames in each buffer
        self._order = []  # the samples kept, by offset
        self._head = 0  # where the next read goes, in frames across the arena
        self._held = {}  # voice -> shdr index it was handed last
        self._retired = None  # the last arena, while a voice may still read it
        self._tails = {}  # shdr index -> ticks_ms when a voice let go of it
        self.arena_bytes = 0
        self.cached = 0
        self.reads = 0
        self.evicted = 0
        self.outside = 0
        self.dropped = 0

    @property
    def cache_bytes(self):
        """The most sample bytes kept. Setting it takes a new arena of that
        size at once and lets go of every sample; voices playing go on
        reading the old one until they end."""
        return self._cache_bytes

    @cache_bytes.setter
    def cache_bytes(self, value):
        value = int(value)
        if value == self._cache_bytes and self._slabs is not None:
            return
        self._cache_bytes = value
        self._open()

    def _open(self):
        """Take the arena: buffers of `SLAB_BYTES`, or of the largest
        sample, up to `cache_bytes` and no more than the file holds."""
        self.evicted += len(self._order)
        self._retire()
        self._slabs = []
        self._frames = []
        self._bytes = []
        self.samples = {}
        self._order = []
        self._head = 0
        self._held = {}
        self._tails = {}
        self.cached = 0
        self.arena_bytes = 0
        font = self.font
        size = self._cache_bytes
        total = getattr(font, "_smpl_frames", None)
        if total is not None and total * 2 < size:
            size = total * 2
        largest = 0
        for sample in getattr(font, "samples", ()):
            n = sample.end - sample.start
            if n > largest:
                largest = n
        slab = max(SLAB_BYTES // 2, largest)
        if size // 2 < slab:
            slab = size // 2
        self._slab = slab
        if slab <= 0:
            return
        import gc

        gc.collect()  # what an earlier arena or bank left is free again first
        for _ in range(size // 2 // slab):
            try:
                buf = _slab(slab * 2)
            except MemoryError:
                break  # the heap gave less than asked: the arena is what it gave
            raw = memoryview(buf)
            if hasattr(raw, "cast"):
                frames = raw.cast("h")
            else:  # MicroPython: views are bytes, two to a frame
                frames = raw
                self._unit = 2
            self._slabs.append(buf)
            self._frames.append(frames)
            self._bytes.append(raw)
        self.arena_bytes = len(self._slabs) * slab * 2

    def _retire(self):
        """Keep the arena being replaced until the voices playing from it
        stop: a view of a SampleBuffer does not keep it alive, so this does."""
        if self._slabs:
            voices = [v for v in self._held if _sounding(v)]
            if voices:
                self._retired = (self._slabs, voices, ticks_ms())

    def _let_retired_go(self):
        retired = self._retired
        if retired is not None:
            slabs, voices, since = retired
            if ticks_diff(ticks_ms(), since) >= TAIL_MS and not any(_sounding(v) for v in voices):
                self._retired = None

    def hold(self, voice, index):
        """`voice` now plays sample `index`: it stays in the arena until the
        voice ends, and for `TAIL_MS` after."""
        old = self._held.get(voice)
        if old is not None and old != index:
            self._tails[old] = ticks_ms()
        self._held[voice] = index

    def _pinned(self):
        """The samples a voice or a fade may still be reading."""
        self._let_retired_go()
        now = ticks_ms()
        pinned = set()
        held = self._held
        tails = self._tails
        for voice in list(held):
            index = held[voice]
            try:
                playing = voice.playing
            except Exception:  # its sampler deinitialised: stopped, no fade
                del held[voice]
                continue
            if playing:
                pinned.add(index)
            else:
                del held[voice]
                tails[index] = now
        for index in list(tails):
            if ticks_diff(now, tails[index]) < TAIL_MS:
                pinned.add(index)
            else:
                del tails[index]
        return pinned

    def _evict(self, entry):
        self._order.remove(entry)
        del self.samples[entry[2]]
        self.cached -= entry[1] * 2
        self.evicted += 1

    def _place(self, frames):
        """An offset where `frames` fit, made by letting go of the samples
        read longest ago that sit there, stepping past any still sounding;
        None when no run fits beside them."""
        slab = self._slab
        end = slab * len(self._slabs)
        if frames > slab or end == 0:
            return None
        pinned = None
        order = self._order
        pos = self._head
        wrapped = 0
        while True:
            if pos % slab + frames > slab:
                pos = (pos // slab + 1) * slab  # a sample never straddles two buffers
            if pos >= end:
                if wrapped:
                    return None
                wrapped = 1
                pos = 0
                continue
            stop = pos + frames
            blocked = None
            for entry in order:
                if entry[0] >= stop:
                    break
                if entry[0] + entry[1] > pos:
                    if pinned is None:
                        pinned = self._pinned()
                    if entry[2] in pinned:
                        blocked = entry
            if blocked is None:
                break
            pos = blocked[0] + blocked[1]
            if wrapped and pos >= self._head:
                return None  # all the way round
        for entry in [e for e in order if e[0] < stop and e[0] + e[1] > pos]:
            self._evict(entry)
        self._head = stop
        return pos

    def _sample(self, sample):
        """The whole sample, from the arena or the file, and the items of
        it per frame."""
        index = sample.index
        entry = self.samples.get(index)
        if entry is None:
            frames = sample.end - sample.start
            if self._slabs is None:
                self._open()
            reader = getattr(self.font, "read_sample_into", None)
            pos = self._place(frames) if frames > 0 and reader is not None else None
            self.reads += 1
            if pos is None:
                return self._outside(sample, frames, reader)
            slab, at = divmod(pos, self._slab)
            reader(sample, self._bytes[slab][at * 2 : (at + frames) * 2])
            entry = [pos, frames, index]
            order = self._order
            i = 0
            while i < len(order) and order[i][0] < pos:
                i += 1
            order.insert(i, entry)
            self.samples[index] = entry
            self.cached += frames * 2
        pos, frames = entry[0], entry[1]
        slab, at = divmod(pos, self._slab)
        unit = self._unit
        return self._frames[slab][at * unit : (at + frames) * unit], unit

    def _outside(self, sample, frames, reader):
        """The sample in a buffer of its own, for one note; None when the
        heap has no room for it either, and the note goes without it."""
        self.outside += 1
        try:
            if reader is None:
                return self.font.read_sample(sample), 1
            buf = bytearray(frames * 2)
        except MemoryError:
            self.dropped += 1
            return None, 1
        reader(sample, buf)
        raw = memoryview(buf)
        if hasattr(raw, "cast"):
            return raw.cast("h"), 1
        return raw, 2

    def has(self, bank, program):
        return (bank, program) in self.presets

    def programs(self, bank):
        """Sorted (program, name) for one bank."""
        out = [(p, n) for (b, p), n in self.presets.items() if b == bank]
        out.sort()
        return out

    def melodic_bank(self):
        """The bank the patch list shows: 0, or the lowest non-percussion
        bank when there is no 0."""
        banks = sorted(set(b for b, _ in self.presets if b != PERCUSSION_BANK))
        if not banks:
            raise ValueError("the SoundFont has no melodic presets")
        return 0 if 0 in banks else banks[0]

    def buffer(self, region):
        """The frames a region plays and its loop points within them; None
        when there was no memory to read them into."""
        sample = region.sample
        pcm, unit = self._sample(sample)
        if pcm is None:
            return None
        length = len(pcm) // unit
        start = region.start - sample.start
        end = region.end - sample.start
        if start < 0:
            start = 0
        if end > length:
            end = length
        if end <= start:
            start, end = 0, length
        if start != 0 or end != length:
            pcm = memoryview(pcm)[start * unit : end * unit]
            length = end - start
        loop_start = region.loop_start - region.start
        loop_end = region.loop_end - region.start
        mode = region.loop_mode
        if mode and not (0 <= loop_start < loop_end <= length):
            # A loop that does not fit the frames is a bank error; play the
            # region through once rather than refuse the note.
            mode = 0
        if mode == 0:
            loop_start, loop_end = 0, length
        return pcm, loop_start, loop_end, mode


def _sounding(voice):
    try:
        return voice.playing
    except Exception:  # its sampler deinitialised
        return False


_OPEN = {}


def open_bank(bank=None, cache_bytes=None):
    """The shared `_Bank` for `bank` (a path, a `SoundFont`, or None to
    search). Banks opened by path are kept, so two instruments on one file
    read each sample once. `cache_bytes` bounds the samples it keeps
    (`CACHE_BYTES` when None); given for a bank already open, it changes
    that bank's bound."""
    if isinstance(bank, _Bank):
        loaded = bank
    elif hasattr(bank, "regions"):
        loaded = _Bank(bank)
    else:
        path = find_bank(bank)
        loaded = _OPEN.get(path)
        if loaded is None:
            loaded = _Bank(_SoundFont(path))
            _OPEN[path] = loaded
    if cache_bytes is not None:
        loaded.cache_bytes = cache_bytes
    return loaded


# --- the voices ------------------------------------------------------------


class Voices(object):
    """Engine voices on one sampler, for one instrument or shared by several.

        pool = soundfont.Voices(48000, 2, voice_count=48)
        melodic = adapter.create(48000, voice="soundfont", bank=path,
                                 voice_pool=pool)
        kit = adapter.create(48000, voice="soundfont_drums", bank=path,
                             voice_pool=pool)
        audio_out.play(pool.output)

    `voice_count` is how many notes' worth of engine voices the pool plays
    at once, and it can change while it plays: fewer stops the voices above
    the new count (each fades out over 5 ms), more takes effect at the next
    note. The sampler is made with `voice_count` voices, or with
    `max_voice_count` when that is more: that is the most the count can be
    raised to later, because a sampler's voices are fixed once it is made
    (and it is the thing `audio_out` plays, so it can't be swapped for a
    bigger one). A voice costs memory whether or not it sounds, so a board
    asks for what it plays; a desktop that wants room to grow asks for the
    build's ceiling, `audiosampler.MAX_VOICES`.

    Every instrument made on it has this sampler as its `output`, so play
    it once. Deinitialising one of them stops its own voices and leaves the
    sampler sounding for the rest; `deinit()` the pool after the last.

    A stolen voice stops at once, and one still sounding clicks. `reserve`
    keeps that many voices ready instead: when fewer are free, the oldest
    releasing voices are stopped, which fades each out over 5 ms on the
    engine's tail and frees it, so a new note takes a free voice before a
    sounding one. The tails end a little sooner, without the click.

    Each write to an engine voice (a note, a release, a level) waits for the
    block the audio pump is pulling, and a pump busy with a big graph is
    pulling one nearly all the time: milliseconds a write. Inside `with
    voices.deferred():` the writes queue instead, and leave at the end
    together, the pump parked for them at a block boundary: one wait for
    the lot. `voice[i]` is the voice the instruments write to, which queues
    while deferred and goes straight to the engine otherwise.

    `gain` scales every voice the pool plays. Sixteen parts summed are far
    louder than one instrument, and the sum is quantised once, so a pool for
    a whole GM module wants headroom: General MIDI players run these banks
    at about 0.2.

    `stolen` counts the voices stopped while still sounding to start a new
    note, `cut` the ones among them that were still held (a note ending
    early), and `faded` the releasing voices faded out for the reserve.
    """

    def __init__(
        self,
        sample_rate,
        channel_count=2,
        voice_count=SHARED_VOICES,
        shared=True,
        reserve=0,
        gain=1.0,
        max_voice_count=None,
    ):
        if int(voice_count) < 1:
            raise ValueError("voice_count must be at least 1")
        self.sampler = _sampler(
            sample_rate,
            channel_count,
            int(voice_count)
            if max_voice_count is None
            else max(int(voice_count), int(max_voice_count)),
        )
        self.sample_rate = sample_rate
        self.channel_count = channel_count
        self.shared = shared
        #: `slots[i]` is engine voice i: None when free, else `[key, serial,
        #: state, exclusive_class, level, pitch, pan, player]`, where `state`
        #: is `HELD`, `RELEASING` or `FADED`, `level`, `pitch` and `pan` are
        #: the region's own, before the live macros, and `player` is the
        #: instrument's that holds it.
        self.slots = [None] * int(voice_count)
        self._queue = None  # the writes waiting, while deferred
        self._pending = {}  # voice index -> playing, as the queue leaves it
        self._depth = 0
        self.voice = [_Queued(self, i) for i in range(self.sampler.voice_count)]
        self.serial = 0
        self.reserve = int(reserve)
        self.gain = float(gain)
        self.stolen = 0
        self.cut = 0
        self.faded = 0

    @property
    def output(self):
        return self.sampler

    @property
    def voice_count(self):
        """How many engine voices the pool plays at once; settable, up to
        `max_voice_count`."""
        return len(self.slots)

    @voice_count.setter
    def voice_count(self, count):
        count = int(count)
        if not 1 <= count <= self.max_voice_count:
            raise ValueError(
                "voice_count must be 1 to %d, the voices the "
                "pool's sampler was made with" % self.max_voice_count
            )
        slots = self.slots
        if count < len(slots):
            voice = self.voice
            for i in range(count, len(slots)):
                if slots[i] is not None:
                    voice[i].stop()
                    _free(slots, i)
            del slots[count:]  # in place: every player holds this list
        else:
            slots.extend([None] * (count - len(slots)))

    @property
    def max_voice_count(self):
        """The most `voice_count` can be: the sampler's voices, which the
        pool was made with and can't add to."""
        return self.sampler.voice_count

    def sounding(self):
        """How many voices are sounding now, releases included."""
        voice = self.voice
        n = 0
        for i in range(len(self.slots)):
            if voice[i].playing:
                n += 1
        return n

    def keep_free(self):
        """Stop the oldest releasing voices until `reserve` are free."""
        slots = self.slots
        ready = 0
        for slot in slots:
            if slot is None or slot[2] == FADED:
                ready += 1
        voice = self.voice
        while ready < self.reserve:
            victim = None
            oldest = 0
            for i, slot in enumerate(slots):
                if (
                    slot is not None
                    and slot[2] == RELEASING
                    and (victim is None or slot[1] < oldest)
                ):
                    victim = i
                    oldest = slot[1]
            if victim is None:
                return
            voice[victim].stop()
            _free(slots, victim)
            self.faded += 1
            ready += 1

    def playing(self, i):
        """Whether voice `i` is sounding, or will be once the queue leaves."""
        p = self._pending.get(i)
        return self.sampler.voice[i].playing if p is None else p

    def deferred(self):
        """`with voices.deferred():` queues the voices' writes and sends
        them when the outermost one ends."""
        return self

    def __enter__(self):
        if self._depth == 0:
            self._queue = []
        self._depth += 1
        return self

    def __exit__(self, *exc):
        self._depth -= 1
        if self._depth == 0:
            self.flush()
            self._queue = None
        return False

    def flush(self):
        """Send the queued writes, in order: with the pump parked at a
        block boundary when there is more than one, so they wait for one
        block between them rather than one each."""
        queue = self._queue
        if not queue:
            return
        self._queue = []
        parked = len(queue) > 1 and _park is not None and _park()
        first = None
        try:
            for fn, args, kw in queue:
                try:
                    if kw:
                        fn(*args, **kw)
                    else:
                        fn(*args)
                except Exception as e:  # the rest still go, then it raises
                    if first is None:
                        first = e
        finally:
            if parked:
                _unpark()
            self._pending.clear()
        if first is not None:
            raise first

    def deinit(self):
        if self._queue is not None:
            self._queue = []  # nothing queued goes to a sampler that is gone
        self._pending.clear()
        self.sampler.deinit()


def _free(slots, i):
    """Free slot `i` and take it out of its player's held notes."""
    slot = slots[i]
    slots[i] = None
    if slot is None:
        return
    held = slot[7].held
    indices = held.get(slot[0])
    if indices is not None:
        if i in indices:
            indices.remove(i)
        if not indices:
            del held[slot[0]]


class _Queued(object):
    """Engine voice `index` of `pool`, as the instruments write to it: its
    writes queue while the pool is deferred, and go straight on otherwise."""

    def __init__(self, pool, index):
        self._pool = pool
        self._index = index
        self._voice = pool.sampler.voice[index]

    def _send(self, fn, args, kw=None, playing=None):
        queue = self._pool._queue
        if queue is None:
            if kw:
                fn(*args, **kw)
            else:
                fn(*args)
            return
        queue.append((fn, args, kw))
        if playing is not None:
            self._pool._pending[self._index] = playing

    @property
    def playing(self):
        p = self._pool._pending.get(self._index)
        return self._voice.playing if p is None else p

    def play(self, buffer, **kw):
        self._send(self._voice.play, (buffer,), kw, True)

    def release(self):
        self._send(self._voice.release, ())

    def stop(self):
        self._send(self._voice.stop, (), None, False)

    @property
    def level(self):
        return self._voice.level

    @level.setter
    def level(self, value):
        self._send(setattr, (self._voice, "level", value))

    @property
    def pitch(self):
        return self._voice.pitch

    @pitch.setter
    def pitch(self, value):
        self._send(setattr, (self._voice, "pitch", value))

    @property
    def pan(self):
        return self._voice.pan

    @pan.setter
    def pan(self, value):
        self._send(setattr, (self._voice, "pan", value))


# --- the player ------------------------------------------------------------


class _Player(object):
    """The voices of one instrument, on its own `Voices` or a shared one.

    `slots` is the pool's: the player's own voices are the slots whose last
    item is the player.
    """

    def __init__(self, bank, voices, default_bank=0):
        self.bank = bank
        self.pool = voices
        self.sampler = voices.sampler
        self.slots = voices.slots
        self.held = {}  # key -> [slot index, ...]
        self.pedal = set()  # channels whose sustain pedal is down
        self.sustained = set()  # keys let go while their pedal was down
        self.default_bank = default_bank
        #: A drum kit sets this: a pad key (36-51) the kit has no zone for
        #: sounds the nearest pad key it has one for.
        self.nearest_pads = False
        self.bank_number = default_bank
        self.program = 0
        self.bank_msb = 0
        self.bank_lsb = 0
        self.volume = DEFAULT_MACROS[0] / 127.0
        self.attack_scale = 1.0
        self.release_scale = 1.0
        self.tune = 1.0
        self.bend = 1.0
        self.pan = 0.0

    # -- preset selection ---------------------------------------------------

    def select(self, bank_number, program):
        """Play `program` from `bank_number`, or from the default bank when
        that bank has no such program; a program no bank has is silent."""
        bank = self.bank
        if not bank.has(bank_number, program) and bank.has(self.default_bank, program):
            bank_number = self.default_bank
        self.bank_number = bank_number
        self.program = program

    def requested_bank(self):
        """The bank the last Bank Select asked for: the default bank until
        one is sent, then MSB*128+LSB when the file has it, else the MSB
        alone (GS), else the LSB alone (XG)."""
        if self.bank_msb == 0 and self.bank_lsb == 0:
            return self.default_bank
        for candidate in (self.bank_msb * 128 + self.bank_lsb, self.bank_msb, self.bank_lsb):
            if any(b == candidate for b, _ in self.bank.presets):
                return candidate
        return self.bank_msb * 128 + self.bank_lsb

    # -- voices -------------------------------------------------------------

    def _collect(self):
        """Free the slots whose voices have finished, whoever held them."""
        voices = self.sampler.voice
        pending = self.pool._pending
        slots = self.slots
        for i in range(len(slots)):
            # not a note still queued to start
            if slots[i] is not None and not voices[i].playing and not pending.get(i):
                _free(slots, i)

    def _free(self, i):
        _free(self.slots, i)

    def _allocate(self):
        slots = self.slots
        for i, slot in enumerate(slots):
            if slot is None:
                return i
        # Every voice busy: the oldest faded one, which is silent, then the
        # oldest releasing one, then the oldest.
        victim = None
        for state in (FADED, RELEASING, HELD):
            for i, slot in enumerate(slots):
                if slot[2] == state and (victim is None or slot[1] < slots[victim][1]):
                    victim = i
            if victim is not None:
                break
        pool = self.pool
        if state != FADED:
            pool.stolen += 1
        if state == HELD:
            pool.cut += 1
        # No stop(): the play() that follows hands what the voice was
        # sounding to the engine's tail, which fades it, as a stop would.
        _free(slots, victim)
        return victim

    def _choke(self, exclusive_class):
        for i, slot in enumerate(self.slots):
            if slot is not None and slot[7] is self and slot[3] == exclusive_class:
                self.pool.voice[i].stop()
                self._free(i)

    def note_on(self, key, pitch, velocity, detune):
        self.release(key)
        self._collect()
        try:
            regions = self.bank.font.regions(
                self.bank_number, self.program, pitch, int(velocity * 127 + 0.5)
            )
        except KeyError:
            return
        if not regions and self.nearest_pads and PAD_LOW <= pitch <= PAD_HIGH:
            regions = self._nearest_pad(pitch, velocity)
        if not regions:
            return
        pool = self.pool
        pool.serial += 1
        serial = pool.serial
        voices = self.pool.voice
        detune_ratio = 2.0 ** (detune / 12.0) if detune else 1.0
        # Choke before any of this note's regions start, so a stereo pair
        # in one class does not stop its own other half.
        for region in regions:
            if region.exclusive_class:
                self._choke(region.exclusive_class)
        indices = []
        for region in regions:
            frames = self.bank.buffer(region)
            if frames is None:
                continue
            pcm, loop_start, loop_end, mode = frames
            vel = velocity
            if 0 <= region.velocity <= 127:
                vel = region.velocity / 127.0
            level = (region.attenuation**ATTENUATION_SCALE) * vel * vel
            ratio = region.pitch_ratio * detune_ratio
            i = self._allocate()
            voices[i].play(
                pcm,
                rate=region.sample_rate,
                pitch=ratio * self.tune * self.bend,
                loop_start=loop_start,
                loop_end=loop_end,
                loop_mode=mode,
                level=level * self.volume * pool.gain,
                pan=_panned(region.pan, self.pan),
                delay=region.delay,
                attack=region.attack * self.attack_scale,
                hold=region.hold,
                decay=region.decay,
                sustain=region.sustain,
                release=region.release * self.release_scale,
            )
            self.bank.hold(voices[i], region.sample.index)
            self.slots[i] = [
                key,
                serial,
                HELD,
                region.exclusive_class,
                level,
                ratio,
                region.pan,
                self,
            ]
            indices.append(i)
        self.held[key] = indices
        if pool.reserve:
            pool.keep_free()

    def _nearest_pad(self, pitch, velocity):
        """The regions of the nearest pad key to `pitch` that the kit has a
        zone for, the lower one first on a tie; empty when the kit has none."""
        font = self.bank.font
        for distance in range(1, PAD_HIGH - PAD_LOW + 1):
            for candidate in (pitch - distance, pitch + distance):
                if PAD_LOW <= candidate <= PAD_HIGH:
                    try:
                        regions = font.regions(
                            self.bank_number, self.program, candidate, int(velocity * 127 + 0.5)
                        )
                    except KeyError:
                        regions = None
                    if regions:
                        return regions
        return ()

    def release(self, key):
        self.sustained.discard(key)
        indices = self.held.pop(key, None)
        if not indices:
            return
        voices = self.pool.voice
        for i in indices:
            slot = self.slots[i]
            if slot is None or slot[7] is not self:
                continue
            if voices[i].playing:
                voices[i].release()
                slot[2] = RELEASING
            else:
                self.slots[i] = None

    def release_all(self):
        for key in list(self.held):
            self.release(key)

    def sounding(self):
        voices = self.pool.voice
        n = 0
        for i, slot in enumerate(self.slots):
            if slot is not None and slot[7] is self and voices[i].playing:
                n += 1
        return n

    def stop_all(self):
        for i, slot in enumerate(self.slots):
            if slot is not None and slot[7] is self:
                self.pool.voice[i].stop()
                self.slots[i] = None
        self.held.clear()
        self.sustained.clear()
        self.pedal.clear()

    def sustain(self, channel, down):
        """Move `channel`'s sustain pedal. Up, every note let go while it
        was down releases now, with its own release envelope; keys still
        pressed keep sounding."""
        if down:
            self.pedal.add(channel)
            return
        self.pedal.discard(channel)
        for key in [k for k in self.sustained if k[0] == channel]:
            self.release(key)

    def relevel(self):
        voices = self.pool.voice
        for i, slot in enumerate(self.slots):
            if slot is not None and slot[7] is self and slot[2] != FADED:
                voices[i].level = slot[4] * self.volume * self.pool.gain

    def repitch(self):
        voices = self.pool.voice
        factor = self.tune * self.bend
        for i, slot in enumerate(self.slots):
            if slot is not None and slot[7] is self:
                voices[i].pitch = slot[5] * factor

    def repan(self):
        voices = self.pool.voice
        offset = self.pan
        for i, slot in enumerate(self.slots):
            if slot is not None and slot[7] is self:
                voices[i].pan = _panned(slot[6], offset)

    # -- events -------------------------------------------------------------

    def handle_event(self, event_type, channel, note_id, data0, value0, value1, sample_position):
        if event_type == EVENT_NOTE_ON and value0 > 0.0:
            self.note_on(key_of(channel, note_id, data0), data0, value0, value1)
        elif event_type in (EVENT_NOTE_OFF, EVENT_NOTE_ON):
            key = key_of(channel, note_id, data0)
            if channel in self.pedal and key in self.held:
                self.sustained.add(key)  # sounds on until the pedal lifts
            else:
                self.release(key)
        elif event_type == EVENT_PARAMETER:
            if data0 == 0:
                self.volume = value0
                self.relevel()
            elif data0 == 1:
                self.attack_scale = 2.0 ** (4.0 * (value0 - 64 / 127.0))
            elif data0 == 2:
                self.release_scale = 2.0 ** (4.0 * (value0 - 64 / 127.0))
            elif data0 == 3:
                self.tune = 2.0 ** ((value0 - 64 / 127.0) * 2.0 / 12.0)
                self.repitch()
            elif data0 == PAN_MACRO:
                self.pan = _bipolar(value0)
                self.repan()
        elif event_type == EVENT_PITCH_BEND:
            self.bend = 2.0 ** (value1 * BEND_RANGE / 12.0)
            self.repitch()
        elif event_type == EVENT_CONTROL_CHANGE:
            if data0 == _CC_BANK_MSB:
                self.bank_msb = int(value0 * 127 + 0.5)
            elif data0 == _CC_BANK_LSB:
                self.bank_lsb = int(value0 * 127 + 0.5)
            elif data0 == _CC_SUSTAIN:
                self.sustain(channel, int(value0 * 127 + 0.5) >= 64)


class SoundFontInstrument(Instrument):
    """An `Instrument` whose program change selects a preset in the bank.

    `programs` maps a patch index to the (bank, program) it selects; the
    melodic instrument's is identity into the melodic bank, the kit's is
    its position in bank 128. Bank Select applies to the melodic one.
    """

    def __init__(
        self,
        player,
        patches,
        programs,
        macro_labels,
        note_map=None,
        transport=None,
        bank_select=True,
        pad_map=None,
    ):
        self._player = player
        self._programs = programs
        self._bank_select = bank_select
        super().__init__(
            player.handle_event,
            patches,
            macro_labels,
            player.sampler,
            transport=transport,
            note_map=note_map,
            pad_map=pad_map,
        )

    @property
    def bank(self):
        """The open bank, for the preset list and `regions()`."""
        return self._player.bank.font

    @property
    def preset(self):
        """(bank, program) playing now."""
        return self._player.bank_number, self._player.program

    @property
    def preset_name(self):
        return self._player.bank.presets.get(self.preset)

    def control_change(self, controller, value, channel=0, sample_position=0):
        """Control Change 10 (Pan) moves the Pan macro, so the macro value
        and the sound agree; the rest reach the player as they are.

        Control Change 64 (Sustain Pedal) at 64 or more holds the notes
        released on that channel until it drops below 64, then releases
        them. A key struck again while its note is held starts a new note."""
        if controller == _CC_PAN:
            self.set_macro(PAN_MACRO, value, channel=channel, sample_position=sample_position)
            return
        super().control_change(controller, value, channel, sample_position)

    def program_change(self, index, channel=0, note_id=-1, sample_position=0):
        target = self._programs.get(index) if isinstance(index, int) else None
        if target is not None:
            bank_number, program = target
            if self._bank_select:
                bank_number = self._player.requested_bank()
            self._player.select(bank_number, program)
        super().program_change(index, channel, note_id, sample_position)

    def reset(self):
        self._player.stop_all()
        self._player.bank_msb = self._player.bank_lsb = 0
        super().reset()

    @property
    def voices(self):
        """How many notes' worth of engine voices this instrument can sound
        at once: its pool's `voice_count`, shared with the pool's other
        instruments when it has some. Set it to change it while notes play,
        up to the pool's `max_voice_count`."""
        self._check_live()
        return self._player.pool.voice_count

    @voices.setter
    def voices(self, count):
        self._check_live()
        if isinstance(count, bool) or not isinstance(count, int) or count < 1:
            raise ValueError("voices must be a positive integer")
        self._player.pool.voice_count = count

    @property
    def voice_pool(self):
        """The `Voices` this instrument plays on."""
        return self._player.pool

    def sounding(self):
        """How many of this instrument's own voices are sounding now,
        releases included: on shared `Voices`, the others' are not counted."""
        return self._player.sounding()

    def deinit(self):
        """On a shared `Voices`, stop this instrument's own voices and leave
        the sampler to the others; on its own, release the sampler too."""
        if self._deinited:
            return
        if not self._player.pool.shared:
            super().deinit()
            return
        self.all_notes_off()
        self._player.stop_all()
        self._output = None
        self._deinited = True


def _sampler(sample_rate, channel_count, voice_count=MAX_VOICES):
    import audiosampler

    return audiosampler.Sampler(
        voice_count=voice_count, channel_count=channel_count, sample_rate=sample_rate
    )


def voices_for(sample_rate, channel_count, voice_pool=None, voices=None):
    """`voice_pool` checked against the instrument's format, or a pool of
    its own of `voices` voices (`MAX_VOICES` when None)."""
    if voice_pool is None:
        return Voices(
            sample_rate, channel_count, MAX_VOICES if voices is None else voices, shared=False
        )
    if voices is not None:
        raise ValueError("a shared pool's voice_count is set on the pool")
    if voice_pool.sample_rate != sample_rate or voice_pool.channel_count != channel_count:
        raise ValueError(
            "the shared voices are %d Hz, %d channels"
            % (voice_pool.sample_rate, voice_pool.channel_count)
        )
    return voice_pool


def create(sample_rate, channel_count=2, transport=None, bank=None, voice_pool=None, voices=None):
    """The bank's melodic presets as one instrument; `bank` is a path, an
    open `SoundFont`, or None to look in the usual places. `voice_pool` is
    a `Voices` to share with other instruments, or None for its own of
    `voices` voices (`MAX_VOICES` when None)."""
    loaded = open_bank(bank)
    melodic = loaded.melodic_bank()
    programs = loaded.programs(melodic)
    patches = {}
    targets = {}
    top = programs[-1][0]
    names = dict(programs)
    for program in range(top + 1):
        name = names.get(program)
        if name is None:
            name = "Program %d (empty)" % program
        patches[program] = (name, DEFAULT_MACROS)
        targets[program] = (melodic, program)
    player = _Player(loaded, voices_for(sample_rate, channel_count, voice_pool, voices), melodic)
    return SoundFontInstrument(player, patches, targets, MACRO_LABELS, transport=transport)
