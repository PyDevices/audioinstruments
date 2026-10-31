"""Write a SoundFont 2 bank from scratch, for the `_sf2` reader's tests.

Nothing here reads a `.sf2`; it only writes one, chunk by chunk, from the
same specification the reader was written from, so the two can disagree
and a test can tell. `tiny_bank()` is the bank the tests know by heart:
three presets (a piano with a pad layer, a pad, a bank-128 kit), a global
zone at both levels, split key ranges, a velocity split, every loop mode,
an exclusive-class pair and a stereo pair.

Runs on CPython and MicroPython, so the same bank can be built on a board.
"""

import struct

import audioinstruments._rack._sf2 as sf2

SAMPLE_RATE = 22050


def _chunk(fourcc, body):
    pad = b"\x00" if len(body) & 1 else b""
    return fourcc + struct.pack("<I", len(body)) + body + pad


def _list(kind, body):
    return _chunk(b"LIST", kind + body)


def _zstr(text, length):
    raw = text.encode()[: length - 1]
    return raw + b"\x00" * (length - len(raw))


def _gen(oper, amount):
    if isinstance(amount, tuple):
        return struct.pack("<HBB", oper, amount[0], amount[1])
    if oper in (sf2.GEN_INSTRUMENT, sf2.GEN_SAMPLE_ID):
        return struct.pack("<HH", oper, amount)
    return struct.pack("<Hh", oper, amount)


