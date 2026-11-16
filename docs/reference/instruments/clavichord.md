# Clavichord

The Clavichord is a ten-voice electric clavichord after a 1970s funk keyboard.
Each key presses a rubber tangent up against a steel string and holds it there
while the key is down. Let the key go and a yarn weave damps the string at
once, with a short, soft pluck as the tangent leaves it. Two electromagnetic
pickups, four tone tabs and a foam mute shape a sound that is bright,
percussive and nasal, and it gets much brighter the harder you play.

```python
import audioinstruments._rack.adapter as adapter

inst = adapter.create(48000, voice="clavichord")      # ten voices
audio_out.play(inst.output)
inst.program_change(0)                                # Funk
for note in (39, 51, 58, 61, 66):
    inst.note_on(note, 110)
```

## The mechanism

The keyboard runs 60 keys, F1 to E6 (MIDI 29 to 88); any key plays, and
outside that range the per-key values hold their end values.

**The string.** Each voice is a string of 24 harmonic partials, a touch
inharmonic, ringing in an `audiomodal.Bank` through the keys core
(`StruckBarCore`). The tangent strikes near the end of the string, so it is
rich in harmonics. Velocity 32 plays about 25 dB under velocity 127, and a
harder blow is shorter and lifts the upper partials, so a loud note is a bright
one. With the mute off the fundamental takes about 7 s to die in the bass, 2.5
s at middle C and 0.6 s at E6; each partial dies faster the higher it sits in
Hz.

**The pickups.** A pickup at a point x along the string hears partial n
weighted by sin(nπx). The upper pickup sits about 1/12 of the string from the
bridge, so it is bright and thin; the lower sits about 1/5 along, warmer, with
more fundamental. `both` adds them and `both_out` subtracts them: the two are
level on the fundamental, so out of phase it is gone, leaving a hollow, nasal
sound. Choosing a pickup changes each partial's gain in the bank; it is not a
filter after the string.

**The damper and the release pluck.** Let a key go and the note is damped in
about 30 ms. The release pluck is the string's first three partials, as the
chosen pickup hears them, about 15 dB under the note's attack and gone in
about 50 ms. The original has no sustain pedal; the pedal (CC 64) works here
as on every instrument.

**The mute.** `mute` (0 to 10) presses foam against the strings: it shortens
every note, down to about 0.15 s at 10, rather than only making it quieter.

**The output section.** After the voices are mixed, four tone tabs stack:
`brilliant` (a high-pass at 600 Hz), `treble` (a gentler high-pass at 300 Hz),
`medium` (a broad band-pass at 1 kHz) and `soft` (a low-pass at 2 kHz); all off
is the raw pickup. Then the auto-wah (`wah`, 0 off to 10), a resonant band-pass
whose centre follows the level of what you play: a hard note sweeps it up from
350 Hz through the upper partials and lets it fall back as the note dies, a
soft one barely moves it. Then `volume`, into an output stage that stays linear
in normal playing and rounds the coincident peaks of a hard ten-note chord
instead of clipping them, and an amplitude tremolo (`tremolo_rate`,
`tremolo_depth`), which the original did not have.

## Controls and presets

Levels run 0 to 10, and the tabs are switches, 0 or 1:

- `pickup`: `"upper"`, `"lower"`, `"both"` (fresh) or `"both_out"`.
- `brilliant`, `treble`, `medium`, `soft`: the tone tabs; fresh, only `medium`
  is on.
- `mute` (0 fresh), `wah` (0 fresh), `volume` (7 fresh).
- `tremolo_rate` (5 fresh) and `tremolo_depth` (0 fresh).

The eight presets: Funk (0, both pickups, `medium`), Brilliant Upper (1, upper
pickup, `brilliant` and `treble`), Warm Lower (2, lower pickup, `soft`), Out of
Phase (3, `both_out`, `treble`), Muted (4, `mute` 6, both pickups, `medium`),
Auto-Wah (5, `wah` 7, upper pickup, `treble`), Full (6, both pickups, every tab
off) and Tremolo (7, `tremolo_depth` 5 at `tremolo_rate` 6, lower pickup,
`medium`). The eight macros are `pickup` (0 to 3), `mute`, `wah`,
`brilliant`, `treble`, `medium`, `soft` and `tremolo_depth`.

`inst.latency_samples` is 256 frames (5.3 ms at 48 kHz), the modal bank's
chunk.

## Where the numbers come from

The pickup positions, the tone tabs' frequencies, the mute's shortest note and
the release pluck's level come from how the original is built. The decay by key
and the level across velocity were steered toward a General MIDI clavi,
FluidR3's program 7, with `tools/traits.py` (see [Traits](https://github.com/PyDevices/audioinstruments/blob/main/docs/dev/traits.md) below):

    python tools/traits.py --reference af2894 7 --phrase keys --vs clavichord:0

The time to fall 6 dB on the Funk patch runs 350, 240, 182, 148 and 86 ms from
C2 to C6, against the reference's 982, 192, 178, 154 and 66, and the level at
velocity 32 and 80 is within 1 dB of it. The reference holds its bass note
almost level for a second, longer than a string decays. It is also brighter
through the middle of the keyboard (a centroid near 2 kHz at middle C, against
about 1.2 kHz on the Funk patch), and it barely brightens with velocity, where
the original changes a great deal.

## What it costs

`examples/poly_bench.py clavichord` renders 1024-frame buffers (21 ms of
audio) with all ten voices held on the Funk patch (on [the desktop the other figures come from](../../how-it-works/performance.md#the-desktop-the-figures-come-from)):

| block | CPython ms | factor | MicroPython ms | factor |
| ---: | ---: | ---: | ---: | ---: |
| 64 | 10.3 | 2.1 | 9.2 | 2.3 |
| 128 (the default) | 8.0 | 2.7 | 6.0 | 3.6 |
| 256 | 6.3 | 3.4 | 4.0 | 5.3 |

The factor is seconds of audio per second of work. With nothing playing, idle
voices park and the instrument costs about 0.8 ms (0.7 ms on MicroPython) a
buffer at 128 frames.

`examples/clavichord_demo.py` plays a 70-second funk piece in six sections
(Funk, Brilliant Upper, Warm Lower, Out of Phase, Muted and Auto-Wah) and
writes `wav_exports/clavichord_demo.wav`.
