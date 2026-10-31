# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""A SoundFont 2 bank's kits as a drum instrument: bank 128, one patch per
kit, the General MIDI percussion keys 35-81 as the pads.

    kit = vrack.adapter.create(48000, voice="soundfont_drums", bank="/sd/FluidR3_GM.sf2")
    kit.note_on(36)          # Bass Drum 1 on the first kit
    kit.program_change(1)    # the bank's second kit

Patch i is the i-th preset of bank 128 in program order, named from the
bank (a General MIDI set lists its Standard kit first). The bank is found
the way `soundfont` finds it, and the two instruments made from one file
share it. A key the kit has no zone for is silent, except the sixteen pad
keys 36-51, which sound the nearest of them the kit does have (see `create`).
The closed hi-hat (42)
and pedal hi-hat (44) stop an open hi-hat (46) that is still ringing when
the bank puts them in one exclusive class, as General MIDI kits do.

The macros are `soundfont`'s: Volume, Attack, Release, Tune and Pan. Pan
(64 centre, 0 left, 127 right) is an offset on each zone's own pan, so a
kit's spread moves as one; it re-pans sounding voices, and Control Change
10 drives it.

`NOTE_MAP` is the whole GM percussion map rather than what any one kit
answers: a bank's kits differ in what they fill, and the map is what a
sequencer writes for.
"""

from ._component import pad_table
from .soundfont import (
    DEFAULT_MACROS,
    PERCUSSION_BANK,
    SoundFontInstrument,
    _Player,
    open_bank,
    voices_for,
)

NAME = "soundfont_drums"
DISPLAY_NAME = "SoundFont Drums"
CATEGORIES = ("Drum", "Sampler")
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

#: Patch 0 as a literal for the scanners; a live kit's `patches` are the
#: bank's, built in `create()`.
PATCHES = {
    0: ("Standard", (100, 64, 64, 64, 64)),
}

#: General MIDI percussion, keys 35-81, under GM's names.
NOTE_MAP = (
    (35, "Acoustic Bass Drum"),
    (36, "Bass Drum 1"),
    (37, "Side Stick"),
    (38, "Acoustic Snare"),
    (39, "Hand Clap"),
    (40, "Electric Snare"),
    (41, "Low Floor Tom"),
    (42, "Closed Hi-Hat"),
    (43, "High Floor Tom"),
    (44, "Pedal Hi-Hat"),
    (45, "Low Tom"),
    (46, "Open Hi-Hat"),
    (47, "Low-Mid Tom"),
    (48, "Hi-Mid Tom"),
    (49, "Crash Cymbal 1"),
    (50, "High Tom"),
    (51, "Ride Cymbal 1"),
    (52, "Chinese Cymbal"),
    (53, "Ride Bell"),
    (54, "Tambourine"),
    (55, "Splash Cymbal"),
    (56, "Cowbell"),
    (57, "Crash Cymbal 2"),
    (58, "Vibraslap"),
    (59, "Ride Cymbal 2"),
    (60, "Hi Bongo"),
    (61, "Low Bongo"),
    (62, "Mute Hi Conga"),
    (63, "Open Hi Conga"),
    (64, "Low Conga"),
    (65, "High Timbale"),
    (66, "Low Timbale"),
    (67, "High Agogo"),
    (68, "Low Agogo"),
    (69, "Cabasa"),
    (70, "Maracas"),
    (71, "Short Whistle"),
    (72, "Long Whistle"),
    (73, "Short Guiro"),
    (74, "Long Guiro"),
    (75, "Claves"),
    (76, "Hi Wood Block"),
    (77, "Low Wood Block"),
    (78, "Mute Cuica"),
    (79, "Open Cuica"),
    (80, "Mute Triangle"),
    (81, "Open Triangle"),
)


class SoundFontDrums(SoundFontInstrument):
    """A kit instrument: `strict_pads` says whether a pad key the kit has no
    zone for is silent (True) or sounds the nearest pad key it has."""

    def __init__(self, *args, strict_pads=False, **kw):
        self._strict_pads = bool(strict_pads)
        super().__init__(*args, **kw)

    @property
    def strict_pads(self):
        self._check_live()
        return self._strict_pads


def create(
    sample_rate,
    channel_count=2,
    transport=None,
    bank=None,
    voice_pool=None,
    voices=None,
    pad_map=None,
    strict_pads=False,
):
    """The bank's kits as one instrument; `bank`, `voice_pool` and `voices`
    as for `soundfont`.

    Pads 36-51 sound by nearest voice: a pad key the kit has no zone for
    plays the nearest of the sixteen it has. `strict_pads=True` turns that
    off, so the kit answers only keys it has a zone for; `pad_map=` (a dict
    or pairs of ``(key, key)``) replaces it with your own table, and the two
    cannot be combined."""
    table = pad_table((), pad_map, strict_pads)
    loaded = open_bank(bank)
    kits = loaded.programs(PERCUSSION_BANK)
    if not kits:
        raise ValueError("the SoundFont has no percussion bank (128)")
    patches = {}
    targets = {}
    for index, (program, name) in enumerate(kits):
        patches[index] = (name, DEFAULT_MACROS)
        targets[index] = (PERCUSSION_BANK, program)
    player = _Player(
        loaded, voices_for(sample_rate, channel_count, voice_pool, voices), PERCUSSION_BANK
    )
    player.nearest_pads = not strict_pads and pad_map is None
    return SoundFontDrums(
        player,
        patches,
        targets,
        MACRO_LABELS,
        note_map=NOTE_MAP,
        transport=transport,
        bank_select=False,
        pad_map=table,
        strict_pads=strict_pads,
    )
