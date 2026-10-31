# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Allocation on MicroPython: what a block costs must not grow with the block.

Every float boxes and every slice makes a small object on MicroPython, so a
block cannot be allocation-free in Python; what can be required is that the
bytes allocated per block are the same at 64 and at 1024 frames. A vector
kernel or a C node meets that; a per-sample Python loop or an array
temporary does not. The cores that still loop per sample (oscillators,
ladders, the granular engine) are not on this list; docs/allocation.md says
which they are. The VCO and the ladders run on audiodsp nodes when the
build has them, and those are checked here at 64 and 256 frames, the most a
node hands out.

To see this test fail, put ``tmp = src * 0.5`` in one of the kernels.
"""

import gc

from audioinstruments._rack.core import Rack, create_buffer, mix_into
from audioinstruments._rack.dsp import (
    AmplifierCore,
    EnvelopeCore,
    LFOCore,
    SampleAndHoldCore,
    WavefolderCore,
)
from audioinstruments._rack.modules.modular100 import Modular100EnvLFO, Modular100VCA

SLACK = 64  # bytes; a float or two of block-rate bookkeeping


def bytes_per_call(fn, warmup=3):
    for _ in range(warmup):
        fn()
    gc.collect()
    before = gc.mem_alloc()
    fn()
    return gc.mem_alloc() - before


def assert_flat(make, label):
    small = bytes_per_call(make(64))
    large = bytes_per_call(make(1024))
    assert large <= small + SLACK, "%s: %d B at 64 frames, %d B at 1024" % (label, small, large)


def test_kernels_are_flat():
    def make(n):
        dst, tmp, a, b = (create_buffer(n, 0.3) for _ in range(4))
        srcs = [a, b]
        levels = [0.5, 0.25]
        return lambda: mix_into(dst, tmp, srcs, levels)

    assert_flat(make, "mix_into")


def test_cv_cores_are_flat():
    def env(n):
        core = EnvelopeCore(48000, n)
        gate = create_buffer(n, 1.0)
        out = create_buffer(n)
        return lambda: core.render(gate, out)

    def lfo(n):
        core = LFOCore(48000, n)
        s, t, w, q = (create_buffer(n) for _ in range(4))
        return lambda: core.render(3.0, sine=s, tri=t, saw=w, square=q)

    def vca(n):
        core = AmplifierCore(n)
        src = create_buffer(n, 0.3)
        cv = create_buffer(n, 0.5)
        out = create_buffer(n)
        return lambda: core.render(src, out, cv, exponential=True)

    def sh(n):
        core = SampleAndHoldCore(n)
        sig = create_buffer(n, 0.3)
        clk = create_buffer(n)
        clk[5] = 1.0
        out = create_buffer(n)
        return lambda: core.render(sig, clk, out, lag=0.5)

    def fold(n):
        core = WavefolderCore(n)
        src = create_buffer(n, 0.3)
        out = create_buffer(n)
        return lambda: core.render(src, out, fold=0.6)

    for make, label in (
        (env, "envelope"),
        (lfo, "lfo"),
        (vca, "vca"),
        (sh, "sample and hold"),
        (fold, "wavefolder"),
    ):
        assert_flat(make, label)


def test_vector_modules_are_flat():
    def rack_with(cls):
        def make(n):
            rack = Rack(block_size=n)
            mod = rack.add_module(cls("m"))
            rack.connect(next(iter(mod.outputs.values())), rack.master_left_in)
            return rack.step

        return make

    assert_flat(rack_with(Modular100EnvLFO), "Modular100EnvLFO")
    assert_flat(rack_with(Modular100VCA), "Modular100VCA")


def test_node_cores_are_flat():
    """The node pull is heap-lock clean, and a node core's block is flat.

    Every float block goes onto the int16 wire through ``to_int16``, which
    is audiodsp's ``audiomath.cast_into`` and allocates nothing, so nothing
    may grow with the block: not the VCO's three CVs, not the ladder's audio
    input or its per-sample cutoff CV. A ulab cast (``dst_i16[:] = tmp``)
    costs two bytes a frame, and a per-sample loop hundreds.
    """
    import micropython
    from audioinstruments._rack.dsp import (
        LadderCore,
        NodeLadderCore,
        NodeOscillatorCore,
        OscillatorCore,
    )

    def osc(n):
        core = OscillatorCore(48000)
        pitch, fm, sync, saw, pulse = (create_buffer(n, 0.01) for _ in range(5))
        return lambda: core.render(
            n, 220.0, pitch, fm_cv=fm, fm_depth=0.2, sync=sync, saw=saw, pulse=pulse
        )

    def ladder(n):
        core = LadderCore(48000, "transistor")
        src, dst, cv = (create_buffer(n, 0.2) for _ in range(3))
        return lambda: core.render(n, src, dst, cutoff_hz=800.0, cutoff_cv=cv, resonance=0.5)

    cases = (
        (osc, "OscillatorCore", OscillatorCore is NodeOscillatorCore),
        (ladder, "LadderCore", LadderCore is NodeLadderCore),
    )
    for make, label, node in cases:
        if not node:
            print("skip %s: this build's audiodsp has no node for it" % label)
            continue
        small = bytes_per_call(make(64))
        large = bytes_per_call(make(256))
        assert large <= small + SLACK, "%s: %d B at 64 frames, %d B at 256" % (label, small, large)

    if OscillatorCore is NodeOscillatorCore:
        core = OscillatorCore(48000)
        saw = create_buffer(64)
        core.render(64, 220.0, create_buffer(64, 0.01), saw=saw)
        bridge = core._bridge
        gc.collect()
        micropython.heap_lock()
        try:
            bridge._pull(bridge._nodes[0])
        finally:
            micropython.heap_unlock()


def test_the_poly_midi_voice_jacks_are_flat_in_poly_and_in_mono_unison():
    """What PolyMidiCV adds to MidiCV for its voices, poly and as a mono stack of three.

    MidiCV's own block (its 48 knob and pad jacks) is not flat on MicroPython,
    so the check is on the bytes the voice jacks add to it.
    """
    from audioinstruments._rack.modules.midi_cv import MidiCVModule
    from audioinstruments._rack.modules.poly_midi_cv import PolyMidiCV

    def added(mono, n):
        base = MidiCVModule("b", block_size=n)
        midi = PolyMidiCV("m", block_size=n, voices=3)
        midi.mono = mono
        midi.alloc.set_unison(3)
        for m in (base, midi):
            m.note_on(60, 100)
            m.pitch_bend(0.5)
        return bytes_per_call(lambda: midi.process(n)) - bytes_per_call(lambda: base.process(n))

    for mono, label in ((False, "poly"), (True, "mono unison")):
        small = added(mono, 64)
        large = added(mono, 1024)
        assert large <= small + SLACK, "PolyMidiCV, %s: %d B at 64 frames, %d B at 1024" % (
            label,
            small,
            large,
        )


def test_the_ensemble_adds_nothing_that_grows_with_the_block():
    """What ``EnsembleCore.render`` does beyond its bridges is flat from 64 to 256 frames.

    The ``ChunkedBridge``s (a line each, the dry and the bypass) copy their
    blocks through ulab, which allocates, so the bytes asked for are those of
    ``render`` less those of the same bridges run alone, over one 256-frame
    chunk (the pull happens once a chunk), per call. What is left is vector
    kernels, a few hundred bytes of bookkeeping each whatever the block.
    """
    from audioinstruments._rack.dsp.ensemble import EnsembleCore

    def added(n):
        core = EnsembleCore(48000, n)
        core.set(True)
        src, byp, left, right, out = (create_buffer(n, 0.2) for _ in range(5))
        bridges = core._bridges + [core._dry, core._bypass]
        calls = 256 // n

        def render():
            for _ in range(calls):
                core.render(src, byp, left, right)

        def bridged():
            for _ in range(calls):
                for bridge in bridges:
                    bridge.process(src, out)

        return (bytes_per_call(render) - bytes_per_call(bridged)) // calls

    small = added(64)
    large = added(256)
    assert large <= small + 4 * SLACK, "EnsembleCore: %d B a call at 64 frames, %d B at 256" % (
        small,
        large,
    )


def test_the_pressure_jacks_are_flat_while_pressure_moves_every_block():
    """What pressure adds to PolyMidiCV's block, sent every block, poly and as a mono stack."""
    from audioinstruments._rack.modules.midi_cv import MidiCVModule
    from audioinstruments._rack.modules.poly_midi_cv import PolyMidiCV

    def added(mono, n):
        base = MidiCVModule("b", block_size=n)
        midi = PolyMidiCV("m", block_size=n, voices=3)
        midi.mono = mono
        midi.alloc.set_unison(3)
        for m in (base, midi):
            m.note_on(60, 100)
        step = [0]

        def press(m):
            step[0] += 1
            m.poly_pressure(60, 1 + step[0] % 100)
            m.channel_pressure(step[0] % 50)
            m.process(n)

        cost = bytes_per_call(lambda: press(midi)) - bytes_per_call(lambda: press(base))
        assert midi.press_out.buffer[0] > 0.0
        return cost

    for mono, label in ((False, "poly"), (True, "mono unison")):
        small = added(mono, 64)
        large = added(mono, 1024)
        assert large <= small + SLACK, "pressure, %s: %d B at 64 frames, %d B at 1024" % (
            label,
            small,
            large,
        )


