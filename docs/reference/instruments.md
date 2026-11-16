# Instruments

Every instrument here is ready to play from `adapter.create()`: name it with
`voice=` and it answers the audio component contract, with its macros and
patches.

```python
import audioinstruments._rack.adapter as adapter

inst = adapter.create(48000, voice="poly106")
audio_out.play(inst.output)
inst.program_change(1)                           # Warm Pad
inst.note_on(60, 100)
```

Each page says how to play one instrument: its controls, its patches, what it
leaves out and what it costs on a desktop. What each costs on a board is in
[Boards](boards.md), and the same names, macros and patches as data, without
loading the audio stack, are in [the catalog](catalog.md). A SoundFont bank
you supply plays as `voice="soundfont"` or `voice="soundfont_drums"`
([Play a SoundFont](../guides/soundfont.md)).

## Polysynths

| `voice=` | Instrument |
| --- | --- |
| `poly106` | [Poly106](instruments/poly106.md): A six-voice poly synth inspired by the Roland Juno-106. |
| `poly5` | [Poly5](instruments/poly5.md): A five-voice two-oscillator poly synth inspired by the Sequential Prophet-5 (rev 3). |
| `poly6` | [Poly6](instruments/poly6.md): A six-voice poly synth inspired by the Korg Polysix. |
| `poly8` | [Poly8](instruments/poly8.md): An eight-voice two-oscillator poly synth inspired by the Roland Jupiter-8. |
| `polyxa` | [PolyXa](instruments/polyxa.md): An eight-voice two-oscillator poly synth inspired by the Oberheim OB-Xa. |
| `polya6` | [PolyA6](instruments/polya6.md): A sixteen-voice poly synth inspired by the Alesis Andromeda A6. |
| `poly80` | [Poly80](instruments/poly80.md): An eight-voice polysynth inspired by the Yamaha CS-80. |

## String machines

| `voice=` | Instrument |
| --- | --- |
| `string_ensemble` | [StringEnsemble](instruments/string_ensemble.md): A fully polyphonic divide-down string machine with one shared envelope, a monophonic bass and a three-phase ensemble, inspired by the ARP/Eminent Solina String Ensemble. |
| `vocoder330` | [Vocoder330](instruments/vocoder330.md): A fully polyphonic string, choir and ten-band vocoder keyboard, inspired by the Roland VP-330 Vocoder Plus. |

## Electric pianos

| `voice=` | Instrument |
| --- | --- |
| `electric_piano` | [ElectricPiano](instruments/electric_piano.md): A ten-voice tine electric piano inspired by the Fender Rhodes Suitcase 73. |
| `reed_piano` | [ReedPiano](instruments/reed_piano.md): A ten-voice plucked-reed electric piano inspired by the Hohner Pianet. |
| `reed_piano200a` | [ReedPiano200A](instruments/reed_piano200a.md): A ten-voice struck-reed electric piano inspired by the Wurlitzer 200A. |
| `clavichord` | [Clavichord](instruments/clavichord.md): A ten-voice struck-string electric clavichord with two pickups, four tone tabs and a mute, inspired by the Hohner Clavinet D6. |
| `electric_grand70` | [ElectricGrand70](instruments/electric_grand70.md): A ten-voice electric grand piano inspired by the Yamaha CP-70. |

## Organs

| `voice=` | Instrument |
| --- | --- |
| `tonewheel3` | [Tonewheel3](instruments/tonewheel3.md): A sixteen-voice tonewheel organ with nine drawbars, single-trigger percussion, key click, a scanner vibrato and chorus, an overdriven rotary speaker, inspired by the Hammond B-3. |
| `compact_organ` | [CompactOrgan](instruments/compact_organ.md): A fully polyphonic divide-down transistor combo organ with voice tabs, a bass section and a pitch vibrato, after the portable combo organs of the mid-1960s. |
| `combo_organ` | [ComboOrgan](instruments/combo_organ.md): A fully polyphonic divide-down transistor combo organ with footage drawbars, a mixture, two tone colours, a bass octave and a vibrato, inspired by the Vox Continental. |

## Mono and duo synths