class Bank(object):
    """Collects samples, instruments and presets, then writes the file.

    A zone is a list of (operator, amount) pairs in file order; a range
    amount is a (low, high) tuple. The caller puts `keyRange` first and the
    terminal generator (`instrument` or `sampleID`) last, as the
    specification requires; a zone without the terminal is global.
    """

    def __init__(self, name="tiny", modulators=()):
        self.name = name
        self.samples = []  # (name, frames, loop_start, loop_end, pitch,
        #                            correction, link, kind)
        self.instruments = []  # (name, [zone, ...])
        self.presets = []  # (name, bank, program, [zone, ...])
        self.modulators = list(modulators)  # instrument-level, raw 10 bytes

    def sample(
        self,
        name,
        frames,
        loop_start=0,
        loop_end=None,
        pitch=60,
        correction=0,
        link=0,
        kind=sf2.SAMPLE_MONO,
    ):
        if loop_end is None:
            loop_end = len(frames)
        self.samples.append((name, frames, loop_start, loop_end, pitch, correction, link, kind))
        return len(self.samples) - 1

    def instrument(self, name, zones):
        self.instruments.append((name, zones))
        return len(self.instruments) - 1

    def preset(self, name, bank, program, zones):
        self.presets.append((name, bank, program, zones))

    def build(self):
        # sdta: each sample followed by the 46 zero frames the spec asks for.
        smpl = b""
        starts = []
        for _name, frames, _ls, _le, _p, _c, _l, _k in self.samples:
            starts.append(len(smpl) // 2)
            smpl += struct.pack("<%dh" % len(frames), *frames)
            smpl += b"\x00" * 92
        sdta = _list(b"sdta", _chunk(b"smpl", smpl))

        shdr = b""
        for i, (name, frames, ls, le, pitch, corr, link, kind) in enumerate(self.samples):
            start = starts[i]
            shdr += _zstr(name, 20) + struct.pack(
                "<IIIIIBbHH",
                start,
                start + len(frames),
                start + ls,
                start + le,
                SAMPLE_RATE,
                pitch,
                corr,
                link,
                kind,
            )
        shdr += _zstr("EOS", 20) + b"\x00" * 26

        inst, ibag, igen = b"", b"", b""
        imod = b""
        for name, zones in self.instruments:
            inst += _zstr(name, 20) + struct.pack("<H", len(ibag) // 4)
            for zone in zones:
                ibag += struct.pack("<HH", len(igen) // 4, len(imod) // 10)
                for oper, amount in zone:
                    igen += _gen(oper, amount)
        for mod in self.modulators:
            imod += mod
        inst += _zstr("EOI", 20) + struct.pack("<H", len(ibag) // 4)
        ibag += struct.pack("<HH", len(igen) // 4, len(imod) // 10)
        igen += b"\x00" * 4
        imod += b"\x00" * 10

        phdr, pbag, pgen = b"", b"", b""
        for name, bank, program, zones in self.presets:
            phdr += _zstr(name, 20) + struct.pack("<HHHIII", program, bank, len(pbag) // 4, 0, 0, 0)
            for zone in zones:
                pbag += struct.pack("<HH", len(pgen) // 4, 0)
                for oper, amount in zone:
                    pgen += _gen(oper, amount)
        phdr += _zstr("EOP", 20) + struct.pack("<HHHIII", 0, 0, len(pbag) // 4, 0, 0, 0)
        pbag += struct.pack("<HH", len(pgen) // 4, 0)
        pgen += b"\x00" * 4
        pmod = b"\x00" * 10

        pdta = _list(
            b"pdta",
            _chunk(b"phdr", phdr)
            + _chunk(b"pbag", pbag)
            + _chunk(b"pmod", pmod)
            + _chunk(b"pgen", pgen)
            + _chunk(b"inst", inst)
            + _chunk(b"ibag", ibag)
            + _chunk(b"imod", imod)
            + _chunk(b"igen", igen)
            + _chunk(b"shdr", shdr),
        )
        info = _list(
            b"INFO",
            _chunk(b"ifil", struct.pack("<HH", 2, 1))
            + _chunk(b"isng", _zstr("EMU8000", 8))
            + _chunk(b"INAM", _zstr(self.name, len(self.name) + 1)),
        )
        return _chunk(b"RIFF", b"sfbk" + info + sdta + pdta)

    def write(self, path):
        data = self.build()
        with open(path, "wb") as f:
            f.write(data)
        return path


# The tiny bank's sample data: frame i of sample n holds n * 1000 + i, so a
# test can tell which frames a read returned.
def _frames(n, count):
    return [n * 1000 + i for i in range(count)]


# A modulator record: velocity -> initialAttenuation, the usual default one,
# written explicitly so `has_modulators` has something to see.
VELOCITY_TO_ATTENUATION = struct.pack("<HHhHH", 0x0502, sf2.GEN_ATTENUATION, 960, 0, 0)


def tiny_bank(modulators=()):
    """The bank the tests check exactly. See `tests/test_cpython_sf2.py`."""
    b = Bank("Tiny Test Bank", modulators)
    G = sf2
    s_low = b.sample("low_c4", _frames(0, 200), 50, 150, pitch=60)
    s_snare = b.sample("snare", _frames(1, 100), pitch=38, correction=-10)
    s_pad_l = b.sample("pad_L", _frames(2, 120), 10, 110, pitch=48, link=3, kind=G.SAMPLE_LEFT)
    s_pad_r = b.sample("pad_R", _frames(3, 120), 10, 110, pitch=48, link=2, kind=G.SAMPLE_RIGHT)
    s_hat_c = b.sample("hat_closed", _frames(4, 80), pitch=42)
    s_hat_o = b.sample("hat_open", _frames(5, 90), 20, 90, pitch=46)
    s_high = b.sample("high_c5", _frames(6, 150), 30, 140, pitch=72, correction=7)

    piano = b.instrument(
        "Piano",
        [
            # global zone: envelope and a pan every local zone inherits
            [
                (G.GEN_DECAY_VOL_ENV, 1200),
                (G.GEN_SUSTAIN_VOL_ENV, 200),
                (G.GEN_RELEASE_VOL_ENV, -1200),
                (G.GEN_PAN, -100),
            ],
            # low half: looped, every address offset kind in play
            [
                (G.GEN_KEY_RANGE, (0, 65)),
                (G.GEN_START_OFFSET, 5),
                (G.GEN_END_OFFSET, 32760),
                (G.GEN_END_COARSE, -1),
                (G.GEN_STARTLOOP_OFFSET, 2),
                (G.GEN_ENDLOOP_OFFSET, -3),
                (G.GEN_SAMPLE_MODES, 1),
                (G.GEN_SAMPLE_ID, s_low),
            ],
            # high half: root override, tuning, key-tracked hold and decay,
            # a local pan that overrides the global one
            [
                (G.GEN_KEY_RANGE, (66, 127)),
                (G.GEN_ROOT_KEY, 70),
                (G.GEN_COARSE_TUNE, 1),
                (G.GEN_FINE_TUNE, -5),
                (G.GEN_SCALE_TUNING, 50),
                (G.GEN_HOLD_VOL_ENV, 0),
                (G.GEN_KEYNUM_TO_HOLD, 50),
                (G.GEN_KEYNUM_TO_DECAY, 100),
                (G.GEN_PAN, 250),
                (G.GEN_SAMPLE_MODES, 3),
                (G.GEN_SAMPLE_ID, s_high),
            ],
        ],
    )
    kit = b.instrument(
        "Kit",
        [
            [(G.GEN_KEY_RANGE, (36, 36)), (G.GEN_SAMPLE_MODES, 0), (G.GEN_SAMPLE_ID, s_snare)],
            [
                (G.GEN_KEY_RANGE, (38, 38)),
                (G.GEN_VEL_RANGE, (0, 79)),
                (G.GEN_ATTENUATION, 100),
                (G.GEN_SAMPLE_ID, s_snare),
            ],
            [(G.GEN_KEY_RANGE, (38, 38)), (G.GEN_VEL_RANGE, (80, 127)), (G.GEN_SAMPLE_ID, s_snare)],
            [
                (G.GEN_KEY_RANGE, (42, 42)),
                (G.GEN_EXCLUSIVE_CLASS, 1),
                (G.GEN_SAMPLE_MODES, 2),
                (G.GEN_SAMPLE_ID, s_hat_c),
            ],
            [
                (G.GEN_KEY_RANGE, (46, 46)),
                (G.GEN_EXCLUSIVE_CLASS, 1),
                (G.GEN_SAMPLE_MODES, 3),
                (G.GEN_SAMPLE_ID, s_hat_o),
            ],
        ],
    )
    pad = b.instrument(
        "Pad",
        [
            [(G.GEN_PAN, -500), (G.GEN_SAMPLE_MODES, 1), (G.GEN_SAMPLE_ID, s_pad_l)],
            [(G.GEN_PAN, 500), (G.GEN_SAMPLE_MODES, 1), (G.GEN_SAMPLE_ID, s_pad_r)],
        ],
    )

    b.preset(
        "Piano",
        0,
        0,
        [
            # preset global zone: adds to every instrument value underneath
            [(G.GEN_ATTENUATION, 50), (G.GEN_FINE_TUNE, 10)],
            # the piano, cut to 0..100 at preset level
            [(G.GEN_KEY_RANGE, (0, 100)), (G.GEN_INSTRUMENT, piano)],
            # a soft pad layer in the middle; its pan nudges right and clips
            [
                (G.GEN_KEY_RANGE, (48, 72)),
                (G.GEN_VEL_RANGE, (0, 63)),
                (G.GEN_PAN, 100),
                (G.GEN_INSTRUMENT, pad),
            ],
        ],
    )
    b.preset(
        "Standard Kit",
        128,
        0,
        [
            [(G.GEN_INSTRUMENT, kit)],
        ],
    )
    b.preset(
        "Pad",
        0,
        1,
        [
            # sampleModes at preset level is forbidden and must be ignored
            [(G.GEN_SAMPLE_MODES, 0), (G.GEN_INSTRUMENT, pad)],
        ],
    )
    return b
