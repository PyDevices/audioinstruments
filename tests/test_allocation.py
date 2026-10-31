# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""No module builds an array while processing a block.

Every block a module owns is a ``TracedBlock``, an ndarray subclass whose
``__array_finalize__`` runs whenever numpy creates a new array from one of
them: a ufunc without ``out=``, ``a * b``, ``-a``, a slice copy. numpy 2
builds such a result as a plain ndarray and hands the subclass a view of it,
so a fresh array shows up with a plain ``base``; a real view of a traced
block has a ``TracedBlock`` base. That is how the two are told apart. One ``rack.step()``
after warm-up must create no array of 256 bytes or more from audioinstruments._rack's own
code (at a 256-frame block a float temporary is 1 KB and an int16 one
512 B). audiodsp's CPython shims make plain ndarrays and bytes of their
own; those are not traced.

To see this test fail, put ``tmp = src * 0.5`` in any process() path.
"""

import os
import traceback

import audioinstruments._rack
import numpy as np
import pytest
from audioinstruments._rack.core import Rack, signal

LIB = os.path.dirname(os.path.abspath(audioinstruments._rack.__file__))
BLOCK = 256
THRESHOLD = 256

EVENTS = []
TRACING = [False]


class TracedBlock(np.ndarray):
    """A block that reports every new array derived from it while tracing."""

    def __array_finalize__(self, obj):
        if obj is None or not TRACING[0] or isinstance(self.base, TracedBlock):
            return  # explicit construction, tracing off, or a view of a block
        size = self.nbytes
        if size >= THRESHOLD:
            stack = traceback.extract_stack()[:-1]
            frames = [f for f in stack if f.filename.startswith(LIB)] or stack
            last = frames[-1]
            where = "%s:%d %s" % (os.path.relpath(last.filename, LIB), last.lineno, last.line)
            EVENTS.append((size, where))


def traced_zeros(size):
    return np.zeros(size, dtype=signal.FLOAT_DTYPE).view(TracedBlock)


@pytest.fixture(autouse=True)
def traced_buffers():
    signal.set_buffer_factory(traced_zeros)
    yield
    signal.set_buffer_factory(None)


MODULES = [
    audioinstruments._rack.Patch2600,
    audioinstruments._rack.ParaphonicSynth,
    audioinstruments._rack.WestCoastSynth,
    audioinstruments._rack.HybridMono,
    audioinstruments._rack.PinMatrix3,
    audioinstruments._rack.Duo20,
    audioinstruments._rack.DuoSynthVoice,
    audioinstruments._rack.DuoSynthLFO,
    audioinstruments._rack.DuoSynthOutput,
    audioinstruments._rack.ElectricGrand70Voice,
    audioinstruments._rack.ElectricGrand70Output,
    audioinstruments._rack.ElectricPianoVoice,
    audioinstruments._rack.ElectricPianoOutput,
    audioinstruments._rack.ElectronicDrums5Voice,
    audioinstruments._rack.ClavichordVoice,
    audioinstruments._rack.ClavichordOutput,
    audioinstruments._rack.ReedPianoVoice,
    audioinstruments._rack.ReedPianoOutput,
    audioinstruments._rack.ReedPiano200AVoice,
    audioinstruments._rack.ReedPiano200AOutput,
    audioinstruments._rack.Tremolo,
    audioinstruments._rack.WestCoast0,
    audioinstruments._rack.FunctionGenerator,
    audioinstruments._rack.MidiCVModule,
    audioinstruments._rack.PolyMidiCV,
    audioinstruments._rack.VoiceMix,
    audioinstruments._rack.Modular100VCO,
    audioinstruments._rack.Modular100VCF,
    audioinstruments._rack.Modular100VCA,
    audioinstruments._rack.Modular100EnvLFO,
    audioinstruments._rack.Modular100Utility,
    audioinstruments._rack.Modular55VCA,
    audioinstruments._rack.Modular55LowPass,
    audioinstruments._rack.Modular55HighPass,
    audioinstruments._rack.Modular55Envelope,
    audioinstruments._rack.Modular55VCO,
    audioinstruments._rack.DrumSynth,
    audioinstruments._rack.Semi32,
    audioinstruments._rack.PolyrhythmSynth,
    audioinstruments._rack.RandomSequencer,
    audioinstruments._rack.GranularProcessor,
    audioinstruments._rack.MacroOscillator,
    audioinstruments._rack.ModalResonator,
    audioinstruments._rack.StateVariableMono,
    audioinstruments._rack.Acid303,
    audioinstruments._rack.MonoOne,
    audioinstruments._rack.Mono101Voice,
    audioinstruments._rack.Mono101LFO,
    audioinstruments._rack.MonoSynthVoice,
    audioinstruments._rack.Poly106Voice,
    audioinstruments._rack.Poly106LFO,
    audioinstruments._rack.Poly106Output,
    audioinstruments._rack.Poly5Voice,
    audioinstruments._rack.Poly5LFO,
    audioinstruments._rack.Poly6Voice,
    audioinstruments._rack.Poly6LFO,
    audioinstruments._rack.Poly6Output,
    audioinstruments._rack.Poly8Voice,
    audioinstruments._rack.Poly8LFO,
    audioinstruments._rack.Poly80Voice,
    audioinstruments._rack.Poly80Mod,
    audioinstruments._rack.Poly80Output,
    audioinstruments._rack.PolyA6Voice,
    audioinstruments._rack.PolyA6Noise,
    audioinstruments._rack.PolyA6Output,
    audioinstruments._rack.PolyXaVoice,
    audioinstruments._rack.PolyXaLFO,
    audioinstruments._rack.PolyXaOutput,
    audioinstruments._rack.StringEnsembleVoice,
    audioinstruments._rack.StringEnsembleEnvelope,
    audioinstruments._rack.StringEnsembleBass,
    audioinstruments._rack.StringEnsembleOutput,
    audioinstruments._rack.BassPedalsVoice,
    audioinstruments._rack.Vocoder330Voice,
    audioinstruments._rack.Vocoder330Keys,
    audioinstruments._rack.Vocoder330Mic,
    audioinstruments._rack.Vocoder330Bank,
    audioinstruments._rack.Vocoder330Output,
    audioinstruments._rack.Tonewheel3Voice,
    audioinstruments._rack.Tonewheel3Percussion,
    audioinstruments._rack.Tonewheel3Vibrato,
    audioinstruments._rack.Tonewheel3Expression,
    audioinstruments._rack.Tonewheel3Rotary,
    audioinstruments._rack.CompactOrganVoice,
    audioinstruments._rack.CompactOrganVibrato,
    audioinstruments._rack.CompactOrganOutput,
    audioinstruments._rack.Rhythm606BassDrum,
    audioinstruments._rack.Rhythm606ClosedHat,
    audioinstruments._rack.Rhythm606Cymbal,
    audioinstruments._rack.Rhythm606OpenHat,
    audioinstruments._rack.Rhythm606Snare,
    audioinstruments._rack.Rhythm606Tom,
    audioinstruments._rack.Rhythm78Cowbell,
    audioinstruments._rack.Rhythm78Cymbal,
    audioinstruments._rack.Rhythm78Drum,
    audioinstruments._rack.Rhythm78Guiro,
    audioinstruments._rack.Rhythm78HiHat,
    audioinstruments._rack.Rhythm78Output,
    audioinstruments._rack.Rhythm78Snare,
    audioinstruments._rack.Rhythm78Tambourine,
    audioinstruments._rack.Rhythm808BassDrum,
    audioinstruments._rack.Rhythm808Clap,
    audioinstruments._rack.Rhythm808Claves,
    audioinstruments._rack.Rhythm808ClosedHat,
    audioinstruments._rack.Rhythm808Conga,
    audioinstruments._rack.Rhythm808Cowbell,
    audioinstruments._rack.Rhythm808Cymbal,
    audioinstruments._rack.Rhythm808Maracas,
    audioinstruments._rack.Rhythm808OpenHat,
    audioinstruments._rack.Rhythm808Output,
    audioinstruments._rack.Rhythm808RimShot,
    audioinstruments._rack.Rhythm808Snare,
    audioinstruments._rack.Rhythm808Tom,
    audioinstruments._rack.Rhythm909BassDrum,
    audioinstruments._rack.Rhythm909Clap,
    audioinstruments._rack.Rhythm909ClosedHat,
    audioinstruments._rack.Rhythm909Crash,
    audioinstruments._rack.Rhythm909OpenHat,
    audioinstruments._rack.Rhythm909Ride,
    audioinstruments._rack.Rhythm909RimShot,
    audioinstruments._rack.Rhythm909Snare,
    audioinstruments._rack.Rhythm909Tom,
    audioinstruments._rack.ComboOrganVoice,
    audioinstruments._rack.ComboOrganVibrato,
    audioinstruments._rack.ComboOrganOutput,
]


def driven_rack(module_cls):
    """A rack with the module, a MIDI-CV module on its keyboard inputs, and a note held."""
    rack = Rack(block_size=BLOCK)
    midi = rack.add_module(audioinstruments._rack.MidiCVModule("midi"))
    mod = rack.add_module(module_cls("mod"))
    for name in (
        "kybd_cv",
        "pitch_in",
        "vco1_pitch",
        "freq_cv1",
        "vco_1v_oct",
        "audio_in",
        "pitch",
    ):
        if name in mod.inputs:
            rack.connect(midi.pitch_out, mod.inputs[name])
            break
    for name in (
        "kybd_gate",
        "gate_in",
        "trigger_in",
        "strum_in",
        "env1_gate",
        "trig_in",
        "clock_in",
        "ch1_trig",
        "gate",
    ):
        if name in mod.inputs:
            rack.connect(midi.gate_out, mod.inputs[name])
            break
    rack.connect(next(iter(mod.outputs.values())), rack.master_left_in)
    midi.note_on(48, 100)
    return rack


def arrays_created_in_one_step(rack, warmup=6):
    for _ in range(warmup):
        rack.step()
    del EVENTS[:]
    TRACING[0] = True
    try:
        rack.step()
    finally:
        TRACING[0] = False
    return list(EVENTS)


@pytest.mark.parametrize("module_cls", MODULES, ids=lambda c: c.NAME)
def test_module_block_creates_no_arrays(module_cls):
    created = arrays_created_in_one_step(driven_rack(module_cls))
    assert created == [], "arrays created in one block:\n" + "\n".join(
        "%d B at %s" % (size, where) for size, where in created
    )


RHYTHM78_MODULES = [
    m for m in MODULES if m.NAME.startswith("Rhythm78") and m.NAME != "Rhythm78Output"
]


@pytest.mark.parametrize("module_cls", RHYTHM78_MODULES, ids=lambda c: c.NAME)
def test_rhythm78_voice_creates_no_arrays_on_the_strike_block(module_cls):
    """The strike itself (retuning a hat, laying out the scrapes) makes no array either."""
    rack = driven_rack(module_cls)
    midi = next(m for m in rack.modules if isinstance(m, audioinstruments._rack.MidiCVModule))
    for _ in range(8):
        rack.step()
    midi.note_off(48)
    for _ in range(300):  # let the voice die away and park
        rack.step()
    del EVENTS[:]
    TRACING[0] = True
    try:
        midi.note_on(46 if module_cls.NAME == "Rhythm78HiHat" else 48, 127)
        rack.step()
        rack.step()
    finally:
        TRACING[0] = False
    assert EVENTS == [], "arrays created:\n" + "\n".join("%d B at %s" % e for e in EVENTS)


def test_the_tracer_sees_a_temporary():
    """The check itself works: a product of two traced blocks is reported."""
    a = signal.create_buffer(BLOCK, 0.5)
    b = signal.create_buffer(BLOCK, 0.5)
    del EVENTS[:]
    TRACING[0] = True
    try:
        tmp = a * b  # noqa: F841 - the temporary is the point
    finally:
        TRACING[0] = False
    assert len(EVENTS) == 1 and EVENTS[0][0] == BLOCK * 4


def test_a_pool_creates_no_arrays_while_voices_play_and_steal():
    """Voices, the allocator's CV jacks and the mixer, with a steal and a cut in flight."""
    from audioinstruments._rack.core import VoicePool

    rack = Rack(block_size=BLOCK)

    def build(voice):
        synth = voice.add(audioinstruments._rack.MonoOne, "synth")
        rack.connect(voice.pitch, synth.inputs["kybd_cv"])
        rack.connect(voice.gate, synth.inputs["kybd_gate"])
        return synth.outputs["vca_out"]

    pool = VoicePool(rack, build, voices=3, max_voices=4, unison=1)
    for note in (48, 55, 60):
        pool.note_on(note, 100)
        rack.step()
    for _ in range(6):
        rack.step()
    pool.note_on(64, 100)  # a steal: the fade, the gap and the start all run in the traced steps
    del EVENTS[:]
    TRACING[0] = True
    try:
        rack.step()
        rack.step()
        rack.step()
        pool.voice_count = 2  # and a cut
        rack.step()
        rack.step()
    finally:
        TRACING[0] = False
    assert EVENTS == [], "arrays created:\n" + "\n".join("%d B at %s" % e for e in EVENTS)


