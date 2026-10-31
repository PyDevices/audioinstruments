# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""A SoundFont 2 (.sf2) reader, written from the SoundFont 2.04 specification.

Open a bank, ask what it holds, and ask what sounds for a note:

    bank = SoundFont("/sd/FluidR3_GM.sf2")
    bank.presets()                      # [(bank, program, name), ...]
    for region in bank.regions(0, 0, key=60, velocity=100):
        pcm = bank.read_sample(region.sample)   # array('h'), mono frames
        ...

A `Region` is one flat answer to "what plays": a sample with its absolute
start, end and loop points in frames (every address-offset generator, coarse
ones included, already applied), the root key and tuning for the key asked
for, the loop mode, the volume envelope in seconds and linear levels, the
attenuation as a linear gain, pan in -1..1, the exclusive class, and the
stereo link. The engine that plays regions (`audiosampler.Sampler`) wants
exactly those; nothing here knows about it.

How generators are combined, from the specification: an instrument's global
zone supplies defaults that its local zones override; a preset's global zone
does the same for the preset's local zones; and preset-level generators are
*added* to the instrument's values, except key and velocity ranges, which
intersect, and the generators the specification forbids at preset level
(sample addresses, sampleModes, exclusiveClass, overridingRootKey, keynum,
velocity), which are ignored there. Modulators are not implemented; the
reader only records whether a bank carries any (`has_modulators`).

Samples stay on disk. The reader keeps the `smpl` chunk's offset and
`read_sample()` reads a region's frames when asked, which is what a board
with a few hundred kilobytes of RAM needs. `load_samples=True` reads the
whole chunk once instead, for the desktop. The optional 24-bit extension
(`sm24`) is ignored: samples are read as 16-bit.

