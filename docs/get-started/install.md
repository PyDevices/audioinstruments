# Install

audioinstruments runs on CPython 3.12 or later and on MicroPython-compatible
firmware that carries audiodsp and ulab. It is used from a checkout of this
repository for now.

## On a desktop (CPython)

You need numpy and audiodsp. The package is
called `omnipython-audiodsp` and you import `audiocore`, `audiofilters` and the
other modules it provides:

```sh
uv venv --seed --python 3.12 .venv
uv pip install --python .venv/bin/python omnipython-audiodsp numpy
git clone https://github.com/PyDevices/audioinstruments && cd audioinstruments
```

Run your programs from the checkout with `PYTHONPATH=lib`, so
`import audioinstruments` finds the package.

## On a MicroPython-compatible board

The firmware needs ulab and audiodsp's `audiocore`, `audiofilters`,
`audiobiquad`, `audioecho`, `audiopump` and `audiograph`. `manifest.py` in the
repository root freezes the instruments and the rack under them: name it as
`FROZEN_MANIFEST` in a unix-port build, or add this directory to a firmware
build's module list. [How it works](../how-it-works/index.md) says what each
module is for.

Next, [play a note](first-program.md).
