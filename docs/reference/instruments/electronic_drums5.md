# ElectronicDrums5

The ElectronicDrums5 is an electronic drum kit with swept analog tones,
inspired by the Simmons SDS-V (1981). Its iconic hexagonal pads, sweeping tom fills,
and punchy transients powered early 1980s pop, new wave, and electronic rock.
A drummer plays it dynamically from velocity-sensitive pads, with separate analog
voice channels for the bass drum, snare drum, and three toms, plus the optional
hi-hat and cymbal modules: closed hat, open hat, and cymbal.

```python
import audioinstruments._rack.adapter as adapter

inst = adapter.create(48000, voice="electronic_drums5")   # 8 voices, 1 per channel
audio_out.play(inst.output)
inst.program_change(0)                           # Classic
inst.note_on(36, 127)                            # Accented Bass Drum
inst.note_on(38, 100)                            # Snare Drum
inst.note_on(48, 127)                            # High Tom
```

## Sounds and circuits

Each channel combines an oscillator whose pitch dives rapidly after the strike
(triangle shaped toward a sine), white noise through a low-pass filter (modeled on the
SSM2044 VCF), and an initial strike click pulse, all governed by one exponential
amplitude decay envelope. The closed hat, open hat, and cymbal have the same controls,
but their noise goes through a high-pass filter, and their tone and click start at 0.

The eight channels map to General MIDI percussion keys:

| voice | channel | General MIDI keys | panel controls |
|---|---|---|---|
| 0 | bass drum (BD) | 35, 36 | bd_tone, bd_noise, bd_pitch, bd_bend, bd_decay, bd_filter, bd_click |
| 1 | snare drum (SD) | 37, 38, 39, 40 | sd_tone, sd_noise, sd_pitch, sd_bend, sd_decay, sd_filter, sd_click |
| 2 | tom 1 / high tom (T1) | 48, 50 | t1_tone, t1_noise, t1_pitch, t1_bend, t1_decay, t1_filter, t1_click |
| 3 | tom 2 / mid tom (T2) | 45, 47 | t2_tone, t2_noise, t2_pitch, t2_bend, t2_decay, t2_filter, t2_click |
| 4 | tom 3 / low tom (T3) | 41, 43 | t3_tone, t3_noise, t3_pitch, t3_bend, t3_decay, t3_filter, t3_click |
| 5 | closed hi-hat (CH) | 42 | ch_tone, ch_noise, ch_pitch, ch_bend, ch_decay, ch_filter, ch_click |
| 6 | open hi-hat (OH) | 46 | oh_tone, oh_noise, oh_pitch, oh_bend, oh_decay, oh_filter, oh_click |
| 7 | cymbal (CY) | 49 | cy_tone, cy_noise, cy_pitch, cy_bend, cy_decay, cy_filter, cy_click |

The **bass drum** tone rests near 42-78 Hz (60 Hz at the middle setting) with a short 35 ms downward
bend from an octave above, a strong strike click, subtle filtered noise, and an
amplitude decay of 300 to 500 ms.

The **snare drum** rests near 150-270 Hz (210 Hz at the middle setting) with a tight 25 ms bend and a
prominent burst of white noise through a high-cutoff low-pass filter (1.5 to 9.5 kHz)
for an aggressive, bright crack decaying in 200 to 300 ms.

The **toms** (high, mid, low) rest near 220 Hz (T1), 160 Hz (T2), and 110 Hz (T3). Each
tom strikes an octave to an octave and a half higher and bends downward over 200 to 240 ms,
blended with a touch of filtered noise and moderate attack click over a 400 to 800 ms decay.
A fill rolling down the three toms produces the signature diving pitch sweep of 1980s drums.

The **hi-hats** are white noise through a high-pass filter (1.5 to 7.5 kHz, 4.5 kHz at the
middle setting), falling 40 dB in 50 ms when closed and 550 ms when open. The **cymbal** is
the same with a lower corner (1 to 5 kHz, 3 kHz at the middle setting) and an 800 ms fall.

## Velocity, choke, and output

Strikes respond dynamically to MIDI velocity, scaled by `sensitivity` (0 to 10, default 5.0).
At sensitivity 10, a soft hit at velocity 40 sits about 18 dB below velocity 127 and bends
half as far in pitch, capturing the expressive response of the original velocity-sensitive
pads. At sensitivity 0, level and bend depth remain constant across velocities.

The closed and open hi-hats choke each other (`CHOKE = ((5, 6),)`), as one pedal-switched
circuit does; the other channels ring freely. Striking a ringing channel again takes the new
strike over the sound that is still ringing: the oscillator keeps its phase, the level
carries on from where it was, the pitch bends down again from the top, and the strike
click sounds again, as it does on every hit. Master volume
(`volume`, default 7.0) and a soft ceiling tanh saturation stage protect the shared mono
output stage against hard clipping when all eight channels are struck simultaneously.
`inst.latency_samples` is 0.

## Patches and macros

Five presets cover classic electronic drum voicings:
- **Classic**: The factory 1984 kit with sweeping toms and balanced punch.
- **Deep Toms**: Lower resting pitches with extended pitch bends and longer decays.
- **Electro**: Fast decays, heavy strike clicks, and a tight snare crack.
- **Syndrum**: High tone mix, minimal noise, and deep bends for disco toms.
- **Gated**: Short, abrupt decays on snare and toms evoking 1980s gated room reverb.

The eight macros are `t1_bend`, `t1_decay`, `sd_noise`, `sd_filter`, `bd_click`,
`bd_decay`, `sensitivity`, and `volume`. `t1_bend` and `t1_decay` move all three toms
together: tom 1 goes to the knob's value and the other two move by the same amount, so a
patch whose toms differ keeps those differences. A tom that reaches 0 or 10 stops there and
comes back to its offset when you turn the knob back.

`examples/electronic_drums5_demo.py` demonstrates all five presets across five 16-step
grooves in 55 seconds, streaming audio to `wav_exports/electronic_drums5_demo.wav`.

## What it costs

`examples/poly_bench.py electronic_drums5` benchmarks all eight channels sounding
simultaneously (struck every four buffers) across block sizes:

| block | CPython ms | factor | MicroPython ms | factor |
| ---: | ---: | ---: | ---: | ---: |
| 64 | 0.73 | 29.2 | 1.12 | 19.1 |
| 128 (default) | 0.65 | 32.8 | 1.03 | 20.7 |
| 256 | 0.56 | 38.4 | 0.97 | 22.1 |

These are the compiled graph on a desktop, per 1024-frame buffer; a busy machine reads
lower. When idle, parked voices take 0.04 ms per buffer on CPython (factor 519) and 0.14 ms
on MicroPython (factor 148).
