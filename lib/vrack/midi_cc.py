# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Scaling functions for every MIDI 1.0 Control Change code.

Source: "Table 3 - Control Change Messages and RPNs", MIDI Manufacturers
Association, 2020. Which control each code means comes from the spec;
nothing here is invented to suit a particular instrument.


Why these do not return 7-bit numbers
-------------------------------------
The spec lists every controller's range as 0-127 because MIDI is a wire
protocol and 7 bits is what fits in a data byte. That is a property of the
cable, not of the control. VST3 has no such limit: it normalises every
parameter to a 0.0-1.0 float, and that is what the host sends us, what an
automation lane records, and what the plug-in hands a macro.

So the translation between the two is ours to choose, and we choose not to
quantise:

  Resolution. Rounding a host's float to one of 128 steps would discard
  resolution we were handed for free. A slow filter sweep quantised to 128
  steps is audible as stair-stepping, and automation envelopes are exactly
  where this library spends its time. Continuous controls therefore keep
  full float precision end to end.

  Centre. MIDI's centre detent is byte 64, which normalises to 64/127 =
  0.50394, not 0.5. In VST3 the natural centre is exactly 0.5 - it is
  where a host parks an untouched parameter and what a bipolar control's
  default wants to be. A bipolar control here is therefore exactly neutral
  at 0.5, not at 0.50394. Switches flip at 0.5 for the same reason, rather
  than at the spec's byte-64 threshold.

The exception is controls whose value is a *number* rather than a
magnitude: bank and program numbers, parameter numbers, the note number in
Portamento Control, a channel count, and every LSB. Those genuinely are
7-bit integers - there is no such thing as bank 3.7 - so they are returned
as int, quantised on purpose.


How to use this in an instrument
--------------------------------
Two stages, and the second one is yours. This module only converts a
0.0-1.0 input into the control's own terms; turning that into something
the instrument accepts is the instrument's job, because only the instrument knows
what its filter or envelope wants.

    from vrack.midi_cc import cc_scale, BRIGHTNESS, CHANNEL_VOLUME

    # Bind the scaler once, at import, named for the knob it drives.
    brightness = cc_scale[BRIGHTNESS]
    channel_volume = cc_scale[CHANNEL_VOLUME]

    def handle_event(event_type, channel, note_id, data0, value0, ...):
        if event_type == EVENT_PARAMETER:
            if data0 == 1:
                # brightness() gives -1..+1; map it onto the cutoff range
                # this instrument actually wants, in Hz.
                cutoff = 2000.0 * (4.0 ** brightness(value0))
            elif data0 == 0:
                volume = channel_volume(value0)      # already 0..1

`vrack`'s instruments divide by exactly the same line. Their `Instrument`
methods speak MIDI 0-127 because that is what a keyboard, a sequencer and a
saved patch all speak, and the wrapper divides by 127.0 before anything
inside an instrument sees it - so the value arriving at a scaler here is
already the 0.0-1.0 this module expects, and a caller with finer resolution
than 7 bits (an automation lane, a drawn envelope) can pass a float and keep
it. Wire ints at the edge, scaled floats inside: the same split this module
draws between bank numbers and filter cutoffs.

Assigning a CC code to a knob is a decision the instrument author makes.
Nothing here forces a mapping - pick the code whose meaning matches the
knob, then map its result to whatever the instrument needs.


Return types
------------
    float 0.0..1.0   continuous controllers the spec gives no unit to
    float -1.0..1.0  bipolar controllers, exactly 0.0 at 0.5
    int   0..127     values that really are 7-bit numbers (see above)
    bool              switches; the spec's <= 63 off / >= 64 on, at 0.5
    None              messages the spec says carry no value

Codes the spec marks "Undefined" are present as plain pass-throughs.
Undefined means free for manufacturer use, not unusable.

Why Sound Controllers 71-78 are bipolar
---------------------------------------
The MMA table gives these a flat 0-127 range and defers their defaults to
MMA RP-021, which is not much to build on. So this was checked against
shipping hardware instead. Roland's INTEGRA-7 MIDI implementation (2012)
documents all eight identically:

    Cutoff (Controller number 74)
    vv = Cutoff value (relative change): 00H - 40H - 7FH (-64 - 0 - +63)
    * The Cutoff Offset parameter (PART VIEW:OFFSET) will change.

Every one of 71-78 says "relative change", spans -64 to +63 about a centre
of 40H, and drives a parameter the machine itself calls an Offset. They
modify the patch's own value rather than replacing it. That is why they
are bipolar here, and it is what makes 0.5 a safe arrival value for a
macro nobody set: the patch is heard exactly as designed.

