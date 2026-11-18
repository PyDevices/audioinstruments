# Vocoder330

The Vocoder330 is a keyboard with three sounds that play at once from the same
keys, inspired by the Roland VP-330 Vocoder Plus: **strings**, a **choir** made
by seven fixed formant filters, and a ten-band **vocoder** that puts the
spectrum of a microphone on the keyboard's tone. Every key sounds, the keyboard
splits at middle C, and a four-line ensemble makes it wide. It is made for
chords, played with two hands.

```python
import audioinstruments._rack.adapter as adapter
from audioinstruments._rack.instruments.vocoder330 import attach_mic

inst = adapter.create(48000, voice="vocoder330")   # 12 voices; voices=N up to 49
audio_out.play(inst.output)
inst.program_change(9)                             # Singing Vocoder
for note in (43, 55, 60, 64):                      # a left hand and a right hand
    inst.note_on(note, 100)
# The mic is off when fresh, so the vocoder patches are silent until they have a voice:
# inst.patch.set_control(inst.voice_pool, "mic_source", "test") for the built-in talker,
# attach_mic(inst, sample) for a mono sample. Neither runs with output="graph".
```

## The keys, and the split

There are `VOICES` (12) voices, up to `MAX_VOICES` (49) with
`create(voices=N)`: a voice here is one key. The pool steals the oldest when
you hold more keys than voices; twelve covers two hands and the tails, which a
new key cuts short anyway (see Release). There is no unison and no mono mode,
and `create()` refuses both. Velocity does nothing.

The keyboard is MIDI `LOWEST_KEY` (36) to `HIGHEST_KEY` (84), split at
`SPLIT_KEY` (60): a key below 60 is on the lower half, 60 and above on the
upper. A key outside the range is folded by octaves into it (35 sounds as 47, 85
as 73, so a 61- or 88-key controller plays every key). Each of the eight
tablets that belong to a half reaches the keys of its half only.

