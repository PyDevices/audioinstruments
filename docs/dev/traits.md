# Traits

How an instrument's sound is pinned, so a change that moves it shows up in the
tests. Read it when you add an instrument or move one's sound on purpose.

`tools/traits.py` plays an instrument's fixed phrase and measures its sound:
for each note across the range, its pitch in cents, its spectral centroid
and first harmonics against the fundamental, its attack, decay, sustain and
release from the RMS envelope, and its stereo correlation; across
velocities, how level and brightness follow the key; and the noise floor
when everything has died away. `SPECS` in that file says, per instrument,
which patches to play, which notes and velocities, and how long to hold and
ring. Its `controls` sets controls on a patch after the program change, so a
held note can be measured with a moving effect stopped.

    python tools/traits.py poly106            # compare with tests/traits/poly106.json
    python tools/traits.py poly106 --show     # print every trait
    python tools/traits.py poly106 --accept   # store what it measures now

`tests/traits/<name>.json` keeps the accepted value of each trait and a
tolerance for it (3 cents of pitch, 1 dB of level, 1.5 dB of a harmonic, 5%
of a centroid, 15% of a time). `tests/test_traits.py` renders the phrase
again and lists every trait that moved.

When it accepts, the tool plays the phrase twice more, bent a count sharp and a
count flat, and keeps only the traits that hold within half their tolerance.
The rest are listed under `unsteady` and not checked. Two detuned oscillators
beat, and a count of tuning moves the beating inside the measuring window, so
a decay time or a harmonic level taken there would fail on any change that
touches rounding. A single-oscillator voice keeps every trait.

A trait file is what the instrument
sounded like when it was accepted, not what it ought to sound like: when a
change moves the sound on purpose, accept the new values and say in the
commit what moved. The Poly106's phrase plays five patches and its check
takes about five seconds on CPython.

The tool also measures a SoundFont preset with the same phrase, which the
fixed-sound instruments (pianos, organs, drum machines) are studied against.
Name a bank by the start of its md5, then the preset:

    python tools/traits.py --reference af2894 4 --phrase keys --show
    python tools/traits.py --reference af2894 4 --phrase keys --vs electric_piano:0

The bank is found through its record in `~/soundfonts/reference/`, and the
file must still match the record, so a renamed or replaced file cannot pass
for the one that was studied. The phrase is played through `audioinstruments._rack.soundfont`
and written as the same traits under `ref.`; with `--vs NAME[:PATCH]` the
tool prints how the instrument's accepted traits differ from the
reference's. Banks live in `~/soundfonts/` and never in this repository, and
the tests that need a real bank skip without one.

## Drums

A drum sound is struck, not held, and rings by itself for a few milliseconds
or several seconds, so a drum instrument or a kit is measured with a drum
phrase (`"drums": True` in a spec, and `drums` among the phrases). Each note
is struck at three velocities (40, 100 and 127). The key is held, as a
one-shot drum plays whatever the gate, until the output has been silent for
50 ms or 10 seconds are up, and then let go. A kit's spec leaves `notes` as
`None` and the tool asks the preset which keys from 27 to 87 it has a zone
for; a reference's record keeps the list it found.

    python tools/traits.py --reference af2894 25 --bank 128 --show     # FluidR3's TR-808 kit
    python tools/traits.py --reference 508fabe3 0 --phrase drums       # a kit in a melodic bank

`--bank 128` plays the program number as a kit through `soundfont_drums`.
A kit that lives in a melodic bank, as FreePats' Synthesizer Percussion does
at 0:0, is measured with `--phrase drums`. An instrument with a drum spec is
checked like any other (`python tools/traits.py NAME`, `--accept`).

Per note, under `d<note>.`:

| trait | what it is |
| --- | --- |
| `v40.peak_db`, `v100.peak_db`, `v127.peak_db` | the loudest sample at each velocity, dB full scale |
| `v40.centroid_hz` and so on | the spectral centroid at each velocity |
| `decay20_ms`, `decay40_ms` | from the loudest moment to the last moment within 20 and 40 dB of it (RMS envelope) |
| `length_ms` | from the strike to the last moment within 60 dB of the loudest |
| `centroid_hz` | the centroid of the first half second, at velocity 100 |
| `band_low_db`, `band_mid_db`, `band_high_db` | the share of the energy below 200 Hz, from 200 Hz to 2 kHz, and above 2 kHz, in dB |
| `noise_tone_db` | the energy outside the spectrum's tonal peaks against the energy in them: negative for a tone, positive for noise, within 40 dB |
| `fundamental_hz` | when a tone in 25 to 800 Hz carries a fifth of the energy: a kick, a tom, a cowbell |
| `pitch_drop_cents` | with a fundamental, how far the pitch fell between 2-12 ms and 38-48 ms after its loudest moment, while the tone still sounds |

`noise_floor_db` follows the last strike. The tolerances are the ones above
plus 2 dB for a band, 3 dB for noise against tone, 3% for a fundamental,
20% or 50 cents for the pitch drop and 25% or 30 ms for the length. A trait
a strike lacks (a hat has no fundamental) is left out, so a strike that gains
or loses one shows up as a trait that moved.

A hard strike can clip, and a clipped peak hides the velocity response:
FluidR3's TR-808 kit clips 17 of its 58 notes at velocity 100 and 127, so
read its response from the 40.
