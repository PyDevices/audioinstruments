# Rhythm78

The Rhythm78 is a fifteen-voice analog preset drum machine inspired by the Roland
CR-78 CompuRhythm (1978). Its warm, rounded sounds defined late-1970s pop, disco,
and early new wave: soft bridged-T resonators for the bass drum, snare, and toms,
pure white-noise hiss for the hi-hats and cymbal, and a rich palette of analog Latin
percussion including maracas, claves, cowbell, tambourine, and guiro.

```python
import audioinstruments._rack.adapter as adapter

inst = adapter.create(48000, voice="rhythm78")   # 15 voices, 1 per sound
audio_out.play(inst.output)
inst.program_change(0)                           # CompuRhythm
inst.note_on(36, 127)                            # Accented Bass Drum
inst.note_on(38, 100)                            # Snare Drum
```

## Sounds and circuits

The fifteen sounds are mapped to General MIDI percussion keys:

| voice | sound | keys | panel controls |
|---|---|---|---|
| 0 | bass drum (BD) | 35, 36 | bd_level |
| 1 | snare drum (SD) | 38, 40 | sd_level |
| 2 | rim shot (RS) | 37 | rs_level |
| 3 | hi-hat (HH) | 42, 44 (closed), 46 (open) | hh_level |
| 4 | cymbal (CY) | 49, 51, 57 | cy_level |
| 5 | maracas (MA) | 70 | ma_level |
| 6 | claves (CL) | 75 | cl_level |
| 7 | cowbell (CB) | 56 | cb_level |
| 8 | tambourine (TB) | 54 | tb_level |
| 9 | guiro short (GS) | 73 | gu_level |
| 10 | guiro long (GL) | 74 | gu_level |
| 11 | high bongo (HB) | 60 | hb_level |
| 12 | low bongo (LB) | 61 | lb_level |
| 13 | low conga (LC) | 62, 63, 64 | lc_level |
| 14 | metal beat (MB) | 55 | mb_level |

The **bass drum** is a soft, deep bridged-T resonator tuned near 54 Hz with a gentle
90-cent downward bend and a soft 220 ms decay. Unlike punchy 808 or 909 kicks, it has
no high-pass click transient.

The **snare drum** combines two low bridged-T resonance rings near 190 Hz and 290 Hz
with high-passed white noise (1.8 kHz cutoff) for a warm, pillowy snare strike.

The **rim shot** ping uses a bridged-T filter tuned near 420 Hz with a steep 120-cent
downward bend and a tight 35 ms decay.

The **hi-hats and cymbal** share a pure white-noise source passed through a sharp
7.2 kHz high-pass filter: closed hat has a tight 40 ms decay, open hat rings for
220 ms, and the cymbal adds a wide 5.5 kHz band-pass for a shimmering 650 ms tail.

The **bongos and conga** use bridged-T ringing filters with characteristic upward
pitch sweeps on strike (+180 cents for low bongo at 160 Hz, +220 cents for high bongo
at 300 Hz, +140 cents for low conga at 110 Hz).

The **cowbell** sums two narrow band-pass filtered square waves at 540 Hz and 800 Hz
into a shared 120 ms ring.

The **tambourine** fires a rapid cluster of three 12 ms noise bursts followed by a
decaying tail at 7.5 kHz high-pass, capturing rattling metal jingles.

The **maracas** produce a single crisp 22 ms burst of high-passed noise at 6.5 kHz.

The **claves** resonate pure wood with a bridged-T tone at 2.4 kHz decaying in 40 ms.

The **guiro** generates textured scrape bursts (40 ms for short, 110 ms for long)
by clocking a low-frequency pulse train into decaying noise bursts.

The **metal beat** is a 600 Hz square wave high-passed at 4 kHz, so only the upper
harmonics of its edges come through, with a 1 ms rise and an 80 ms decay.

## Choke and additions

Closed hi-hat (keys 42, 44) and open hi-hat (key 46) share voice 3, so a closed hat
retriggers it and cuts a ringing open hat without clicking. Because they share a voice, no
adapter-level choke group is required (`CHOKE = ()`). The cymbal has its own voice and
rings on through them. Re-striking any drum voice similarly resets its envelope and core
cleanly.

The panel adds individual voice level trimmers (`bd_level`, `sd_level`, etc.),
`balance` (shifting level between the drum voices and the hat/cymbal group),
`tone` (a low- and high-shelf tilt filter around 1 kHz), and velocity `accent`.

## Patches and macros

Four presets provide distinct voicings:
- **CompuRhythm**: factory CR-78 tuning and balance, warm and intimate.
- **Bossa**: lowered percussion decays and elevated Latin percussion levels.
- **Disco**: brighter tone tilt, boosted hats, punchier kick and snare.
- **Dark**: warm rolled-off tone, longer decays, softer percussion.

The six macros are `balance`, `accent`, `tone`, `bd_level`, `hh_level`, and `volume`.

`examples/rhythm78_demo.py` demonstrates all four presets across four classic
patterns in 58 seconds, streaming audio to `wav_exports/rhythm78_demo.wav`.

## What it costs

`examples/poly_bench.py rhythm78` benchmarks all fifteen voices sounding
simultaneously (struck every four buffers) across block sizes:

| block | CPython ms | factor | MicroPython ms | factor |
| ---: | ---: | ---: | ---: | ---: |
| 64 | 0.76 | 28.0 | 1.38 | 15.5 |
| 128 (default) | 0.83 | 25.8 | 1.20 | 17.7 |
| 256 | 0.79 | 26.8 | 1.15 | 18.5 |

These are the compiled graph on a desktop, per 1024-frame buffer. When idle, parked voices
take 0.07 ms per buffer on CPython (factor 318) and 0.21 ms on MicroPython (factor 100).
