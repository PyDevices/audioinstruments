# Install

audioinstruments runs on CPython 3.12 or later and on MicroPython-compatible
firmware that carries audiodsp and ulab. It is used from a checkout of this
repository for now.

## On a desktop (CPython)

You need numpy and audiodsp (from TestPyPI until its release). The package is
called `omnipython-audiodsp` and you import `audiocore`, `audiofilters` and the
other modules it provides:

```sh
uv venv --seed --python 3.12 .venv
uv pip install --python .venv/bin/python -i https://test.pypi.org/simple/ \
    --extra-index-url https://pypi.org/simple/ --index-strategy unsafe-best-match \
    omnipython-audiodsp numpy
git clone https://github.com/PyDevices/audioinstruments && cd audioinstruments
```

The `--index-strategy unsafe-best-match` flag matters: uv looks in the extra
index first, and PyPI holds only a placeholder for `omnipython-audiodsp`, so
without the flag uv installs that instead of the current release.

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
