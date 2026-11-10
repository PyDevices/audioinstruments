# Your first program

This plays middle C on the Poly106, a six-voice synth inspired by the Roland
Juno-106, and prints what it makes. You need the setup from
[Install](install.md).

```python
import audiocore
import audioinstruments

inst = audioinstruments.create("poly106", 48000)
print(inst.macro_labels[:4])
inst.note_on(60, 100)
for n in range(6):
    inst.fill()
    result, data = audiocore.get_buffer(inst.output, False, 0)
    samples = memoryview(bytes(data)).cast("h")
    print(n, max(abs(s) for s in samples))
inst.deinit()
```

Save it as `example.py` in the checkout and run it with
`PYTHONPATH=lib .venv/bin/python example.py`. It prints the instrument's first
four knobs, then the loudest sample of each buffer as the note sounds:

```text
('vcf_freq', 'vcf_res', 'vcf_env', 'env_attack')
0 3673
1 5483
2 4779
3 4561
4 4411
5 4233
```

`create` takes an instrument's name and a sample rate. `note_on(60, 100)` is
MIDI note 60 at velocity 100. `fill()` renders a block; on MicroPython you
call it every 10 to 20 ms while an instrument plays. `inst.output` is the
audio component's output, which `audio_out.play(inst.output)` sends to a
speaker on a board. `deinit()` frees the voices.

To hear instruments, `python examples/play_audio.py --no-live --wav` renders a short
movement for each of twenty instruments into `wav_exports/`. The other instruments are in
[Instruments](../reference/instruments.md), and
[Play chords and drive an instrument](../guides/polyphony.md) goes on from
here.