def test_a_voice_mix_with_buses_is_flat_in_a_steady_block_and_a_ramp():
    """VoiceMix with two buses at 64 and 256 frames: a held voice and one fading out."""
    from audioinstruments._rack.modules.voice_mix import VoiceMix

    def make(n, ramp):
        mix = VoiceMix("m", block_size=n, voices=2, buses=("a", "b"))
        for i in range(2):
            for name in ("a", "b"):
                src = create_buffer(n, 0.2)
                mix.bus_ins[name][i].set_cable(_Wire(src))
            mix.audio_ins[i].set_cable(_Wire(create_buffer(n, 0.2)))
        mix.gated[0] = mix.gated[1] = True

        def run():
            if ramp:
                mix.gain[0] = 1.0
                mix.target[0] = 0.0
                mix.gated[0] = True
            mix.process(n)

        return run

    for ramp in (False, True):
        small = bytes_per_call(make(64, ramp))
        large = bytes_per_call(make(256, ramp))
        assert large <= small + SLACK, "VoiceMix buses (ramp=%s): %d B at 64, %d B at 256" % (
            ramp,
            small,
            large,
        )


class _Source:
    def __init__(self, buf):
        self._buf = buf

    def get_buffer(self):
        return self._buf


class _Wire:
    """Just enough of a Cable for an input jack to read ``source.get_buffer()``."""

    def __init__(self, buf):
        self.source = _Source(buf)