@pytest.mark.parametrize("mono", (False, True), ids=("poly", "mono"))
def test_a_pool_creates_no_arrays_while_pressure_moves_every_block(mono):
    """Poly and channel pressure sent every block, with a steal in flight, make no array."""
    from audioinstruments._rack.core import VoicePool

    rack = Rack(block_size=BLOCK)

    def build(voice):
        synth = voice.add(audioinstruments._rack.MonoOne, "synth")
        rack.connect(voice.pitch, synth.inputs["kybd_cv"])
        rack.connect(voice.gate, synth.inputs["kybd_gate"])
        return synth.outputs["vca_out"]

    pool = VoicePool(rack, build, voices=3, unison=2 if mono else 1, mono=mono)
    for note in (48, 55, 60):
        pool.note_on(note, 100)
        rack.step()
    for _ in range(6):
        rack.step()
    midi = pool.midi
    midi.poly_pressure(60, 77)
    rack.step()
    assert midi.press_out.buffer[0] > 0.5  # it was fed
    assert max(float(j.buffer[0]) for j in midi.press_outs) > 0.5
    del EVENTS[:]
    TRACING[0] = True
    try:
        for step in range(8):
            if step == 3:
                pool.note_on(64, 100)  # a steal while the pressure moves
            for note in (48, 55, 60, 64):
                midi.poly_pressure(note, 10 + 10 * step)
            midi.channel_pressure(5 * step)
            rack.step()
    finally:
        TRACING[0] = False
    assert EVENTS == [], "arrays created:\n" + "\n".join("%d B at %s" % e for e in EVENTS)


