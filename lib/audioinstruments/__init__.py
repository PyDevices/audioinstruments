# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Synthesizers, organs and electric pianos, each one a patch on a virtual rack.

Each instrument is a module, ``audioinstruments.<name>``, exposing:

    MACRO_LABELS  tuple of names, one per macro parameter
    MACRO_MODES   {index: "UNIPOLAR" | "BIPOLAR" | "TOGGLE"}
    PATCHES       {index: (name, (macro values, 0-127))}; patch 0 is the sound
                  a freshly created instrument makes
    NOTE_MAP      drum machines only: ((midi_note, label), ...)
    PAD_MAP       drum machines only: ((key, voice), ...) for pad keys 36-51
    create(sample_rate, channel_count=2, transport=None, **options)

    import audioinstruments
    inst = audioinstruments.create("poly106", 48000)
    inst.note_on(60)
    inst.set_macro(0, 96)            # vcf_freq, MIDI scale
    audio_out.play(inst.output)

On MicroPython call ``inst.fill()`` every 10 to 20 ms while it plays: that is
when notes and knobs reach the sound. Where the patch compiles to an
``audiograph`` graph, ``inst.output`` is the graph and renders as it is
pulled; otherwise it is a ring that ``fill()`` keeps topped up. The options
are those of ``vrack.adapter.Instrument`` (``voices``, ``block_size``,
``output``, ``engine`` and the rest), or of ``vrack.soundfont.create`` for the
SAMPLERS.
"""

import sys

from ._names import ALL, DRUM_MACHINES, MELODIC, SAMPLERS

__all__ = ("ALL", "DRUM_MACHINES", "MELODIC", "SAMPLERS", "create", "load")


def load(name):
    """Import and return the instrument module ``name``."""
    full = __name__ + "." + name
    __import__(full)
    return sys.modules[full]


def create(name, sample_rate, channel_count=2, transport=None, **options):
    """Load instrument ``name`` and return a live instance of it."""
    return load(name).create(
        sample_rate, channel_count=channel_count, transport=transport, **options
    )


def _build(name, sample_rate, channel_count, transport, options):
    import vrack.adapter as adapter

    options["voice"] = name
    if name not in adapter.SAMPLERS and "output" not in options and adapter._pull_is_native_only():
        # The graph renders as it is pulled, so a host that pulls and calls
        # fill() now and then keeps time. A patch that does not compile, or
        # an audiograph older than the change queue (before audiodsp 0.6.11),
        # takes the ring.
        try:
            return adapter.create(
                sample_rate,
                channel_count=channel_count,
                transport=transport,
                output="graph",
                **options,
            )
        except (ImportError, ValueError, RuntimeError):
            pass
    return adapter.create(sample_rate, channel_count=channel_count, transport=transport, **options)
