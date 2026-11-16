# Rhythm909

The Rhythm909 is an eleven-voice analog and hybrid drum machine with one circuit per
pad, inspired by the Roland TR-909 Rhythm Composer (1983). Its analog voices (bass drum,
snare, toms) use swept oscillators rather than pinged filters, giving them punch and
body that defined house and techno. The cymbals and hats synthesize the original's
sample-ROM character without shipping samples: the six-oscillator metallic bank passes
through the 909's resonant filters and a 6-bit quantization and sample-and-hold stage
at 32 kHz, capturing the iconic aliased sheen of the hardware.

```python
import audioinstruments._rack.adapter as adapter

inst = adapter.create(48000, voice="rhythm909")  # 11 voices, 1 per sound
audio_out.play(inst.output)
inst.program_change(0)                          # Classic 909
inst.note_on(36, 127)                           # Accented Bass Drum
inst.note_on(38, 100)                           # Snare Drum
```

## Sounds and circuits

The eleven sounds are mapped to General MIDI percussion keys:

| voice | sound | keys | panel controls |
|---|---|---|---|
| 0 | bass drum (BD) | 35, 36 | tune, level, attack, decay |
| 1 | rim shot (RS) | 37 | level |
| 2 | snare drum (SD) | 38, 40 | tune, level, tone, snappy |
| 3 | hand clap (CP) | 39 | level |
| 4 | closed hi-hat (CH) | 42, 44 | hh_level, ch_decay |
| 5 | open hi-hat (OH) | 46 | hh_level, oh_decay |
| 6 | low tom (LT) | 41, 43 | tune, level, decay |
| 7 | mid tom (MT) | 45, 47 | tune, level, decay |
| 8 | high tom (HT) | 48, 50 | tune, level, decay |
| 9 | crash (CR) | 49, 57 | level, tune |
| 10 | ride (RD) | 51, 59 | level, tune |

The **bass drum** sweeps an oscillator from 150-250 Hz down to 45-65 Hz over 30 ms.
`bd_attack` injects a sharp strike click pulse and high-frequency noise burst, while
`bd_decay` ranges from 100 to 900 ms.

The **snare drum** combines two swept oscillators near 180 and 330 Hz (`sd_tune`)
with filtered white noise whose cutoff is shaped by `sd_tone` and whose level is set
by `sd_snappy`.

The **toms** (low, mid, high) feature swept oscillators with deep downward pitch drops
and subtle membrane noise, spanning 80-120 Hz (LT), 120-180 Hz (MT), and 160-240 Hz (HT)
at rest with decay times from 150 to 800 ms.

The **rim shot** combines resonant tones near 220 Hz and 1.7 kHz through a high-pass filter
for a 20 ms click. The **hand clap** extends the 808 clap architecture with a brighter
1.3 kHz band-pass filter and a rougher, longer tail.

The **hi-hats and cymbals** derive from the six-oscillator metallic bank, high-passed
and shaped by one-shot decay envelopes (CH: 40-120 ms, OH: 150 ms-1.0 s, crash: 1.5-2.5 s,
ride: 2.0-3.0 s with a bell ping), then processed through a 6-bit quantization stage
with an anti-aliasing pre-filter and rate decimation at 32 kHz. On crash and ride, `tune`
moves the sample rate (24 to 40 kHz) and the metallic bank frequencies in lockstep.

## Choke, accent, and output

Closed and open hi-hats form a mutual choke group (`CHOKE = ((4, 5),)`): striking either
hat cuts off the other over a single block fade.

MIDI velocity provides the accent, scaled by `accent` (0 to 10, default 5.0). On the kick,
velocity also raises click intensity. `bits` (4 to 8, default 6) and `crush` (on/off)
allow dialing between vintage 6-bit grit and clean modern metal.

The output stage mixes all voices through `volume` and a soft tanh ceiling. `inst.latency_samples`
is 0.

## Patches and macros

Five presets cover the 909's production lineage:
- **Classic 909**: balanced factory configuration.
- **Detroit Techno**: high attack kick, snappy snare, high-tuned cymbals.
- **Chicago House**: jackin' house setup with boosted clap, snappy snare, and ringing open hat.
- **Hardcore**: slammed kick attack and decay, short snappy snare, saturated levels.
- **Clean Metal**: bypasses 6-bit crushing for pristine, high-fidelity cymbals.

The eight macros are `bd_attack`, `bd_decay`, `sd_snappy`, `sd_tune`, `ch_decay`, `oh_decay`,
`accent`, and `volume`.

`examples/rhythm909_demo.py` plays a 66-second, 128 BPM track across all five presets,
streaming audio to `wav_exports/rhythm909_demo.wav`.

## What it costs

`examples/poly_bench.py rhythm909` benchmarks all eleven voices sounding
simultaneously (struck every four buffers) across block sizes:

| block | CPython ms | factor | MicroPython ms | factor |
| ---: | ---: | ---: | ---: | ---: |
| 64 | 42.31 | 0.50 | 12.19 | 1.75 |
| 128 (default) | 21.33 | 1.00 | 7.56 | 2.82 |
| 256 | 11.33 | 1.88 | 5.02 | 4.25 |

When idle, parked voices take 0.10 ms per buffer on CPython (factor 214) and
0.27 ms on MicroPython (factor 78). On MicroPython, all eleven voices running
simultaneously execute comfortably in real time (2.82x at default 128-frame blocks).