The same document confirms the rest of this table by contrast, which is
the more useful result:

    CC 91/93 Reverb and Chorus Send Level    "00H - 7FH (0 - 127)"
    CC 80-83 General Purpose 5-8             "00H - 7FH (0 - 127)"

Those are plain absolute levels, not relative - so the effect depths at
91-95 stay unipolar, where zero means none. CC 84 is "kk = source note
number", confirming it as an int rather than a magnitude, and CC 64-69 are
"0-63 = OFF, 64-127 = ON", confirming the switches.

CC 70 (Sound Variation) and CC 79 (undefined) are absolute. They sit in
the 70-79 block but no device found documents them as relative changes,
and the spec gives 79 no meaning at all.

One deviation worth recording: RPN Channel Fine Tuning is +/-100 cents
here, per the MMA table's own "00H 00H = -100 cents ... 7FH 7FH = +100
cents". The INTEGRA-7 accepts only 20 00H - 60 00H, i.e. +/-50 cents. That
is a device restricting the range, not disagreeing about it, so the
general definition is what this module implements.
"""

# --- conversions -------------------------------------------------------------


def _unit(x):
    """0.0..1.0 -> 0.0..1.0, clamped. Full float precision, no quantising."""
    if x < 0.0:
        return 0.0
    if x > 1.0:
        return 1.0
    return x


def _bipolar(x):
    """0.0..1.0 -> -1.0..+1.0, exactly 0.0 at 0.5.

    Deliberately centred on 0.5 rather than on MIDI's byte-64 detent
    (0.50394): 0.5 is where a VST3 host leaves an untouched parameter.
    """
    return _unit(x) * 2.0 - 1.0


def _switch(x):
    """0.0..1.0 -> bool. The spec's <= 63 off / >= 64 on, at the VST3
    half-way point rather than at 64/127."""
    return _unit(x) >= 0.5


def _byte(x):
    """0.0..1.0 -> a 7-bit number, 0..127.

    Only for controls whose value is a number rather than a magnitude:
    bank/program/parameter/note numbers, channel counts, and LSBs.
    """
    return int(_unit(x) * 127.0 + 0.5)


def _none(x):
    """Messages the spec says carry no value (their data byte is fixed)."""
    return None


# Sound Controllers 71-78, the eight the spec gives default meanings to.
# Relative, per RP-021 and confirmed against shipping hardware - see the
# module docstring. 70 (Sound Variation) and 79 (undefined) are not in
# this group: no device documents them as relative changes.
_sound_controller = _bipolar


# --- control numbers ---------------------------------------------------------

BANK_SELECT = 0
MODULATION_WHEEL = 1
BREATH_CONTROLLER = 2
FOOT_CONTROLLER = 4
PORTAMENTO_TIME = 5
DATA_ENTRY_MSB = 6
CHANNEL_VOLUME = 7
BALANCE = 8
PAN = 10
EXPRESSION = 11
EFFECT_CONTROL_1 = 12
EFFECT_CONTROL_2 = 13
GENERAL_PURPOSE_1 = 16
GENERAL_PURPOSE_2 = 17
GENERAL_PURPOSE_3 = 18
GENERAL_PURPOSE_4 = 19

DAMPER_PEDAL = 64
PORTAMENTO_ON_OFF = 65
SOSTENUTO = 66
SOFT_PEDAL = 67
LEGATO_FOOTSWITCH = 68
HOLD_2 = 69

# Sound Controllers 1-10, with the spec's default meanings.
SOUND_VARIATION = 70
TIMBRE = 71  # Harmonic Intensity - a resonance control
RELEASE_TIME = 72
ATTACK_TIME = 73
BRIGHTNESS = 74  # the spec's name for a filter cutoff
DECAY_TIME = 75
VIBRATO_RATE = 76
VIBRATO_DEPTH = 77
VIBRATO_DELAY = 78
SOUND_CONTROLLER_10 = 79

GENERAL_PURPOSE_5 = 80
GENERAL_PURPOSE_6 = 81
GENERAL_PURPOSE_7 = 82
GENERAL_PURPOSE_8 = 83
PORTAMENTO_CONTROL = 84
HIGH_RESOLUTION_VELOCITY_PREFIX = 88

# Effects depths 1-5, with the spec's default and former meanings.
REVERB_SEND = 91
TREMOLO_DEPTH = 92  # "formerly Tremolo Depth"
CHORUS_SEND = 93  # "formerly Chorus Depth"
DETUNE_DEPTH = 94  # "formerly Celeste [Detune] Depth"
PHASER_DEPTH = 95

DATA_INCREMENT = 96
DATA_DECREMENT = 97
NRPN_LSB = 98
NRPN_MSB = 99
RPN_LSB = 100
RPN_MSB = 101

ALL_SOUND_OFF = 120
RESET_ALL_CONTROLLERS = 121
LOCAL_CONTROL = 122
ALL_NOTES_OFF = 123
OMNI_MODE_OFF = 124
OMNI_MODE_ON = 125
MONO_MODE_ON = 126
POLY_MODE_ON = 127


# --- the table ---------------------------------------------------------------

# Control code -> a function taking the host's 0.0-1.0 and returning the
# control's own value. x is always in the range 0.0 to 1.0.
cc_scale = {
    0: _byte,  # Bank Select (MSB)
    1: _unit,  # Modulation Wheel or Lever
    2: _unit,  # Breath Controller
    3: _unit,  # Undefined
    4: _unit,  # Foot Controller
    5: _unit,  # Portamento Time
    6: _byte,  # Data Entry MSB
    7: _unit,  # Channel Volume (formerly Main Volume)
    8: _bipolar,  # Balance
    9: _unit,  # Undefined
    10: _bipolar,  # Pan
    11: _unit,  # Expression Controller
    12: _unit,  # Effect Control 1
    13: _unit,  # Effect Control 2
    14: _unit,  # Undefined
    15: _unit,  # Undefined
    16: _unit,  # General Purpose Controller 1
    17: _unit,  # General Purpose Controller 2
    18: _unit,  # General Purpose Controller 3
    19: _unit,  # General Purpose Controller 4
    20: _unit,  # Undefined
    21: _unit,  # Undefined
    22: _unit,  # Undefined
    23: _unit,  # Undefined
    24: _unit,  # Undefined
    25: _unit,  # Undefined
    26: _unit,  # Undefined
    27: _unit,  # Undefined
    28: _unit,  # Undefined
    29: _unit,  # Undefined
    30: _unit,  # Undefined
    31: _unit,  # Undefined
    # 32-63: LSB for Controls 0-31 - the low 7 bits of a 14-bit value, so
    # genuinely 7-bit numbers.
    32: _byte,  # LSB for Control 0 (Bank Select)
    33: _byte,  # LSB for Control 1 (Modulation Wheel)
    34: _byte,  # LSB for Control 2 (Breath Controller)
    35: _byte,  # LSB for Control 3 (Undefined)
    36: _byte,  # LSB for Control 4 (Foot Controller)
    37: _byte,  # LSB for Control 5 (Portamento Time)
    38: _byte,  # LSB for Control 6 (Data Entry)
    39: _byte,  # LSB for Control 7 (Channel Volume)
    40: _byte,  # LSB for Control 8 (Balance)
    41: _byte,  # LSB for Control 9 (Undefined)
    42: _byte,  # LSB for Control 10 (Pan)
    43: _byte,  # LSB for Control 11 (Expression)
    44: _byte,  # LSB for Control 12 (Effect Control 1)
    45: _byte,  # LSB for Control 13 (Effect Control 2)
    46: _byte,  # LSB for Control 14 (Undefined)
    47: _byte,  # LSB for Control 15 (Undefined)
    48: _byte,  # LSB for Control 16 (Gen. Purpose 1)
    49: _byte,  # LSB for Control 17 (Gen. Purpose 2)
    50: _byte,  # LSB for Control 18 (Gen. Purpose 3)
    51: _byte,  # LSB for Control 19 (Gen. Purpose 4)
    52: _byte,  # LSB for Control 20 (Undefined)
    53: _byte,  # LSB for Control 21 (Undefined)
    54: _byte,  # LSB for Control 22 (Undefined)
    55: _byte,  # LSB for Control 23 (Undefined)
    56: _byte,  # LSB for Control 24 (Undefined)
    57: _byte,  # LSB for Control 25 (Undefined)
    58: _byte,  # LSB for Control 26 (Undefined)
    59: _byte,  # LSB for Control 27 (Undefined)
    60: _byte,  # LSB for Control 28 (Undefined)
    61: _byte,  # LSB for Control 29 (Undefined)
    62: _byte,  # LSB for Control 30 (Undefined)
    63: _byte,  # LSB for Control 31 (Undefined)
    # 64-69: switches.
    64: _switch,  # Damper Pedal on/off (Sustain)
    65: _switch,  # Portamento On/Off
    66: _switch,  # Sostenuto On/Off
    67: _switch,  # Soft Pedal On/Off
    68: _switch,  # Legato Footswitch (on = Legato)
    69: _switch,  # Hold 2
    # 70-79: Sound Controllers. 71-78 are relative: 64 is "no change",
    # confirmed against Roland's INTEGRA-7 MIDI implementation, where each
    # drives an explicit "Offset" parameter. 70 and 79 are not relative on
    # any device found, so they stay absolute.
    70: _unit,  # Sound Controller 1 (Sound Variation)
    71: _sound_controller,  # Sound Controller 2 (Timbre/Harmonic Intens.)
    72: _sound_controller,  # Sound Controller 3 (Release Time)
    73: _sound_controller,  # Sound Controller 4 (Attack Time)
    74: _sound_controller,  # Sound Controller 5 (Brightness)
    75: _sound_controller,  # Sound Controller 6 (Decay Time)
    76: _sound_controller,  # Sound Controller 7 (Vibrato Rate)
    77: _sound_controller,  # Sound Controller 8 (Vibrato Depth)
    78: _sound_controller,  # Sound Controller 9 (Vibrato Delay)
    79: _unit,  # Sound Controller 10 (default undefined)
    80: _unit,  # General Purpose Controller 5
    81: _unit,  # General Purpose Controller 6
    82: _unit,  # General Purpose Controller 7
    83: _unit,  # General Purpose Controller 8
    84: _byte,  # Portamento Control (a source note number)
    85: _unit,  # Undefined
    86: _unit,  # Undefined
    87: _unit,  # Undefined
    88: _byte,  # High Resolution Velocity Prefix
    89: _unit,  # Undefined
    90: _unit,  # Undefined
    # 91-95: effect depths. Zero means none, so these stay unipolar.
    91: _unit,  # Effects 1 Depth (Reverb Send Level)
    92: _unit,  # Effects 2 Depth (formerly Tremolo Depth)
    93: _unit,  # Effects 3 Depth (Chorus Send Level)
    94: _unit,  # Effects 4 Depth (formerly Celeste [Detune] Depth)
    95: _unit,  # Effects 5 Depth (formerly Phaser Depth)
    96: _none,  # Data Increment (Data Entry +1) - no value
    97: _none,  # Data Decrement (Data Entry -1) - no value
    98: _byte,  # Non-Registered Parameter Number - LSB
    99: _byte,  # Non-Registered Parameter Number - MSB
    100: _byte,  # Registered Parameter Number - LSB
    101: _byte,  # Registered Parameter Number - MSB
    102: _unit,  # Undefined
    103: _unit,  # Undefined
    104: _unit,  # Undefined
    105: _unit,  # Undefined
    106: _unit,  # Undefined
    107: _unit,  # Undefined
    108: _unit,  # Undefined
    109: _unit,  # Undefined
    110: _unit,  # Undefined
    111: _unit,  # Undefined
    112: _unit,  # Undefined
    113: _unit,  # Undefined
    114: _unit,  # Undefined
    115: _unit,  # Undefined
    116: _unit,  # Undefined
    117: _unit,  # Undefined
    118: _unit,  # Undefined
    119: _unit,  # Undefined
    # 120-127: Channel Mode messages. These change the channel's operating
    # mode rather than a sound parameter, and the spec fixes their data
    # byte, so almost none of them carry a value to scale.
    120: _none,  # All Sound Off (data 0)
    121: _none,  # Reset All Controllers (data 0)
    122: _switch,  # Local Control On/Off (0 off, 127 on)
    123: _none,  # All Notes Off (data 0)
    124: _none,  # Omni Mode Off (+ all notes off)
    125: _none,  # Omni Mode On (+ all notes off)
    126: _byte,  # Mono Mode On - data is the channel count
    127: _none,  # Poly Mode On (data 0)
}


# --- Registered Parameter Numbers -------------------------------------------

PITCH_BEND_SENSITIVITY = (0x00, 0x00)
CHANNEL_FINE_TUNING = (0x00, 0x01)
CHANNEL_COARSE_TUNING = (0x00, 0x02)
TUNING_PROGRAM_CHANGE = (0x00, 0x03)
TUNING_BANK_SELECT = (0x00, 0x04)
MODULATION_DEPTH_RANGE = (0x00, 0x05)
MPE_CONFIGURATION = (0x00, 0x06)
RPN_NULL = (0x7F, 0x7F)

# Table 3a. This is where the spec states real physical units rather than a
# bare 0-127, so these return cents and semitones directly - no second
# mapping needed in the instrument. Keyed by the (MSB, LSB) pair you would
# send on CC 101 and CC 100.
rpn_scale = {
    # MSB = +/- semitones, LSB = +/- cents. Returned in semitones, over the
    # 0-24 range hardware conventionally offers.
    PITCH_BEND_SENSITIVITY: lambda x: _unit(x) * 24.0,
    # 00H 00H = -100 cents, 40H 00H = A440, 7FH 7FH = +100 cents.
    CHANNEL_FINE_TUNING: lambda x: _bipolar(x) * 100.0,
    # MSB only, resolution 100 cents: 00H = -6400 cents, 40H = A440,
    # 7FH = +6300 cents. Returned in semitones, and genuinely quantised -
    # coarse tuning steps by whole semitones.
    CHANNEL_COARSE_TUNING: lambda x: _byte(x) - 64,
    TUNING_PROGRAM_CHANGE: _byte,
    TUNING_BANK_SELECT: _byte,
    # Defined by the GM2 spec; manufacturer-defined elsewhere.
    MODULATION_DEPTH_RANGE: _unit,
    MPE_CONFIGURATION: _byte,
    # Setting RPN to 7FH,7FH disables data entry, increment and decrement
    # until a new RPN or NRPN is selected.
    RPN_NULL: _none,
}


# --- names -------------------------------------------------------------------

# The spec's own wording, for tooling that wants to label a control. Kept
# apart from the table above so that stays a pure code -> function map.
cc_name = {
    0: "Bank Select",
    1: "Modulation Wheel or Lever",
    2: "Breath Controller",
    4: "Foot Controller",
    5: "Portamento Time",
    6: "Data Entry MSB",
    7: "Channel Volume",
    8: "Balance",
    10: "Pan",
    11: "Expression Controller",
    12: "Effect Control 1",
    13: "Effect Control 2",
    16: "General Purpose Controller 1",
    17: "General Purpose Controller 2",
    18: "General Purpose Controller 3",
    19: "General Purpose Controller 4",
    64: "Damper Pedal on/off (Sustain)",
    65: "Portamento On/Off",
    66: "Sostenuto On/Off",
    67: "Soft Pedal On/Off",
    68: "Legato Footswitch",
    69: "Hold 2",
    70: "Sound Controller 1 (default: Sound Variation)",
    71: "Sound Controller 2 (default: Timbre/Harmonic Intens.)",
    72: "Sound Controller 3 (default: Release Time)",
    73: "Sound Controller 4 (default: Attack Time)",
    74: "Sound Controller 5 (default: Brightness)",
    75: "Sound Controller 6 (default: Decay Time)",
    76: "Sound Controller 7 (default: Vibrato Rate)",
    77: "Sound Controller 8 (default: Vibrato Depth)",
    78: "Sound Controller 9 (default: Vibrato Delay)",
    79: "Sound Controller 10 (default undefined)",
    80: "General Purpose Controller 5",
    81: "General Purpose Controller 6",
    82: "General Purpose Controller 7",
    83: "General Purpose Controller 8",
    84: "Portamento Control",
    88: "High Resolution Velocity Prefix",
    91: "Effects 1 Depth (default: Reverb Send Level)",
    92: "Effects 2 Depth (formerly Tremolo Depth)",
    93: "Effects 3 Depth (default: Chorus Send Level)",
    94: "Effects 4 Depth (formerly Celeste [Detune] Depth)",
    95: "Effects 5 Depth (formerly Phaser Depth)",
    96: "Data Increment",
    97: "Data Decrement",
    98: "Non-Registered Parameter Number (NRPN) - LSB",
    99: "Non-Registered Parameter Number (NRPN) - MSB",
    100: "Registered Parameter Number (RPN) - LSB",
    101: "Registered Parameter Number (RPN) - MSB",
    120: "All Sound Off",
    121: "Reset All Controllers",
    122: "Local Control On/Off",
    123: "All Notes Off",
    124: "Omni Mode Off",
    125: "Omni Mode On",
    126: "Mono Mode On",
    127: "Poly Mode On",
}

rpn_name = {
    PITCH_BEND_SENSITIVITY: "Pitch Bend Sensitivity",
    CHANNEL_FINE_TUNING: "Channel Fine Tuning",
    CHANNEL_COARSE_TUNING: "Channel Coarse Tuning",
    TUNING_PROGRAM_CHANGE: "Tuning Program Change",
    TUNING_BANK_SELECT: "Tuning Bank Select",
    MODULATION_DEPTH_RANGE: "Modulation Depth Range",
    MPE_CONFIGURATION: "MPE Configuration Message",
    RPN_NULL: "Null Function Number for RPN/NRPN",
}

for _cc in range(32, 64):
    cc_name.setdefault(_cc, "LSB for Control %d" % (_cc - 32))
for _cc in range(128):
    cc_name.setdefault(_cc, "Undefined")
del _cc