Runs on CPython and MicroPython: plain classes, `struct.unpack_from`, no
typing at runtime.
"""

import array
import struct

#: Keys (bank, program, key) whose regions a bank keeps built: building one
#: is most of what a note costs on a board.
REGION_CACHE = 512

# Generator operators (specification section 8.1.2).
GEN_START_OFFSET = 0
GEN_END_OFFSET = 1
GEN_STARTLOOP_OFFSET = 2
GEN_ENDLOOP_OFFSET = 3
GEN_START_COARSE = 4
GEN_FILTER_FC = 8
GEN_FILTER_Q = 9
GEN_END_COARSE = 12
GEN_PAN = 17
GEN_DELAY_VOL_ENV = 33
GEN_ATTACK_VOL_ENV = 34
GEN_HOLD_VOL_ENV = 35
GEN_DECAY_VOL_ENV = 36
GEN_SUSTAIN_VOL_ENV = 37
GEN_RELEASE_VOL_ENV = 38
GEN_KEYNUM_TO_HOLD = 39
GEN_KEYNUM_TO_DECAY = 40
GEN_INSTRUMENT = 41
GEN_KEY_RANGE = 43
GEN_VEL_RANGE = 44
GEN_STARTLOOP_COARSE = 45
GEN_KEYNUM = 46
GEN_VELOCITY = 47
GEN_ATTENUATION = 48
GEN_ENDLOOP_COARSE = 50
GEN_COARSE_TUNE = 51
GEN_FINE_TUNE = 52
GEN_SAMPLE_ID = 53
GEN_SAMPLE_MODES = 54
GEN_SCALE_TUNING = 56
GEN_EXCLUSIVE_CLASS = 57
GEN_ROOT_KEY = 58

# Sample types (shdr sfSampleType).
SAMPLE_MONO = 1
SAMPLE_RIGHT = 2
SAMPLE_LEFT = 4
SAMPLE_LINKED = 8
SAMPLE_ROM = 0x8000

# Instrument-level defaults for the generators this reader reads (section
# 8.1.3). Everything absent here defaults to zero.
_DEFAULTS = {
    GEN_FILTER_FC: 13500,
    GEN_DELAY_VOL_ENV: -12000,
    GEN_ATTACK_VOL_ENV: -12000,
    GEN_HOLD_VOL_ENV: -12000,
    GEN_DECAY_VOL_ENV: -12000,
    GEN_RELEASE_VOL_ENV: -12000,
    GEN_KEYNUM: -1,
    GEN_VELOCITY: -1,
    GEN_SCALE_TUNING: 100,
    GEN_ROOT_KEY: -1,
}

# Generators a preset zone may not carry (section 8.5); ignored at that level.
_INSTRUMENT_ONLY = set(
    (
        GEN_START_OFFSET,
        GEN_END_OFFSET,
        GEN_STARTLOOP_OFFSET,
        GEN_ENDLOOP_OFFSET,
        GEN_START_COARSE,
        GEN_END_COARSE,
        GEN_STARTLOOP_COARSE,
        GEN_ENDLOOP_COARSE,
        GEN_KEYNUM,
        GEN_VELOCITY,
        GEN_SAMPLE_MODES,
        GEN_EXCLUSIVE_CLASS,
        GEN_ROOT_KEY,
        GEN_SAMPLE_ID,
    )
)

_RANGE_GENS = (GEN_KEY_RANGE, GEN_VEL_RANGE)
_UNSIGNED_GENS = (GEN_INSTRUMENT, GEN_SAMPLE_ID)

_COARSE = 32768


class SoundFontError(ValueError):
    """The file is not a SoundFont 2 bank this reader can use."""


def _name(data, offset, length=20):
    raw = bytes(data[offset : offset + length])
    cut = raw.find(b"\x00")
    if cut >= 0:
        raw = raw[:cut]
    try:
        return raw.decode("utf-8")
    except (UnicodeError, ValueError):
        return "".join(chr(b) for b in raw)


def timecents_to_seconds(timecents):
    """Absolute timecents to seconds (1200 timecents per doubling)."""
    return 2.0 ** (timecents / 1200.0)


def centibels_to_gain(centibels):
    """Centibels of attenuation to a linear gain (0 cB is unity)."""
    if centibels <= 0:
        return 1.0
    return 10.0 ** (-centibels / 200.0)


def _pcm(data):
    """16-bit little-endian bytes as array('h').

    CPython's array iterates a bytes initializer as integers and wants
    `frombytes`; MicroPython has no `frombytes` and takes a bytes object
    (only a bytes object: a memoryview is iterated) as the buffer itself.
    """
    out = array.array("h")
    if hasattr(out, "frombytes"):
        out.frombytes(data)
        return out
    if not isinstance(data, bytes):
        data = bytes(data)
    return array.array("h", data)


def cents_to_hz(cents):
    """Absolute cents (8.176 Hz at zero) to Hz."""
    return 8.176 * 2.0 ** (cents / 1200.0)


class Sample(object):
    """One `shdr` record. Frame addresses are into the `smpl` chunk."""

    def __init__(
        self,
        index,
        name,
        start,
        end,
        loop_start,
        loop_end,
        sample_rate,
        original_pitch,
        pitch_correction,
        link,
        sample_type,
    ):
        self.index = index
        self.name = name
        self.start = start
        self.end = end
        self.loop_start = loop_start
        self.loop_end = loop_end
        self.sample_rate = sample_rate
        self.original_pitch = original_pitch
        self.pitch_correction = pitch_correction
        self.link = link
        self.sample_type = sample_type

    def __repr__(self):
        return "Sample(%d, %r, %d..%d @%d)" % (
            self.index,
            self.name,
            self.start,
            self.end,
            self.sample_rate,
        )


class Region(object):
    """What one zone sounds like for one key and velocity.

    `start`, `end`, `loop_start`, `loop_end` are absolute frames into the
    sample data, address offsets applied; `read_sample(region.sample,
    region.start, region.end)` fetches exactly the frames to play.
    `pitch_ratio` is the playback ratio at the sample's own rate: multiply by
    `sample_rate / output_rate` for an engine running at another rate.
    """

    def __init__(self):
        self.sample = None
        self.key_low = 0
        self.key_high = 127
        self.vel_low = 0
        self.vel_high = 127
        self.start = 0
        self.end = 0
        self.loop_start = 0
        self.loop_end = 0
        self.sample_rate = 0
        self.loop_mode = 0
        self.root_key = 60
        self.scale_tuning = 100
        self.tune = 0
        self.cents = 0.0
        self.pitch_ratio = 1.0
        self.keynum = -1
        self.velocity = -1
        self.delay = 0.0
        self.attack = 0.0
        self.hold = 0.0
        self.decay = 0.0
        self.sustain = 1.0
        self.release = 0.0
        self.attenuation = 1.0
        self.pan = 0.0
        self.exclusive_class = 0
        self.sample_type = SAMPLE_MONO
        self.link = None
        self.filter_cutoff = 13500
        self.filter_q = 0
        self.filter_hz = 0.0
        self.generators = None

    def __repr__(self):
        return "Region(%r, key %d-%d, vel %d-%d, root %d)" % (
            self.sample.name if self.sample else None,
            self.key_low,
            self.key_high,
            self.vel_low,
            self.vel_high,
            self.root_key,
        )


class SoundFont(object):
    """A SoundFont 2 bank open for reading.

    `load_samples=True` reads the sample chunk into memory at open; the
    default leaves it on disk and `read_sample()` seeks. `index=True`
    (the default) resolves every preset's zones at open so the first note
    on any preset is as fast as the rest; `index=False` resolves each preset
    the first time it is asked for, which keeps a board's RAM for the
    presets it plays.
    """

    def __init__(self, path, load_samples=False, index=True):
        self.path = path
        self.info = {}
        self.has_modulators = False
        self.samples = []
        self._file = open(path, "rb")  # noqa: SIM115 - held open for the life of the bank
        self._smpl_offset = 0
        self._smpl_frames = 0
        self._smpl = None
        self._presets = []  # (bank, program, name, bag_lo, bag_hi)
        self._insts = []  # (name, bag_lo, bag_hi)
        self._pbag = None
        self._pgen = None
        self._ibag = None
        self._igen = None
        self._index = {}  # (bank, program) -> [candidate, ...]
        self._built = {}  # (bank, program, key) -> [[candidate, Region or None], ...]
        try:
            self._parse()
            if load_samples:
                self.load_samples()
            if index:
                for key in self._preset_keys():
                    self._index_preset(key)
        except Exception:
            self.close()
            raise

    def close(self):
        if self._file is not None:
            self._file.close()
            self._file = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # -- the file -----------------------------------------------------------

    def _read(self, offset, size):
        self._file.seek(offset)
        data = self._file.read(size)
        if len(data) != size:
            raise SoundFontError("truncated at %d" % offset)
        return data

    def _parse(self):
        head = self._read(0, 12)
        if head[0:4] != b"RIFF" or head[8:12] != b"sfbk":
            raise SoundFontError("not a RIFF sfbk file")
        riff_size = struct.unpack_from("<I", head, 4)[0]
        pos = 12
        end = 8 + riff_size
        seen = set()
        while pos + 8 <= end:
            hdr = self._read(pos, 8)
            fourcc = hdr[0:4]
            size = struct.unpack_from("<I", hdr, 4)[0]
            if fourcc != b"LIST":
                raise SoundFontError("unexpected chunk %r" % fourcc)
            kind = self._read(pos + 8, 4)
            body = pos + 12
            body_end = pos + 8 + size
            if kind == b"INFO":
                self._parse_info(body, body_end)
            elif kind == b"sdta":
                self._parse_sdta(body, body_end)
            elif kind == b"pdta":
                self._parse_pdta(body, body_end)
            seen.add(kind)
            pos = body_end + (size & 1)
        for kind in (b"INFO", b"sdta", b"pdta"):
            if kind not in seen:
                raise SoundFontError("missing %s list" % kind.decode())

    def _subchunks(self, pos, end):
        while pos + 8 <= end:
            hdr = self._read(pos, 8)
            size = struct.unpack_from("<I", hdr, 4)[0]
            yield hdr[0:4], pos + 8, size
            pos += 8 + size + (size & 1)

    def _parse_info(self, pos, end):
        for fourcc, body, size in self._subchunks(pos, end):
            data = self._read(body, size)
            key = fourcc.decode()
            if fourcc == b"ifil" or fourcc == b"iver":
                self.info[key] = struct.unpack_from("<HH", data, 0)
            else:
                self.info[key] = _name(data, 0, size)
        version = self.info.get("ifil")
        if version is None or version[0] != 2:
            raise SoundFontError("not a SoundFont 2 bank: ifil=%r" % (version,))

    def _parse_sdta(self, pos, end):
        for fourcc, body, size in self._subchunks(pos, end):
            if fourcc == b"smpl":
                self._smpl_offset = body
                self._smpl_frames = size // 2
            # sm24 (the 24-bit extension) is ignored.

    def _parse_pdta(self, pos, end):
        chunks = {}
        for fourcc, body, size in self._subchunks(pos, end):
            chunks[fourcc] = self._read(body, size)
        for need in (b"phdr", b"pbag", b"pgen", b"inst", b"ibag", b"igen", b"shdr"):
            if need not in chunks:
                raise SoundFontError("hydra lacks %s" % need.decode())

        # Modulators: recorded, never applied. Each chunk ends in a
        # terminal record, so one record means none.
        for fourcc in (b"pmod", b"imod"):
            if len(chunks.get(fourcc, b"")) > 10:
                self.has_modulators = True

        phdr = chunks[b"phdr"]
        count = len(phdr) // 38
        bag_ndx = []
        for i in range(count):
            o = i * 38
            program, bank, bag = struct.unpack_from("<HHH", phdr, o + 20)
            bag_ndx.append(bag)
            if i < count - 1:
                self._presets.append([bank, program, _name(phdr, o), bag, 0])
        for i in range(len(self._presets)):
            self._presets[i][4] = bag_ndx[i + 1]

        inst = chunks[b"inst"]
        count = len(inst) // 22
        bag_ndx = []
        for i in range(count):
            o = i * 22
            bag = struct.unpack_from("<H", inst, o + 20)[0]
            bag_ndx.append(bag)
            if i < count - 1:
                self._insts.append([_name(inst, o), bag, 0])
        for i in range(len(self._insts)):
            self._insts[i][2] = bag_ndx[i + 1]

        self._pbag = chunks[b"pbag"]
        self._pgen = chunks[b"pgen"]
        self._ibag = chunks[b"ibag"]
        self._igen = chunks[b"igen"]

        shdr = chunks[b"shdr"]
        count = len(shdr) // 46 - 1  # the terminal EOS record
        for i in range(count):
            o = i * 46
            (start, end_, loop_start, loop_end, rate, pitch, correction, link, kind) = (
                struct.unpack_from("<IIIIIBbHH", shdr, o + 20)
            )
            self.samples.append(
                Sample(
                    i,
                    _name(shdr, o),
                    start,
                    end_,
                    loop_start,
                    loop_end,
                    rate,
                    pitch,
                    correction,
                    link,
                    kind,
                )
            )

    # -- zones ---------------------------------------------------------------

    def _zone_gens(self, bags, gens, bag):
        """The generators of one bag, as {operator: amount}."""
        lo = struct.unpack_from("<H", bags, bag * 4)[0]
        hi = struct.unpack_from("<H", bags, bag * 4 + 4)[0]
        out = {}
        for g in range(lo, hi):
            o = g * 4
            oper = struct.unpack_from("<H", gens, o)[0]
            if oper in _RANGE_GENS:
                lo_b, hi_b = struct.unpack_from("<BB", gens, o + 2)
                out[oper] = (lo_b, hi_b)
            elif oper in _UNSIGNED_GENS:
                out[oper] = struct.unpack_from("<H", gens, o + 2)[0]
            else:
                out[oper] = struct.unpack_from("<h", gens, o + 2)[0]
        return out

    def _zones(self, bags, gens, bag_lo, bag_hi, terminal):
        """A record's zones as (global, [local, ...]).

        `terminal` is the generator a local zone must end with (instrument
        for presets, sampleID for instruments). A first zone without it is
        the global zone; any later zone without it is ignored.
        """
        global_gens = {}
        locals_ = []
        for bag in range(bag_lo, bag_hi):
            zone = self._zone_gens(bags, gens, bag)
            if terminal in zone:
                locals_.append(zone)
            elif bag == bag_lo:
                global_gens = zone
        return global_gens, locals_

    def _preset_keys(self):
        return [(p[0], p[1]) for p in self._presets]

    def _find_preset(self, bank, program):
        for p in self._presets:
            if p[0] == bank and p[1] == program:
                return p
        return None

    def _index_preset(self, key):
        """Resolve a preset to flat candidates: ranges, instrument and preset
        generators for each (preset zone, instrument zone) pair."""
        preset = self._find_preset(key[0], key[1])
        if preset is None:
            raise KeyError("no preset bank %d program %d" % key)
        pglobal, pzones = self._zones(self._pbag, self._pgen, preset[3], preset[4], GEN_INSTRUMENT)
        candidates = []
        for pzone in pzones:
            pg = dict(pglobal)
            pg.update(pzone)
            inst_index = pg.pop(GEN_INSTRUMENT)
            if inst_index >= len(self._insts):
                continue
            inst = self._insts[inst_index]
            pk_lo, pk_hi = pg.pop(GEN_KEY_RANGE, (0, 127))
            pv_lo, pv_hi = pg.pop(GEN_VEL_RANGE, (0, 127))
            for oper in list(pg):
                if oper in _INSTRUMENT_ONLY:
                    del pg[oper]
            iglobal, izones = self._zones(self._ibag, self._igen, inst[1], inst[2], GEN_SAMPLE_ID)
            for izone in izones:
                ig = dict(iglobal)
                ig.update(izone)
                k_lo, k_hi = ig.pop(GEN_KEY_RANGE, (0, 127))
                v_lo, v_hi = ig.pop(GEN_VEL_RANGE, (0, 127))
                k_lo = max(k_lo, pk_lo)
                k_hi = min(k_hi, pk_hi)
                v_lo = max(v_lo, pv_lo)
                v_hi = min(v_hi, pv_hi)
                if k_lo > k_hi or v_lo > v_hi:
                    continue
                if ig[GEN_SAMPLE_ID] >= len(self.samples):
                    continue
                candidates.append((k_lo, k_hi, v_lo, v_hi, ig, pg))
        self._index[key] = candidates
        return candidates

    # -- the public face -----------------------------------------------------

    def presets(self):
        """Every preset as (bank, program, name), in bank then program order."""
        out = [(p[0], p[1], p[2]) for p in self._presets]
        out.sort()
        return out

    def preset_name(self, bank, program):
        p = self._find_preset(bank, program)
        return None if p is None else p[2]

    def regions(self, bank, program, key, velocity=100):
        """The regions that sound for `key` at `velocity` on a preset.

        Raises KeyError for a preset the bank does not have. An empty list
        means the preset has nothing for that key and velocity. The regions
        are kept for the next note on the same key (up to `REGION_CACHE`
        keys), so they are shared: read them, don't change them.
        """
        built = self._built.get((bank, program, key))
        if built is None:
            candidates = self._index.get((bank, program))
            if candidates is None:
                candidates = self._index_preset((bank, program))
            if len(self._built) >= REGION_CACHE:
                self._built.clear()
            built = [[c, None] for c in candidates if c[0] <= key <= c[1]]
            self._built[(bank, program, key)] = built
        out = []
        for entry in built:
            c = entry[0]
            if c[2] <= velocity <= c[3]:
                region = entry[1]
                if region is None:
                    region = entry[1] = self._region(c[0], c[1], c[2], c[3], c[4], c[5], key)
                out.append(region)
        return out

    def read_sample(self, sample, start=None, end=None):
        """Frames `[start, end)` of a sample as array('h'), the whole sample
        when no bounds are given. Little-endian 16-bit, as the file holds
        them."""
        if start is None:
            start = sample.start
        if end is None:
            end = sample.end
        if start < 0 or end > self._smpl_frames or end < start:
            raise SoundFontError("sample %r out of the smpl chunk" % sample.name)
        if self._smpl is not None:
            return _pcm(self._smpl[start * 2 : end * 2])
        return _pcm(self._read(self._smpl_offset + start * 2, (end - start) * 2))

    def read_sample_into(self, sample, buf, start=None, end=None):
        """Read frames `[start, end)` of a sample (the whole sample when no
        bounds are given) into `buf`, a writable buffer of at least that
        many 16-bit frames, with no copy on the way. The bytes go in as
        the file holds them, little-endian."""
        if start is None:
            start = sample.start
        if end is None:
            end = sample.end
        if start < 0 or end > self._smpl_frames or end < start:
            raise SoundFontError("sample %r out of the smpl chunk" % sample.name)
        size = (end - start) * 2
        out = memoryview(buf)
        if getattr(out, "itemsize", 1) != 1 and hasattr(out, "cast"):
            out = out.cast("B")
        if len(out) < size:
            raise ValueError("the buffer holds fewer frames than the sample")
        if self._smpl is not None:
            out[:size] = self._smpl[start * 2 : end * 2]
            return
        self._file.seek(self._smpl_offset + start * 2)
        got = 0
        while got < size:
            n = self._file.readinto(out[got:size])
            if not n:
                raise SoundFontError("truncated at %d" % (self._smpl_offset + start * 2 + got))
            got += n

    def load_samples(self):
        """Read the whole smpl chunk into memory, for `read_sample` to slice."""
        if self._smpl is None:
            self._smpl = memoryview(self._read(self._smpl_offset, self._smpl_frames * 2))

    # -- one region ----------------------------------------------------------

    def _linked(self, sample):
        """The other channel of a stereo sample, or None.

        Only a link the header can stand behind: another sample whose type
        carries the complementary channel. Banks exist that mark samples
        left and right and leave every `wSampleLink` at zero (FluidR3 does,
        for all 970 of its stereo samples); there the pair is still two
        regions, one panned each way, but `link` is None.
        """
        kind = sample.sample_type & (SAMPLE_LEFT | SAMPLE_RIGHT | SAMPLE_LINKED)
        if not kind or sample.link == sample.index:
            return None
        if sample.link >= len(self.samples):
            return None
        other = self.samples[sample.link]
        if kind == SAMPLE_LEFT:
            want = SAMPLE_RIGHT
        elif kind == SAMPLE_RIGHT:
            want = SAMPLE_LEFT
        else:
            want = SAMPLE_LINKED
        return other if other.sample_type & want else None

    def _region(self, k_lo, k_hi, v_lo, v_hi, ig, pg, key):
        def gen(oper):
            return ig.get(oper, _DEFAULTS.get(oper, 0)) + pg.get(oper, 0)

        sample = self.samples[ig[GEN_SAMPLE_ID]]
        r = Region()
        r.sample = sample
        r.key_low, r.key_high, r.vel_low, r.vel_high = k_lo, k_hi, v_lo, v_hi
        r.generators = (ig, pg)

        r.start = sample.start + gen(GEN_START_OFFSET) + _COARSE * gen(GEN_START_COARSE)
        r.end = sample.end + gen(GEN_END_OFFSET) + _COARSE * gen(GEN_END_COARSE)
        r.loop_start = (
            sample.loop_start + gen(GEN_STARTLOOP_OFFSET) + _COARSE * gen(GEN_STARTLOOP_COARSE)
        )
        r.loop_end = sample.loop_end + gen(GEN_ENDLOOP_OFFSET) + _COARSE * gen(GEN_ENDLOOP_COARSE)
        r.sample_rate = sample.sample_rate

        mode = gen(GEN_SAMPLE_MODES) & 3
        r.loop_mode = 0 if mode == 2 else mode

        root = gen(GEN_ROOT_KEY)
        if root < 0 or root > 127:
            root = sample.original_pitch
            if root > 127:
                root = 60  # 255: unpitched, taken as middle C
        r.root_key = root
        r.keynum = gen(GEN_KEYNUM)
        r.velocity = gen(GEN_VELOCITY)
        played = r.keynum if 0 <= r.keynum <= 127 else key
        r.scale_tuning = gen(GEN_SCALE_TUNING)
        r.tune = 100 * gen(GEN_COARSE_TUNE) + gen(GEN_FINE_TUNE) + sample.pitch_correction
        r.cents = (played - root) * r.scale_tuning + r.tune
        r.pitch_ratio = 2.0 ** (r.cents / 1200.0)

        r.delay = timecents_to_seconds(gen(GEN_DELAY_VOL_ENV))
        r.attack = timecents_to_seconds(gen(GEN_ATTACK_VOL_ENV))
        r.hold = timecents_to_seconds(
            gen(GEN_HOLD_VOL_ENV) + (60 - played) * gen(GEN_KEYNUM_TO_HOLD)
        )
        r.decay = timecents_to_seconds(
            gen(GEN_DECAY_VOL_ENV) + (60 - played) * gen(GEN_KEYNUM_TO_DECAY)
        )
        sustain = gen(GEN_SUSTAIN_VOL_ENV)
        r.sustain = 0.0 if sustain >= 1000 else centibels_to_gain(sustain)
        r.release = timecents_to_seconds(gen(GEN_RELEASE_VOL_ENV))

        r.attenuation = centibels_to_gain(gen(GEN_ATTENUATION))
        pan = gen(GEN_PAN)
        if pan < -500:
            pan = -500
        elif pan > 500:
            pan = 500
        r.pan = pan / 500.0

        r.exclusive_class = gen(GEN_EXCLUSIVE_CLASS)
        r.sample_type = sample.sample_type
        r.link = self._linked(sample)

        r.filter_cutoff = gen(GEN_FILTER_FC)
        r.filter_q = gen(GEN_FILTER_Q)
        r.filter_hz = cents_to_hz(r.filter_cutoff)
        return r