def test_a_pool_with_buses_creates_no_arrays_through_a_steal():
    """Two buses fed by every voice, summed through plain blocks and a steal's ramp."""
    from audioinstruments._rack.core import VoicePool

    rack = Rack(block_size=BLOCK)

    def build(voice):
        synth = voice.add(audioinstruments._rack.MonoOne, "synth")
        rack.connect(voice.pitch, synth.inputs["kybd_cv"])
        rack.connect(voice.gate, synth.inputs["kybd_gate"])
        voice.bus("a", synth.outputs["vca_out"])
        voice.bus("b", synth.outputs["vca_out"])
        return synth.outputs["vca_out"]

    pool = VoicePool(rack, build, voices=3, buses=("a", "b"))
    for note in (48, 55, 60):
        pool.note_on(note, 100)
        rack.step()
    for _ in range(6):
        rack.step()
    assert float(max(pool.buses["a"].buffer)) > 0.0  # it was fed
    pool.note_on(64, 100)  # a steal: the ramp runs through the buses in the traced steps
    del EVENTS[:]
    TRACING[0] = True
    try:
        for _ in range(5):
            rack.step()
    finally:
        TRACING[0] = False
    assert EVENTS == [], "arrays created:\n" + "\n".join("%d B at %s" % e for e in EVENTS)


