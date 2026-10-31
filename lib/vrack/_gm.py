# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""General MIDI's names for the percussion keys this library uses.

Every drum machine here answers GM note numbers, so one MIDI track plays on
any of them. The names live in one place because three readers want them: the
`drumkits` multi-machine instrument labels its voices from this table, the
tests render the README's kit/hit grid from it, and a person reading either
one needs them to agree.

Only the keys some machine maps are listed. A name here that nothing answers
would be a slot the library claims and does not fill.
"""

#: MIDI note -> General MIDI percussion name.
PERCUSSION = {
    35: "Acoustic Bass Drum",
    36: "Bass Drum 1",
    37: "Side Stick",
    38: "Acoustic Snare",
    39: "Hand Clap",
    40: "Electric Snare",
    41: "Low Floor Tom",
    42: "Closed Hi-Hat",
    43: "High Floor Tom",
    44: "Pedal Hi-Hat",
    45: "Low Tom",
    46: "Open Hi-Hat",
    47: "Low-Mid Tom",
    48: "Hi-Mid Tom",
    49: "Crash Cymbal 1",
    50: "High Tom",
    51: "Ride Cymbal 1",
    52: "Chinese Cymbal",
    53: "Ride Bell",
    54: "Tambourine",
    55: "Splash Cymbal",
    56: "Cowbell",
    57: "Crash Cymbal 2",
    58: "Vibraslap",
    59: "Ride Cymbal 2",
    60: "Hi Bongo",
    61: "Low Bongo",
    62: "Mute Hi Conga",
    63: "Open Hi Conga",
    64: "Low Conga",
    69: "Cabasa",
    70: "Maracas",
    73: "Short Guiro",
    75: "Claves",
}
