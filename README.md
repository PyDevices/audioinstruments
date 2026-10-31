![One note through a patch of VCO, filter and amplifier, rendered by vrack](docs/images/note.png)

vrack is a virtual Eurorack modular synthesizer: twenty modules inspired by classic instruments, with panels and patch cables, rendered a block at a time on OmniPython's [audiodsp](https://github.com/PyDevices/audiodsp), on CPython and on MicroPython-compatible firmware.

## Install

You need Python 3.12 or later, numpy and audiodsp (from TestPyPI until its release):

```sh
uv venv --seed --python 3.12 .venv
uv pip install --python .venv/bin/python -i https://test.pypi.org/simple/ \
    --extra-index-url https://pypi.org/simple/ omnipython-audiodsp numpy
git clone https://github.com/bdbarnett/vrack && cd vrack
```

## Try it

```python
from vrack import MidiCVModule, Modular100VCO, Modular100VCF, Modular100VCA, Modular100EnvLFO, Rack

rack = Rack(sample_rate=48000, block_size=64)
midi, vco, vcf, vca, env = (rack.add_module(m) for m in (
    MidiCVModule("midi"), Modular100VCO("vco"), Modular100VCF("vcf"),
    Modular100VCA("vca"), Modular100EnvLFO("env")))
rack.connect(midi.pitch_out, vco.vco1_pitch_in)
rack.connect(midi.gate_out, env.env1_gate_in)
rack.connect(vco.vco1_saw_out, vcf.vcf1_audio1)
rack.connect(env.env1_out, vcf.vcf1_mod2)
rack.connect(vcf.vcf1_out, vca.vca1_audio1)
rack.connect(env.env2_out, vca.vca1_mod1)
rack.connect(vca.vca1_out, rack.master_left_in)
vcf.set_param("vcf1_cutoff", 0.45)
midi.note_on(60, 100)
for block in range(8):
    rack.step()
    print(block, round(max(abs(x) for x in rack.output_buffer_left), 3))
```

Run it with `PYTHONPATH=lib .venv/bin/python example.py`. It plays one note and prints the loudest sample of each block as the envelope opens (1.0 is +10 V):

```
0 0.003
1 0.017
2 0.077
3 0.124
4 0.158
5 0.18
6 0.185
7 0.136
```

[Docs](docs/overview.md) · [Examples](examples/) · [Roadmap](ROADMAP.md)

OmniPython is made by [PyDevices](https://pydevices.com).
