# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Play a trait spec's phrase on one patch and write the PCM, on any interpreter.

    micropython tools/traits_render.py poly106 1 graph '{"notes": ...}' out.pcm

``tools/traits.py`` runs this under MicroPython for a spec that names an
``engine`` its own audiodsp lacks (the Poly106's graph form needs
``audiograph``), then measures the file it wrote the way it measures its own
renders. Where audiodsp has ``audiograph``, traits.py renders in-process
instead, and the two renders are the same samples. The file is interleaved stereo int16; the last line printed is
``latency <frames>``.
"""

import json
import sys

# No os.path on MicroPython: the script's own path says where tools/ and lib/ are.
_parts = (sys.argv[0] if sys.argv and sys.argv[0] else "tools/traits_render.py").split("/")
HERE = "/".join(_parts[:-1]) or "."
ROOT = "/".join(_parts[:-2]) or "."
for folder in (HERE, ROOT + "/lib"):
    if folder not in sys.path:
        sys.path.insert(0, folder)

import audioinstruments._rack.adapter as adapter  # noqa: E402
from traits_phrase import BUFFER, SAMPLE_RATE, schedule  # noqa: E402


def render(name, patch, engine, spec, path):
    inst = adapter.create(
        SAMPLE_RATE, voice=name, engine=engine, output="pull", buffer_frames=BUFFER
    )
    try:
        inst.program_change(patch)
        # JSON made the patch numbers strings
        for control, value in spec.get("controls", {}).get(str(patch), {}).items():
            inst.patch.set_control(inst.voice_pool, control, value)
        todo, buffers = schedule(spec)
        k = 0
        with open(path, "wb") as f:
            for b in range(buffers):
                start = b * BUFFER
                while k < len(todo) and todo[k][0] < start + BUFFER:
                    frame, on, note, velocity = todo[k]
                    if on:
                        inst.note_on(note, velocity, sample_position=frame - start)
                    else:
                        inst.note_off(note, sample_position=frame - start)
                    k += 1
                f.write(inst._pull())
        return inst.latency_samples
    finally:
        inst.deinit()


def main(argv):
    name, patch, engine, spec, path = argv[0], int(argv[1]), argv[2], json.loads(argv[3]), argv[4]
    print("latency %d" % render(name, patch, engine, spec, path))


if __name__ == "__main__":
    main(sys.argv[1:])