def test_a_mono_pool_with_a_glide_creates_no_arrays_through_legato_and_bend():
    """The mono jacks, a legato move, a retrigger and a GlideCore sliding the note."""
    from audioinstruments._rack.core import VoicePool
    from audioinstruments._rack.dsp.glide import GlideCore

    rack = Rack(block_size=BLOCK)

    class Slide(audioinstruments._rack.core.Module):
        NAME = "Slide"

        def _build(self):
            self.note_in = self.add_input(
                "note", signal_type=audioinstruments._rack.core.SignalType.CV
            )
            self.pitch_in = self.add_input(
                "pitch", signal_type=audioinstruments._rack.core.SignalType.CV
            )
            self.out = self.add_output(
                "out", signal_type=audioinstruments._rack.core.SignalType.AUDIO
            )
            self.glide = GlideCore(self.sample_rate, self.block_size)
            self.glide.mode = GlideCore.ON
            self.glide.time = 0.05
            self.add_scratch("slid")

        def process(self, block_size):
            self.glide.process(self.slid, self.note_in.get_buffer(), self.pitch_in.get_buffer())
            self.out.buffer[:] = self.slid

    def build(voice):
        slide = voice.add(Slide, "slide")
        rack.connect(voice.note, slide.note_in)
        rack.connect(voice.pitch, slide.pitch_in)
        return slide.out

    pool = VoicePool(rack, build, voices=1, mono=True, retrigger=True)
    pool.note_on(48, 100)
    for _ in range(6):
        rack.step()
    del EVENTS[:]
    TRACING[0] = True
    try:
        pool.note_on(60, 100)  # legato, and a retrigger pulse
        rack.step()
        rack.step()
        pool.midi.pitch_bend(0.5)
        rack.step()
        pool.note_off(60)  # back to 48
        rack.step()
        rack.step()
    finally:
        TRACING[0] = False
    assert EVENTS == [], "arrays created:\n" + "\n".join("%d B at %s" % e for e in EVENTS)