| `voice=` | Instrument |
| --- | --- |
| `mono101` | [Mono101](instruments/mono101.md): A monophonic bass and lead synth inspired by the Roland SH-101. |
| `mono_synth` | [MonoSynth](instruments/mono_synth.md): A monophonic bass and lead synth inspired by the Moog Minimoog Model D. |
| `mono_one` | [MonoOne](instruments/mono_one.md): A voice inspired by the Sequential Pro-One: two VCOs with sync, a four-pole filter, two ADSRs, an LFO, glide, and the poly-mod matrix that sends the filter envelope and VCO B to VCO A's frequency and pulse width and to the filter cutoff. |
| `acid303` | [Acid303](instruments/acid303.md): A bass voice inspired by the Roland TB-303: saw or square VCO, the diode ladder with accent circuit, a decay envelope, slide, and a 16-step sequencer with gate, accent and slide per step. |
| `duo20` | [Duo20](instruments/duo20.md): A voice inspired by the Korg MS-20: two VCOs, a high-pass into a low-pass Sallen-Key pair with diode-clipped peak, two envelopes, a modulation generator, noise, sample and hold, and a patch panel. |
| `hybrid_mono` | [HybridMono](instruments/hybrid_mono.md): A voice inspired by the EDP Wasp: two DCOs, a CMOS multimode filter whose inverter stages clip, an envelope, an LFO and a VCA, with a small patch panel. |
| `patch2600` | [Patch2600](instruments/patch2600.md): A semi-modular voice inspired by the ARP 2600 (and Behringer's 2600): three VCOs, a ladder VCF, a VCA, two envelopes, ring modulator, noise, sample and hold, a voltage processor and a spring reverb. |
| `state_variable_mono` | [StateVariableMono](instruments/state_variable_mono.md): A voice inspired by the Oberheim SEM: two VCOs, a 12 dB multimode filter that morphs from low-pass through notch to high-pass (or switches to band-pass), two ADS envelopes, an LFO and a VCA, with a patch panel. |
| `west_coast_synth` | [WestCoastSynth](instruments/west_coast_synth.md): A West Coast voice inspired by the Buchla Music Easel: a complex oscillator (modulation and principal oscillators with FM or AM), a timbre wavefolder, two vactrol low-pass gates, two function generators and a random voltage source. |
| `bass_pedals` | [BassPedals](instruments/bass_pedals.md): A monophonic pedal bass synthesizer inspired by the Moog Taurus. |
| `duosynth` | [DuoSynth](instruments/duosynth.md): A duophonic two-oscillator synthesizer inspired by the ARP Odyssey. |

A mono synth plays one note at a time, so `create()` refuses `voices`, `max_voices` or `unison` above 1. The player can
choose `priority` (`"last"`, `"low"`, `"high"` or `"duo"`: which held key sounds) and
`retrigger` when creating the instrument or while it plays.

```python
import audioinstruments._rack.adapter as adapter

inst = adapter.create(48000, voice="mono101", priority="low")
inst.retrigger = True        # every key pulses the trigger, not only the first
```

The DuoSynth plays two keys at once on the `"duo"` priority. Legato, the note stack and portamento are in [Polyphony](../guides/polyphony.md#one-voice-mono-mode).

## Drum machines

| `voice=` | Instrument |
| --- | --- |
| `rhythm808` | [Rhythm808](instruments/rhythm808.md): An analog drum machine with sixteen sounds, one circuit per pad, inspired by the Roland TR-808. |
| `rhythm606` | [Rhythm606](instruments/rhythm606.md): An analog drum machine with seven sounds, inspired by the Roland TR-606. |
| `rhythm909` | [Rhythm909](instruments/rhythm909.md): A drum machine with eleven synthesized sounds, inspired by the Roland TR-909. |
| `rhythm78` | [Rhythm78](instruments/rhythm78.md): An analog preset rhythm machine with fifteen sounds, inspired by the Roland CR-78. |
| `electronic_drums5` | [ElectronicDrums5](instruments/electronic_drums5.md): An electronic drum kit with swept tones and noise hats, inspired by the Simmons SDS-V. |

```{toctree}
:hidden:

instruments/poly106
instruments/poly5
instruments/poly6
instruments/poly8
instruments/polyxa
instruments/polya6
instruments/poly80
instruments/string_ensemble
instruments/vocoder330
instruments/electric_piano
instruments/reed_piano
instruments/reed_piano200a
instruments/clavichord
instruments/electric_grand70
instruments/tonewheel3
instruments/compact_organ
instruments/combo_organ
instruments/mono101
instruments/mono_synth
instruments/mono_one
instruments/acid303
instruments/duo20
instruments/hybrid_mono
instruments/patch2600
instruments/state_variable_mono
instruments/west_coast_synth
instruments/bass_pedals
instruments/duosynth
instruments/rhythm808
instruments/rhythm606
instruments/rhythm909
instruments/rhythm78
instruments/electronic_drums5
```