Each voice makes an 8' sawtooth at the key's pitch and a 4' an octave above it,
the 4' hard-synced to the 8' so the two stay locked in phase. They are written
to five mono buses (`strings`, `choir_a`, `choir_b`, `choir_c`, `carrier`) that
the shared section filters once for the whole keyboard, which is why a chord
costs the filters once and not once a key. [polyphony.md](../../guides/polyphony.md#buses)
has the buses, which the graph compiles to `MIX` chains. A voice writes a tone at `BUS_LEVEL` (0.5) so twelve keys that start
together stay inside the 16-bit wire.

## Strings

`strings_upper` and `strings_lower` send the 4' tone of that half's keys to the
strings bus, through the strings envelope. `strings_attack` runs from
`ATTACK_MIN_S` (0.005) to `ATTACK_MAX_S` (3.0) seconds, exponential, corrected
by `ATTACK_TO_PEAK` (0.51) so it is the time to the peak. `strings_tone` is a
12 dB per octave low-pass on the strings' sum, `TONE_MIN_HZ` (800.0) to
`TONE_MAX_HZ` (12000.0), exponential. The strings always go through the
ensemble: a string machine's strings are its ensemble.

## The choir

Four tablets: `voice_upper_female4` (the 4' tone of upper keys),
`voice_upper_male8` (8', upper), `voice_lower_male4` (4', lower) and
`voice_lower_male8` (8', lower). The choir is made by seven band-pass filters
at `CHOIR_FILTERS_HZ` (200.0, 230.0, 600.0, 900.0, 1300.0, 2800.0, 3300.0), each at
`CHOIR_Q` (4.0), once for the keyboard. A voice writes three choir buses by
which filters its tablet needs: `choir_a` (lower male 8': F1, F3, F4, F6),
`choir_b` (lower male 4' and upper male 8': F2, F3, F4, F6) and `choir_c` (upper
female 4': F3, F4, F5, F7). Each filter is fed the sum of the buses that use it,
and a filter whose inputs were silent this block and last does not run. The
choir has its own attack, `voice_attack`, over the same range as the strings',
and goes through the ensemble if `voice_ensemble` is on.

## The vocoder

`vocoder_upper` and `vocoder_lower` send the 8' tone of that half's keys to the
carrier bus, through a carrier envelope whose attack is fixed at
`VOCODER_ATTACK_S` (0.005) seconds: the vocoder has no attack control. The bank
splits the mic and the carrier into ten bands at `BAND_HZ` (200.0, 280.0, 400.0, 600.0,
900.0, 1300.0, 2000.0, 2800.0, 4000.0, 6000.0), each two band-pass stages
(`BAND_STAGES`, 2) at `BAND_Q` (2.5): a Q high enough that the bands stay apart,
low enough that the sum ripples by a few decibels. A follower on each mic band
rises over `FOLLOW_ATTACK_S` (0.005) seconds and falls over `FOLLOW_RELEASE_S`
(0.03), and the matching carrier band is multiplied by it, its gain ramped across
the block so it does not buzz at the block rate. The ten are summed at
`VOCODER_GAIN` (28.0).

There is no sound until you speak while a key is down, and with a long release
you keep speaking after you let go. `vocoder_tone` adds the consonants: the mic
through a high-pass of `CONSONANT_STAGES` (2) stages at `CONSONANT_HZ` (4000.0),
at up to `CONSONANT_GAIN` (1.0), but only while the carrier sounds, so an "s"
comes through with a key down and never without one. **Design choice:** the
original's TONE control is read as this level.

`vocoder_hold` freezes the spectrum: the followers stop listening and each level
falls by `exp(-block_seconds / HOLD_SAG_S)` a block, `HOLD_SAG_S` (2.5) seconds
to fall by a factor of e, so keys pressed during the hold sound the held vowel
and it fades over a few seconds. It is a control here; CC 64 stays the sustain
pedal. A band whose level is below `SKIP_LEVEL` (0.0001) is not synthesised, and
with neither vocoder tablet on nothing in the bank runs. The compander and the
pre-emphasis around a hardware vocoder's bank cancel in floating point, so they
are not built.

## The voice the vocoder listens to

the rack's instruments have no audio input, so the mic is built in, and
`mic_source` picks where it comes from:

- `"off"` (fresh): silence, and so a silent vocoder, with the strings and the
  choir playing. It is the one source a board's audio pump can play: all the
  others render in Python, so an instrument on `output="graph"` raises
  `ValueError` for them; give it one with `output="ring"`. Robot Voice, Singing
  Vocoder and Whisper Vocoder are silent until they have a voice.
- `"test"`: a built-in talker, so the vocoder sounds in tests and
  renders with no file and no hardware. A glottal sawtooth at `TALKER_F0`
  (110.0) Hz through three formant filters at `TALKER_FORMANT_Q` (5.0), saying
  six syllables on a loop of `TALKER_PHRASE_S` (2.4) seconds. The vowels are
  Peterson and Barney's (1952) averages for men, and a burst of noise seeded
  with `TALKER_SEED` (330) comes before two of the syllables. It is the same
  samples every run, and the phrase starts again on `reset()`. The talker, its
  phrase and its level are design choices.
- `"input"`: a sample. `attach_mic(inst, sample)` takes any mono audiodsp
  sample at the instrument's rate (a `WaveFile`, a `RawSample`) and raises
  `ValueError` for a stereo one or one at another rate. The first block of the
  sample is lost to the bridge that pulls it, and a finished sample gives
  silence. `attach_mic(inst, None)` detaches it, and with none attached
  `"input"` reads the mic module's `mic_in` jack, so a rack patched by hand can
  feed it. On the graph the mic is a `Fragment.fed` module: it renders in
  Python each block and feeds the graph, so a Vocoder330 with a source plays
  under `step()`. The live input is proven with files only; a board's microphone is not
  tried.

`mic_level` is the mic's gain, `MIC_GAIN_AT_10` (4.0) times `(mic_level / 10) ** 2`:
1.0 at the fresh 5. The bank, the consonants and the direct mic all read the mic
after this gain. The talker only runs while something reads the mic.

## Release, and the tail cut

`release` is for all three envelopes, `RELEASE_MIN_S` (0.05) to `RELEASE_MAX_S`
(6.0) seconds, exponential. When a key goes down, every key that has been let go
cuts its release to `TAIL_CUT_S` (0.05) seconds, so changing chords under a long
release does not pile the old chord's tail under the new one. Keys still held
are not touched, and a tail with no new key rings on.

## Vibrato

The choir and the vocoder (not the strings) pass through a vibrato: a delay line
swept by a sine. `vib_depth` is the pitch swing at 10, `VIB_MAX_SEMITONES` (0.5)
either way; the delay swing is worked out each block from the depth and the
rate (a delay swing of `dev / (2 pi rate)` for a pitch swing `dev`), so the depth
you hear does not change with the rate. `vib_rate` runs `VIB_MIN_HZ` (2.0) to
`VIB_MAX_HZ` (9.0), exponential. `vib_delay` is linear from 0 to
`VIB_DELAY_MAX_S` (3.0) seconds: after a key goes down with no key held, the
vibrato stays at nothing for the delay, then rises over `VIB_FADE_S` (0.3)
seconds, and a key pressed while another is held does not start it again.

## The ensemble

Four delay lines, two a side, built from the same `EnsembleCore` as the
StringEnsemble's: line A sweeps with a slow triangle of `ENSEMBLE_SLOW_S` (3.9, 4.6)
seconds (A and B), each carrying `ENSEMBLE_FAST_CYCLES` (26) fast sines (150 ms
and 176.9 ms), around a centre delay of `ENSEMBLE_CENTRE_MS` (4.0), with swings of
`ENSEMBLE_SLOW_MS` (1.6) and `ENSEMBLE_FAST_MS` (0.12) milliseconds, damped at
`ENSEMBLE_TONE_HZ` (8000.0). The right side's sweeps are the left's upside down.
The first line of a side is the dry plus its wet and the second its wet alone,
each at `ENSEMBLE_LEVEL` (0.3333) into its side: that is the EnsembleCore's line
level, and with the dry share a side sums to unity. The strings go through it
always; the choir and the vocoder go through it when `voice_ensemble` or
`vocoder_ensemble` is on, and through a plain delay of the same length when not,
so the sides are then the same sample for sample.

## Pitch shift and tuning

`pitch_mode` is `"off"`, `"auto"` or `"manual"` (the foot-switch position of the
original is not built). `pitch_set` runs 0 to `PITCH_SET_MAX_SEMITONES` (13.0)
semitones. In `"auto"` every key that goes down restarts one swoop for the whole
keyboard: the pitch jumps to minus `pitch_set` and rises in a straight line to
nothing over `pitch_time`, `PITCH_TIME_MIN_S` (0.03) to `PITCH_TIME_MAX_S` (2.0)
seconds, exponential, written as a ramp across each block. Held keys dip with the
new one, since the original has one master oscillator. In `"manual"` the pitch
bend is the slider, by `pitch_set` semitones both ways (the MIDI module's
`bend_range`, which it will not set under `BEND_RANGE_MIN` (1.0), so a
`pitch_set` under 0.8 still bends a semitone); in the other two positions the
voices play the note without the bend. `tune` is -`TUNE_RANGE_CENTS` (50.0) to
+50 cents on every section.

## Balance, and the output

`strings_level` is the strings, `voice_level` the choir and the vocoder (the
original's balance has no vocoder level), `direct_mic` the mic as it comes in,
after its gain, with no vocoder, vibrato or ensemble. All three are linear,
`LEVEL_SCALE` (0.1) a step; the strings' sum is scaled by `STRINGS_GAIN` (2.0)
and the choir's by `CHOIR_GAIN` (2.5) first. The output ends in a DC block, a
high-pass at `DC_HZ` (10.0). MASTER VOLUME is the adapter's level; the mono
output and the phones are not built.

Every path comes out `LATENCY_SAMPLES` (656) frames late: the vibrato's line and
the ensemble's are `LATENCY_FRAMES` (256) each, and the vibrato's centre delay,
`VIB_CENTRE_MS` (3.0), is 144 frames at 48 kHz (`VIB_CENTRE_FRAMES`, 144).
The strings, the plain-delay path and the direct mic are delayed to match, so
the sections stay aligned and a tablet switched while a note sounds never jumps
in time. With the ensemble on, the first sound of an impulse is the dry share of
each side's first line, at exactly that delay; the wet lines follow a few
milliseconds later.

## The filters

The band-passes are `synthio.Biquad` through `audiofilters.Filter`, in
audiodsp's widened arithmetic. They settle to exact zero when the input stops
and carry no constant offset, so nothing in the rack removes one.

## Where the numbers come from

**Sources** (page numbers as printed): the *VP-330 Owner's Manual* (Roland, July
1980) [OM], the *VP-330 Service Notes*, first edition, 21 September 1979 [S79]
and second edition, 25 October 1980 [S80], the Wikipedia article on the
VP-330 and zoeblade's VP-330 notes. They give: 49 keys, C to C [OM p.10]; the
keyboard split at the centre and the four buses (upper 8', upper 4', lower 8',
lower 4') [S79 p.7, p.13]; the strings' attack and tone, and the human voice's
attack and ensemble tablet [OM p.4, p.6, p.10]; seven human-voice tone filters at
200, 230, 600, 900, 1300, 2800 and 3300 Hz, and which four each voice uses [S79
p.12 and the secondary sources]; one RELEASE control for all three sections [OM
p.10]; the new key that clears the release of keys already let go, in about 50 ms
[S80 p.3]; ten analysing band-passes at 200, 280, 400, 600, 900, 1300, 2000, 2800, 4000
and 6000 Hz [S79 p.10]; the vocoder that is silent until you speak [OM p.7]; the
hold [OM p.7, S79 p.5]; vibrato for the human voice and the vocoder, not the
strings, with depth, delay and rate [OM p.6]; an ensemble of bucket-brigade lines
with slow triangles of 3.9 and 4.6 s and fast sines of 150 and 175 ms, two lines a
channel [S79 p.9, S80 p.2]; pitch shift with AUTO and MANUAL modes [OM p.5]; the
tuning range of 50 cents [OM p.10].

**Design choices**, which no source states: the voice count; the folding of keys;
the 4' locked to the 8'; the band Q and stages; the followers' times; the
vocoder carrier's fixed attack; the consonant path's corner and gate; the hold's
sag time within the 2 to 3 seconds the notes give; the ensemble's depths, centre
delay and dry share; the vibrato's depth range and fade; pitch bend as the manual
slider, both ways; the swoop moving the whole keyboard; A at 440 Hz; the talker
and its level; the latency being 656 and not 512; the ranges of the sliders that
have no source; every patch.

**Not built.** The external synthesizer input (the carrier is always the
keyboard), the EXT CONT pitch shift and the hold pedal, a live board microphone,
the mono output, the output level switch and the phones.

## Routing table

Every route the instrument wires, the control that sets it, its range or depth
and the constant that sets that (in the modules under
`lib/audioinstruments/_rack/modules/vocoder330/`, the patch in `lib/audioinstruments/_rack/instruments/vocoder330.py`
and the lines in `lib/audioinstruments/_rack/dsp/ensemble.py`). Pitch is CV at 0.1 per octave.

| Route | Control | Range or depth | Constant | Test |
| --- | --- | --- | --- | --- |
| `split` | the eight tablets of a half | keys below 60 lower, 60 and above upper | `SPLIT_KEY` (60) | `test_route_split` |
| `key_fold` | none | a key outside 36 to 84 sounds in it by octaves | `LOWEST_KEY` (36), `HIGHEST_KEY` (84) | `test_route_key_fold` |
| `footage` | none | 8' at the key, 4' an octave above, locked | `BUS_LEVEL` (0.5) | `test_route_footage` |
| `strings_path` | `strings_upper`, `strings_lower`, `strings_tone`, `strings_level` | 800 Hz to 12 kHz low-pass; level 0.1 a step | `TONE_MIN_HZ` (800.0), `TONE_MAX_HZ` (12000.0), `STRINGS_GAIN` (2.0) | `test_route_strings_path` |
| `choir_matrix` | the four choir tablets | each tablet's four filters of seven | `CHOIR_FILTERS_HZ` (200.0, 230.0, 600.0, 900.0, 1300.0, 2800.0, 3300.0), `CHOIR_Q` (4.0), `CHOIR_GAIN` (2.5) | `test_route_choir_matrix`, `test_route_choir_matrix_from_the_buses` |
| `envelopes` | `strings_attack`, `voice_attack`, `release` | 5 ms to 3 s; carrier 5 ms; release 50 ms to 6 s | `ATTACK_MIN_S` (0.005), `ATTACK_MAX_S` (3.0), `VOCODER_ATTACK_S` (0.005), `RELEASE_MIN_S` (0.05), `RELEASE_MAX_S` (6.0) | `test_route_envelopes`, `test_route_envelopes_share_the_release` |
| `tail_cut` | none | a new key cuts released keys to 50 ms | `TAIL_CUT_S` (0.05) | `test_route_tail_cut` |
| `vocoder_carrier` | `vocoder_upper`, `vocoder_lower` | the 8' tone of the half | `VOCODER_GAIN` (28.0) | `test_route_vocoder_carrier` |
| `vocoder_bands` | `mic_level` | ten bands, two stages at Q 2.5 | `BAND_HZ` (200.0, 280.0, 400.0, 600.0, 900.0, 1300.0, 2000.0, 2800.0, 4000.0, 6000.0), `BAND_Q` (2.5), `FOLLOW_ATTACK_S` (0.005), `FOLLOW_RELEASE_S` (0.03) | `test_route_vocoder_bands` |
| `vocoder_needs_both` | `mic_source` | no key or no voice, no sound | `SKIP_LEVEL` (0.0001) | `test_route_vocoder_needs_both` |
| `consonant` | `vocoder_tone` | high-pass at 4 kHz, only while the carrier sounds | `CONSONANT_HZ` (4000.0), `CONSONANT_GAIN` (1.0), `GATE_SMOOTH_S` (0.01) | `test_route_consonant` |
| `hold` | `vocoder_hold` | the levels fall by a factor of e in 2.5 s | `HOLD_SAG_S` (2.5) | `test_route_hold` |
| `vibrato` | `vib_depth`, `vib_rate`, `vib_delay` | 0.5 semitone; 2 to 9 Hz; 0 to 3 s, then 0.3 s | `VIB_MAX_SEMITONES` (0.5), `VIB_MIN_HZ` (2.0), `VIB_MAX_HZ` (9.0), `VIB_DELAY_MAX_S` (3.0), `VIB_FADE_S` (0.3) | `test_route_vibrato_depth_is_the_same_at_both_ends_of_the_rate`, `test_route_vibrato_is_for_the_choir_and_the_vocoder_not_the_strings`, `test_route_vibrato_waits_for_its_delay_then_fades_in` |
| `ensemble_select` | `voice_ensemble`, `vocoder_ensemble` | strings always; four lines of 3.9 and 4.6 s | `ENSEMBLE_SLOW_S` (3.9, 4.6), `ENSEMBLE_CENTRE_MS` (4.0), `ENSEMBLE_SLOW_MS` (1.6), `ENSEMBLE_FAST_MS` (0.12), `ENSEMBLE_LEVEL` (0.3333) | `test_route_ensemble_select` |
| `pitch_shift` | `pitch_mode`, `pitch_set`, `pitch_time` | 0 to 13 semitones; 30 ms to 2 s | `PITCH_SET_MAX_SEMITONES` (13.0), `PITCH_TIME_MIN_S` (0.03), `PITCH_TIME_MAX_S` (2.0) | `test_route_pitch_shift_auto_dips_every_sounding_key_on_each_press`, `test_route_pitch_shift_manual_bends_by_pitch_set_both_ways_and_off_ignores_it`, `test_route_pitch_shift_moves_the_bend_range_with_pitch_set` |
| `tune` | `tune` | -50 to +50 cents | `TUNE_RANGE_CENTS` (50.0) | `test_route_tune` |
| `balance` | `strings_level`, `voice_level`, `direct_mic` | 0.1 a step | `LEVEL_SCALE` (0.1) | `test_route_balance_each_level_scales_only_its_own_section` |
| `latency` | none | 656 frames, every path, both sides | `LATENCY_FRAMES` (256), `VIB_CENTRE_MS` (3.0), `LATENCY_SAMPLES` (656) | `test_route_latency` |
| `mic_source` | `mic_source`, `mic_level` | the quadratic gain, 1.0 at 5 | `MIC_GAIN_AT_10` (4.0) | `test_route_mic_source` |

## Patches and macros

There are twelve patches: Init, String Ensemble, Bright Strings, Male Choir,
Female Choir, Full Choir, Strings and Choir, Choir Under Strings, Robot Voice,
Singing Vocoder, Whisper Vocoder and Swooping Choir. Every patch's attacks are
1.2 s or less and every patch's four-key chord sits within 3 dB of the median.
Whisper Vocoder plays a little of the dry mic on purpose, so it speaks with no
key down; the other vocoder patches are silent without one. The ten macros are
`strings_attack`, `strings_tone`, `voice_attack`, `release`, `vocoder_tone`,
`mic_level`, `vib_depth`, `vib_rate`, `vib_delay` and `pitch_time`, each
covering its control's whole range. Set any control by its name in
`audioinstruments._rack.instruments.vocoder330.SETTINGS` with
`inst.patch.set_control(inst.voice_pool, name, value)`.

`examples/vocoder330_demo.py` plays all twelve in order, mostly with two hands
across the split, writes `wav_exports/vocoder330_demo.wav`, and checks that every
section sounds, nothing clips, and each has at least a quarter of its power at
120 Hz and above and a tenth or less below 40 Hz, so it can be heard on small
speakers. `examples/poly_render.py vocoder330` checks that a stolen voice does
not click.

## What it costs

`examples/poly_bench.py vocoder330` renders 1024-frame buffers with all twelve
voices held on the Init patch (on [the desktop the other figures come from](../../how-it-works/performance.md#the-desktop-the-figures-come-from)):

| block | CPython ms | factor | MicroPython ms | factor |
| ---: | ---: | ---: | ---: | ---: |
| 64 | 28.8 | 0.74 | 12.8 | 1.67 |
| 128 (the default) | 15.3 | 1.39 | 7.6 | 2.80 |
| 256 | 8.2 | 2.59 | 5.0 | 4.30 |

The vocoder patches cost more, since the bank is twenty filter calls a block:
on CPython a four-key chord on Robot Voice, Singing Vocoder and Whisper Vocoder
renders at about 1.05 to 1.2 times real time at the default block.