def test_mono_unison_and_a_poly_glide_create_no_arrays():
    """A mono stack of three moving legato, a bend, the unison lowered, and a poly glide."""
    from audioinstruments._rack.core import VoicePool
    from audioinstruments._rack.dsp.glide import GlideCore

    class Slide(audioinstruments._rack.core.Module):
        NAME = "Slide"

        def _build(self):
            self.note_in = self.add_input(
                "note", signal_type=audioinstruments._rack.core.SignalType.CV
            )
            self.pitch_in = self.add_input(
                "pitch", signal_type=audioinstruments._rack.core.SignalType.CV
            )
            self.out = self.add_output(
                "out", signal_type=audioinstruments._rack.core.SignalType.AUDIO
            )
            self.glide = GlideCore(self.sample_rate, self.block_size)
            self.glide.mode = GlideCore.ON
            self.glide.time = 0.05
            self.add_scratch("slid")

        def process(self, block_size):
            self.glide.process(self.slid, self.note_in.get_buffer(), self.pitch_in.get_buffer())
            self.out.buffer[:] = self.slid

    def pool_of(mono):
        rack = Rack(block_size=BLOCK)

        def build(voice):
            slide = voice.add(Slide, "slide")
            rack.connect(voice.note, slide.note_in)
            rack.connect(voice.pitch, slide.pitch_in)
            return slide.out

        return rack, VoicePool(rack, build, voices=3, mono=mono, unison=3 if mono else 1)

    for mono in (True, False):
        rack, pool = pool_of(mono)
        pool.note_on(48, 100)
        for _ in range(6):
            rack.step()
        pool.note_off(48)
        for _ in range(60):
            rack.step()
        pool.note_on(48, 100)
        rack.step()
        del EVENTS[:]
        TRACING[0] = True
        try:
            pool.note_on(60, 100)  # legato on the stack; a new voice gliding in poly
            rack.step()
            rack.step()
            pool.midi.pitch_bend(0.5)
            rack.step()
            if mono:
                pool.unison = 2  # the third voice fades out and parks
            pool.note_off(60)
            for _ in range(4):
                rack.step()
        finally:
            TRACING[0] = False
        assert EVENTS == [], "arrays created:\n" + "\n".join("%d B at %s" % e for e in EVENTS)


def test_the_string_ensemble_creates_no_arrays_with_a_bass_key_and_a_released_chord():
    """The whole instrument: upper keys, the bass, the latch, a choke, the ensemble and the DC block.

    The one-module rows above feed a voice only a pitch and a gate and never reach the bass
    or the output section, so this plays the instrument itself.
    """
    import audioinstruments._rack.adapter as adapter

    inst = adapter.create(48000, voice="string_ensemble", output="pull", block_size=BLOCK)
    inst.program_change(10)  # Everything: all six tones, ensemble on
    rack = inst.rack
    for note in (48, 60, 64, 67):
        inst.note_on(note, 100)
    for _ in range(40):
        rack.step()
    assert float(np.max(np.abs(inst.patch.bass.audio_out.buffer))) > 0.0  # the bass was fed
    inst.note_off(64)  # a choke
    del EVENTS[:]
    TRACING[0] = True
    try:
        for _ in range(4):
            rack.step()
        for note in (48, 60, 67):  # the last keys up: the latch and the envelope's tail
            inst.note_off(note)
        for _ in range(8):
            rack.step()
        inst.note_on(55, 100)  # a key during the tail
        for _ in range(4):
            rack.step()
    finally:
        TRACING[0] = False
    inst.deinit()
    assert EVENTS == [], "arrays created:\n" + "\n".join("%d B at %s" % e for e in EVENTS)


