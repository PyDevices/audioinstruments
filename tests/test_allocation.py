# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""No module builds an array while processing a block.

Every block a module owns is a ``TracedBlock``, an ndarray subclass whose
``__array_finalize__`` runs whenever numpy creates a new array from one of
them: a ufunc without ``out=``, ``a * b``, ``-a``, a slice copy. numpy 2
builds such a result as a plain ndarray and hands the subclass a view of it,
so a fresh array shows up with a plain ``base``; a real view of a traced
block has a ``TracedBlock`` base. That is how the two are told apart. One ``rack.step()``
after warm-up must create no array of 256 bytes or more from vrack's own
code (at a 256-frame block a float temporary is 1 KB and an int16 one
512 B). audiodsp's CPython shims make plain ndarrays and bytes of their
own; those are not traced.

To see this test fail, put ``tmp = src * 0.5`` in any process() path.
"""

import os
import traceback

import numpy as np
import pytest
import vrack
from vrack.core import Rack, signal

LIB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(vrack.__file__))), "vrack")
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
    vrack.Patch2600,
    vrack.ParaphonicSynth,
    vrack.WestCoastSynth,
    vrack.HybridMono,
    vrack.PinMatrix3,
    vrack.Duo20,
    vrack.DuoSynthVoice,
    vrack.DuoSynthLFO,
    vrack.DuoSynthOutput,
    vrack.ElectricGrand70Voice,
    vrack.ElectricGrand70Output,
    vrack.ElectricPianoVoice,
    vrack.ElectricPianoOutput,
    vrack.ClavichordVoice,
    vrack.ClavichordOutput,
    vrack.ReedPianoVoice,
    vrack.ReedPianoOutput,
    vrack.ReedPiano200AVoice,
    vrack.ReedPiano200AOutput,
    vrack.Tremolo,
    vrack.WestCoast0,
    vrack.FunctionGenerator,
    vrack.MidiCVModule,
    vrack.PolyMidiCV,
    vrack.VoiceMix,
    vrack.Modular100VCO,
    vrack.Modular100VCF,
    vrack.Modular100VCA,
    vrack.Modular100EnvLFO,
    vrack.Modular100Utility,
    vrack.Modular55VCA,
    vrack.Modular55LowPass,
    vrack.Modular55HighPass,
    vrack.Modular55Envelope,
    vrack.Modular55VCO,
    vrack.DrumSynth,
    vrack.Semi32,
    vrack.PolyrhythmSynth,
    vrack.RandomSequencer,
    vrack.GranularProcessor,
    vrack.MacroOscillator,
    vrack.ModalResonator,
    vrack.StateVariableMono,
    vrack.Acid303,
    vrack.MonoOne,
    vrack.Mono101Voice,
    vrack.Mono101LFO,
    vrack.MonoSynthVoice,
    vrack.Poly106Voice,
    vrack.Poly106LFO,
    vrack.Poly106Output,
    vrack.Poly5Voice,
    vrack.Poly5LFO,
    vrack.Poly6Voice,
    vrack.Poly6LFO,
    vrack.Poly6Output,
    vrack.Poly8Voice,
    vrack.Poly8LFO,
    vrack.Poly80Voice,
    vrack.Poly80Mod,
    vrack.Poly80Output,
    vrack.PolyA6Voice,
    vrack.PolyA6Noise,
    vrack.PolyA6Output,
    vrack.PolyXaVoice,
    vrack.PolyXaLFO,
    vrack.PolyXaOutput,
    vrack.StringEnsembleVoice,
    vrack.StringEnsembleEnvelope,
    vrack.StringEnsembleBass,
    vrack.StringEnsembleOutput,
    vrack.BassPedalsVoice,
    vrack.Vocoder330Voice,
    vrack.Vocoder330Keys,
    vrack.Vocoder330Mic,
    vrack.Vocoder330Bank,
    vrack.Vocoder330Output,
    vrack.Tonewheel3Voice,
    vrack.Tonewheel3Percussion,
    vrack.Tonewheel3Vibrato,
    vrack.Tonewheel3Expression,
    vrack.Tonewheel3Rotary,
    vrack.CompactOrganVoice,
    vrack.CompactOrganVibrato,
    vrack.CompactOrganOutput,
    vrack.Rhythm606BassDrum,
    vrack.Rhythm606ClosedHat,
    vrack.Rhythm606Cymbal,
    vrack.Rhythm606OpenHat,
    vrack.Rhythm606Snare,
    vrack.Rhythm606Tom,
    vrack.Rhythm808BassDrum,
    vrack.Rhythm808Clap,
    vrack.Rhythm808Claves,
    vrack.Rhythm808ClosedHat,
    vrack.Rhythm808Conga,
    vrack.Rhythm808Cowbell,
    vrack.Rhythm808Cymbal,
    vrack.Rhythm808Maracas,
    vrack.Rhythm808OpenHat,
    vrack.Rhythm808Output,
    vrack.Rhythm808RimShot,
    vrack.Rhythm808Snare,
    vrack.Rhythm808Tom,
    vrack.ComboOrganVoice,
    vrack.ComboOrganVibrato,
    vrack.ComboOrganOutput,
]


def driven_rack(module_cls):
    """A rack with the module, a MIDI-CV module on its keyboard inputs, and a note held."""
    rack = Rack(block_size=BLOCK)
    midi = rack.add_module(vrack.MidiCVModule("midi"))
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
    from vrack.core import VoicePool

    rack = Rack(block_size=BLOCK)

    def build(voice):
        synth = voice.add(vrack.MonoOne, "synth")
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
    from vrack.core import VoicePool

    rack = Rack(block_size=BLOCK)

    def build(voice):
        synth = voice.add(vrack.MonoOne, "synth")
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
    from vrack.core import VoicePool

    rack = Rack(block_size=BLOCK)

    def build(voice):
        synth = voice.add(vrack.MonoOne, "synth")
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
    from vrack.core import VoicePool
    from vrack.dsp.glide import GlideCore

    rack = Rack(block_size=BLOCK)

    class Slide(vrack.core.Module):
        NAME = "Slide"

        def _build(self):
            self.note_in = self.add_input("note", signal_type=vrack.core.SignalType.CV)
            self.pitch_in = self.add_input("pitch", signal_type=vrack.core.SignalType.CV)
            self.out = self.add_output("out", signal_type=vrack.core.SignalType.AUDIO)
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
    from vrack.core import VoicePool
    from vrack.dsp.glide import GlideCore

    class Slide(vrack.core.Module):
        NAME = "Slide"

        def _build(self):
            self.note_in = self.add_input("note", signal_type=vrack.core.SignalType.CV)
            self.pitch_in = self.add_input("pitch", signal_type=vrack.core.SignalType.CV)
            self.out = self.add_output("out", signal_type=vrack.core.SignalType.AUDIO)
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
    import vrack.adapter as adapter

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
    import vrack.adapter as adapter

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
    import vrack.adapter as adapter

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
    import vrack.adapter as adapter

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