def test_the_vocoder330_creates_no_arrays_with_every_section_playing_and_a_steal():
    """The whole instrument: strings, choir and vocoder, the vibrato, the ensemble, a swoop and a steal.

    The one-module rows above feed a voice only a pitch and a gate and leave the keys, the mic, the
    bank and the output unfed, so this plays the instrument itself.
    """
    import audioinstruments._rack.adapter as adapter

    inst = adapter.create(48000, voice="vocoder330", output="pull", block_size=BLOCK, voices=4)
    inst.program_change(11)  # Swooping Choir: the swoop, the choir, the ensemble
    for name in (
        "strings_upper",
        "strings_lower",
        "vocoder_upper",
        "vocoder_lower",
        "vocoder_ensemble",
    ):
        inst.patch.set_control(inst.voice_pool, name, True)
    inst.patch.set_control(inst.voice_pool, "vib_delay", 0.0)
    rack = inst.rack
    for note in (48, 55, 60, 64):
        inst.note_on(note, 100)
    for _ in range(80):
        rack.step()
    assert float(np.max(np.abs(inst.patch.bank.out_jack.buffer))) > 0.0  # the bank was fed
    inst.note_off(64)
    inst.note_on(72, 100)  # a steal, a press (the tail cut) and a new swoop
    del EVENTS[:]
    TRACING[0] = True
    try:
        for _ in range(12):
            rack.step()
        inst.patch.set_control(inst.voice_pool, "vocoder_hold", True)
        for _ in range(4):
            rack.step()
    finally:
        TRACING[0] = False
    inst.deinit()
    assert EVENTS == [], "arrays created:\n" + "\n".join("%d B at %s" % e for e in EVENTS)


def test_the_tonewheel3_creates_no_arrays_with_every_effect_on_and_a_steal():
    """The whole organ: drawbars, percussion, click, chorus, a half-closed pedal, the
    driven speaker changing speed, and a steal."""
    import audioinstruments._rack.adapter as adapter

    inst = adapter.create(48000, voice="tonewheel3", output="pull", block_size=BLOCK, voices=4)
    inst.program_change(2)  # Rock Drive: percussion, fast speaker, drive
    for name, value in (("vibrato", True), ("vibrato_mode", "C3"), ("expression", 6.0)):
        inst.patch.set_control(inst.voice_pool, name, value)
    rack = inst.rack
    for note in (48, 55, 60, 64):
        inst.note_on(note, 100)
    for _ in range(80):
        rack.step()
    inst.note_off(64)
    inst.note_on(72, 100)  # a steal
    del EVENTS[:]
    TRACING[0] = True
    try:
        for _ in range(12):
            rack.step()
        inst.patch.set_control(inst.voice_pool, "rotary", "slow")
        inst.patch.set_control(inst.voice_pool, "db4", 4)
        for _ in range(4):
            rack.step()
    finally:
        TRACING[0] = False
    inst.deinit()
    assert EVENTS == [], "arrays created:\n" + "\n".join("%d B at %s" % e for e in EVENTS)


def test_the_clavichord_creates_no_arrays_with_the_wah_a_release_pluck_and_a_steal():
    """Every tab, the wah and the tremolo on, a key let go (its release pluck), and a steal."""
    import audioinstruments._rack.adapter as adapter

    inst = adapter.create(48000, voice="clavichord", output="pull", block_size=BLOCK, voices=4)
    inst.program_change(5)  # Auto-Wah
    for name in ("brilliant", "treble", "medium", "soft"):
        inst.patch.set_control(inst.voice_pool, name, 1.0)
    inst.patch.set_control(inst.voice_pool, "tremolo_depth", 5.0)
    rack = inst.rack
    for note in (48, 55, 60, 64):
        inst.note_on(note, 120)
    for _ in range(20):
        rack.step()
    inst.note_off(64)
    del EVENTS[:]
    TRACING[0] = True
    try:
        for _ in range(4):
            rack.step()
        inst.note_on(72, 100)
        inst.note_on(76, 100)  # a fifth note on four voices: a steal
        for _ in range(12):
            rack.step()
    finally:
        TRACING[0] = False
    stolen = inst.voice_pool.stolen
    inst.deinit()
    assert stolen >= 1
    assert EVENTS == [], "arrays created:\n" + "\n".join("%d B at %s" % e for e in EVENTS)
