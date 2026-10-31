# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""A polyphonic rack as an audio component.

``create()`` returns an ``Instrument``: the object audiocomponents'
instruments are, so a host written for those can drive this one. MIDI goes
in through ``note_on()``, ``note_off()``, ``pitch_bend()`` and
``control_change()``, which feed a ``PolyMidiCV``; the voices run in a rack;
and ``output`` is something audiodsp can pull, so ``audio_out.play(inst.output)``
and a plugin's sidecar take it as they take any other instrument.

    import vrack.adapter as adapter

    inst = adapter.create(48000, voice="mono_one", voices=8)
    audio_out.play(inst.output)
    inst.note_on(60, 100)

``voice`` names one of the single-module voices in ``ALL``, or is a
``VoicePatch`` you wrote. ``voices`` is how many notes sound at once and is
settable while they play, up to ``max_voices``. ``inst.voice_pool`` is the
``VoicePool`` underneath.

How ``output`` is pulled depends on the interpreter. On CPython it is an
object audiodsp's pull calls into, and the rack renders inside the pull. A
MicroPython build's audio nodes are native code and cannot call back into
Python, so there ``output`` is an ``audiopump.Ring`` and you call
``inst.fill()`` from a timer, every 10 to 20 ms, to keep it topped up.
``fill()`` is a harmless no-op on CPython, so one loop serves both.

With ``output="graph"`` a patch compiled to a graph is played by whatever
pulls it: ``output`` is the ``audiograph.Graph`` itself, so on a board whose
audio pump has a core of its own the whole patch renders there. ``fill()``
then renders nothing; call it once a turn of your loop and it applies what
changed (notes, knobs, voices going quiet) to the graph as one batch at the
top of a block. A note lands at the next block after the turn that played it.
"""

from .core.poly import VoicePool
from .core.rack import Rack
from .core.signal import BRIDGE_SCALE, ULAB, create_buffer, np

try:
    from _thread import allocate_lock as _allocate_lock
except ImportError:  # a build without threads
    _allocate_lock = None

#: Single-module voices ``create(voice=...)`` accepts: the module, the jack
#: its pitch goes into, the jack its gate goes into, and the jack its audio
#: leaves from.
_MODULE_VOICES = {
    "duo20": ("Duo20", "kybd_cv", "kybd_gate", "vca_out"),
    "mono_one": ("MonoOne", "kybd_cv", "kybd_gate", "vca_out"),
    "state_variable_mono": ("StateVariableMono", "kybd_cv", "kybd_gate", "vca_out"),
    "patch2600": ("Patch2600", "kybd_cv", "kybd_gate", "vca_out"),
    "hybrid_mono": ("HybridMono", "kybd_cv", "kybd_gate", "vca_out"),
}

#: Instruments built from several modules, with presets: the name, the
#: submodule of ``vrack.instruments`` and the ``VoicePatch`` class in it.
_PATCH_VOICES = {
    "bass_pedals": ("bass_pedals", "BassPedals"),
    "combo_organ": ("combo_organ", "ComboOrgan"),
    "compact_organ": ("compact_organ", "CompactOrgan"),
    "duosynth": ("duosynth", "DuoSynth"),
    "electric_grand70": ("electric_grand70", "ElectricGrand70"),
    "electric_piano": ("electric_piano", "ElectricPiano"),
    "mono101": ("mono101", "Mono101"),
    "mono_synth": ("mono_synth", "MonoSynth"),
    "poly106": ("poly106", "Poly106"),
    "poly5": ("poly5", "Poly5"),
    "poly6": ("poly6", "Poly6"),
    "poly8": ("poly8", "Poly8"),
    "poly80": ("poly80", "Poly80"),
    "polya6": ("polya6", "PolyA6"),
    "polyxa": ("polyxa", "PolyXa"),
    "reed_piano": ("reed_piano", "ReedPiano"),
    "reed_piano200a": ("reed_piano200a", "ReedPiano200A"),
    "rhythm606": ("rhythm606", "Rhythm606"),
    "rhythm78": ("rhythm78", "Rhythm78"),
    "rhythm808": ("rhythm808", "Rhythm808"),
    "rhythm909": ("rhythm909", "Rhythm909"),
    "string_ensemble": ("string_ensemble", "StringEnsemble"),
    "tonewheel3": ("tonewheel3", "Tonewheel3"),
    "vocoder330": ("vocoder330", "Vocoder330"),
}

#: Instruments that play recorded samples through an ``audiosampler`` and have
#: no rack: a SoundFont bank's melodic presets, and its kits. Each is a module
#: of ``vrack`` with its own ``create()``; they take ``bank=``, ``voices=`` and
#: ``voice_pool=`` where the rack voices take the options of ``Instrument``.
SAMPLERS = ("soundfont", "soundfont_drums")

#: The voices ``create(voice=name)`` can build without a patch of your own.
ALL = tuple(sorted(list(_MODULE_VOICES) + list(_PATCH_VOICES) + list(SAMPLERS)))

#: A float of 1.0 is 10 V; the rack's blocks are written to PCM at 27000 per
#: 1.0, the scale the demo movements use.
PCM_SCALE = 27000.0

#: Audio the pull hands back is 16-bit signed, as audiodsp's nodes are.
BITS_PER_SAMPLE = 16

_MORE_DATA = 1


class _NoLock:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _lock():
    return _allocate_lock() if _allocate_lock is not None else _NoLock()


class VoicePatch:
    """What an Instrument plays: one voice's modules and the macros over them.

    Subclass it, or use ``ModuleVoice`` for a single module. ``build(voice)``
    installs the voice's modules with ``voice.add()``, patches them with
    ``voice.connect()`` from ``voice.pitch``, ``voice.gate`` and
    ``voice.velocity``, and returns the OutputJack that carries the audio.
    ``build_shared(rack, left, right)`` builds the section after the voices,
    once, and returns the two jacks that go to the master. A patch with
    ``BUSES`` gets a fourth argument, ``buses`` (see ``BUSES``). ``set_macro``
    moves macro ``index`` to ``norm`` (0..1) in every voice.

    A monophonic patch sets ``MONO = True`` and ``VOICES = 1``. Its one voice
    never steals or fades: ``voice.pitch``, ``voice.gate`` and
    ``voice.velocity`` carry the line (last-note priority unless the player
    chooses another), and ``voice.trig``, ``voice.legato`` and ``voice.note``
    say when a note starts, whether it was played legato and what its pitch
    is before the bend, for a portamento (``dsp.glide.GlideCore``).
    """

    NAME = "voice"
    #: True for a monophonic patch: ``create()`` builds one voice and refuses more.
    MONO = False
    #: How many voices ``create()`` builds when it is not told.
    VOICES = 8
    #: Frames the patch delays its sound by (a chorus or a look-ahead).
    LATENCY_SAMPLES = 0
    #: Names of mono buses beside the main jack. ``build(voice)`` sends a jack to one
    #: with ``voice.bus(name, jack)`` and ``build_shared`` gets a fourth argument, a
    #: dict from each name to the jack carrying that bus's sum.
    BUSES = ()
    MACRO_LABELS = ()
    MACRO_MODES = {}
    #: {index: (name, macro values 0..127)}; patch 0 is the sound a fresh
    #: instrument makes.
    PATCHES = {0: ("Init", ())}

    def build(self, voice):
        raise NotImplementedError

    def build_global(self, rack, midi):
        """Modules every voice reads that exist once (one LFO for all), built first."""
        pass

    def build_shared(self, rack, left, right):
        return left, right

    def apply_patch(self, pool, index):
        """Set what patch ``index`` sets beyond its macros. ``program_change`` calls it."""
        pass

    def set_macro(self, pool, index, norm):
        pass


class ModuleVoice(VoicePatch):
    """One vrack module as a voice, with the module's own macros."""

    def __init__(self, name):
        try:
            module_name, self._pitch, self._gate, self._audio = _MODULE_VOICES[name]
        except KeyError:
            raise ValueError(
                "unknown voice %r; the built-in voices are %s" % (name, ", ".join(ALL))
            ) from None
        from .modules import get_module_class

        self.NAME = name
        self._cls = get_module_class(module_name)
        self.MACRO_LABELS = tuple(self._cls.MACRO_LABELS)
        self.MACRO_MODES = dict(self._cls.MACRO_MODES)
        probe = self._cls("probe")
        defaults = tuple(
            int(round(probe.get_macro(i) * 127.0)) for i in range(len(self.MACRO_LABELS))
        )
        self.PATCHES = {0: ("Init", defaults)}

    def build(self, voice):
        module = voice.add(self._cls, "synth")
        voice.connect(voice.pitch, module.inputs[self._pitch])
        voice.connect(voice.gate, module.inputs[self._gate])
        return module.outputs[self._audio]

    def set_macro(self, pool, index, norm):
        pool.set_macro("synth", index, norm)


def voice_patch(name):
    """The ``VoicePatch`` that ``create(voice=name)`` plays, built fresh."""
    entry = _PATCH_VOICES.get(name)
    if entry is None:
        return ModuleVoice(name)
    submodule, cls = entry
    module = __import__("vrack.instruments." + submodule, None, None, (cls,))
    return getattr(module, cls)()


def _positive_int(value, name):
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError("%s must be a positive integer" % name)
    return value


def _midi_value(value, name, high=127):
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("%s must be an integer from 0 through %d" % (name, high))
    if not 0 <= value <= high:
        raise ValueError("%s must be from 0 through %d" % (name, high))
    return value


def _channel(value):
    return _midi_value(value, "channel", 15)


def _note_id(value):
    if isinstance(value, bool) or not isinstance(value, int) or value < -1:
        raise ValueError("note_id must be -1 or a non-negative integer")
    return value


def _sample_position(value):
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("sample_position must be a non-negative integer")
    return value


def _bounded_midi(value):
    return min(127.0, max(0.0, float(value)))


class _PullSource:
    """The object audiodsp pulls on CPython: the rack renders inside the pull."""

    def __init__(self, instrument):
        self._instrument = instrument
        self.sample_rate = instrument._sample_rate
        self.channel_count = instrument._channel_count
        self.bits_per_sample = BITS_PER_SAMPLE
        self.samples_signed = True

    def _reset_buffer(self, single_channel_output=False, audio_channel=0):
        pass

    def _get_buffer(self, single_channel_output=False, audio_channel=0):
        inst = self._instrument
        if inst is None:
            return 0, memoryview(b"")
        return _MORE_DATA, inst._pull()

    def deinit(self):
        self._instrument = None


def _pull_is_native_only():
    """True on a build whose audio nodes only pull native objects (MicroPython)."""
    try:
        import audiocore
    except ImportError:
        return False

    class _Probe:
        sample_rate = 48000
        channel_count = 1
        bits_per_sample = 16
        samples_signed = True

        def _reset_buffer(self, single_channel_output=False, audio_channel=0):
            pass

        def _get_buffer(self, single_channel_output=False, audio_channel=0):
            return 0, memoryview(b"")

    try:
        audiocore.reset_buffer(_Probe())
    except (TypeError, AttributeError):
        return True
    return False


#: The pad keys a kit fills from its nearest neighbour, as ``soundfont_drums`` does.
PAD_LOW = 36
PAD_HIGH = 51


def kit_pads(patch, pad_map=None, strict_pads=False):
    """The key-to-voice table a kit's pool plays from, or None for a keyboard
    patch (one without ``PADS``). See ``Instrument`` for ``pad_map`` and
    ``strict_pads``."""
    from ._component import pad_table

    own = getattr(patch, "PADS", None)
    if own is None:
        if pad_map is not None or strict_pads:
            raise ValueError("pad_map and strict_pads are for a drum kit")
        return None
    own = dict(pad_table(own))
    override = pad_table((), pad_map, strict_pads)  # checks the pair of options
    if strict_pads:
        return own
    if pad_map is not None:
        return {key: own[target] for key, target in override.items() if target in own}
    table = dict(own)
    for key in range(PAD_LOW, PAD_HIGH + 1):
        if key in table:
            continue
        for distance in range(1, PAD_HIGH - PAD_LOW + 1):
            near = [k for k in (key - distance, key + distance) if PAD_LOW <= k <= PAD_HIGH]
            hit = [k for k in near if k in own]
            if hit:
                table[key] = own[hit[0]]
                break
    return table


class Instrument:
    """A live polyphonic instrument implementing the audio component API.

    Build it with ``create()``. The options are ``voice`` (a name in
    ``ALL`` or a ``VoicePatch``), ``voices`` (notes at once: the patch's ``VOICES``,
    8 unless it says), ``max_voices``
    (the most ``voices`` can be raised to, default ``voices``), ``unison``
    (voices per note, with ``unison_detune`` in semitones and
    ``unison_spread`` of stereo width), ``steal`` (``"oldest"``, ``"lowest"``,
    ``"highest"`` or ``"none"``), ``order`` (which voice a new note takes
    first: ``"free"``, ``"cycle"`` or ``"reuse"``), ``level`` (the voice mix, 0.5),
    ``block_size`` (rack block in frames, 128), ``buffer_frames`` (frames one
    pull hands back, 256), ``output`` (``"auto"``, ``"pull"``, ``"ring"`` or
    ``"graph"``, which needs the graph engine) and ``ring_blocks`` (how many
    buffers the ring holds, 6).

    ``engine`` says how the rack renders. ``"graph"`` compiles it to one
    ``audiograph`` graph (``vrack.core.graph``) and renders each block with
    one C call; ``"rack"`` runs the modules in Python; ``"auto"``, the
    default, takes the graph where the build has ``audiograph`` and every
    module in the rack has a fragment, and the rack otherwise. ``engine``
    on the instrument says which you got.

    A monophonic patch (``MONO = True``) takes ``priority`` (``"last"``,
    ``"low"``, ``"high"`` or ``"duo"``: which held key sounds, or the lowest and the
    highest together) and ``retrigger`` (a
    ``trig`` pulse on every key, not only the first), both settable on the
    instrument while it plays. It refuses ``voices`` or ``max_voices`` above
    1 and ``unison``, and the other patches refuse ``priority`` and
    ``retrigger``.

    A drum kit (a patch with ``PADS``, the ``(key, voice)`` pairs it answers)
    has one voice per sound and ``voices`` is how many sounds it has. Each
    other pad key from 36 to 51 sounds the nearest key the kit has, the
    lower on a tie, as ``soundfont_drums`` does. ``strict_pads=True`` turns
    that off, so the kit answers only its own keys; ``pad_map=`` (a dict or
    ``(key, key)`` pairs) replaces it with your own table, each key sounding
    the kit key it names. The two cannot be combined.
    """

    def __init__(
        self,
        sample_rate,
        channel_count=2,
        transport=None,
        voice="mono_one",
        voices=None,
        max_voices=None,
        unison=1,
        unison_detune=0.1,
        unison_spread=0.5,
        steal="oldest",
        order="free",
        level=0.5,
        block_size=128,
        buffer_frames=256,
        output="auto",
        ring_blocks=6,
        priority="last",
        retrigger=False,
        engine="auto",
        pad_map=None,
        strict_pads=False,
    ):
        sample_rate = _positive_int(sample_rate, "sample_rate")
        if channel_count not in (1, 2) or isinstance(channel_count, bool):
            raise ValueError("channel_count must be 1 or 2")
        if engine not in ("auto", "rack", "graph"):
            raise ValueError('engine must be "auto", "rack" or "graph"')
        block_size = _positive_int(block_size, "block_size")
        buffer_frames = _positive_int(buffer_frames, "buffer_frames")
        if buffer_frames % block_size:
            raise ValueError(
                "buffer_frames must be a whole number of blocks (block_size=%d)" % block_size
            )
        if output not in ("auto", "pull", "ring", "graph"):
            raise ValueError('output must be "auto", "pull", "ring" or "graph"')
        if output == "graph" and engine == "rack":
            raise ValueError('output="graph" needs engine="graph" or "auto"')
        self.patch = voice_patch(voice) if isinstance(voice, str) else voice
        self._pads = kit_pads(self.patch, pad_map, strict_pads)
        self._strict_pads = bool(strict_pads)
        if voices is None:
            voices = getattr(self.patch, "VOICES", 8)
        voices = _positive_int(voices, "voices")
        mono = bool(getattr(self.patch, "MONO", False))
        if mono and (voices > 1 or (max_voices or 1) > 1 or unison > 1):
            raise ValueError(
                "%s is monophonic: voices, max_voices and unison must be 1" % self.patch.NAME
            )
        self._mono = mono
        self._sample_rate = sample_rate
        self._channel_count = channel_count
        self._deinited = False
        self.transport = transport if transport is not None else _static_transport
        self._lock = _lock()
        self._events = []
        self._event_seq = 0
        self._macro_values = [0.0] * len(self.patch.MACRO_LABELS)
        self._patch_index = None

        self.rack = Rack(sample_rate=sample_rate, block_size=block_size)
        self._pool = VoicePool(
            self.rack,
            self.patch.build,
            voices=voices,
            max_voices=max_voices,
            unison=unison,
            steal=steal,
            order=order,
            unison_detune=unison_detune,
            unison_spread=unison_spread,
            build_shared=self.patch.build_shared,
            build_global=getattr(self.patch, "build_global", None),
            mono=mono,
            priority=priority,
            retrigger=retrigger,
            buses=getattr(self.patch, "BUSES", ()),
            pads=self._pads,
            chokes=getattr(self.patch, "CHOKE", ()),
        )
        self._pool.mix.set_param("level", level)
        self._midi = self._pool.midi
        self._compiled = None
        if engine != "rack":
            self._compile(engine)

        self._block_size = block_size
        self._blocks = buffer_frames // block_size
        self._frame_bytes = 2 * channel_count
        self._buffer_frames = buffer_frames
        self._slot = 0
        self._slots = []
        self._conv = create_buffer(block_size)
        for _ in range(2):
            raw = bytearray(buffer_frames * self._frame_bytes)
            self._slots.append((raw, self._block_views(raw)))
        if output == "auto":
            output = "ring" if _pull_is_native_only() else "pull"
        self._ring = None
        self._attached = False
        self._due = False  # a patch change waits for its recompile (attached)
        if output == "graph":
            if self._compiled is None:
                raise ValueError(
                    'output="graph" needs the patch compiled to a graph, and this one'
                    " renders on the rack"
                )
            self._output = self._compiled.attach()
            self._attached = True
        elif output == "ring":
            import audiopump

            self._ring = audiopump.Ring(
                sample_rate=sample_rate,
                channel_count=channel_count,
                frames=buffer_frames,
                capacity=_positive_int(ring_blocks, "ring_blocks"),
            )
            self._output = self._ring
        else:
            self._output = _PullSource(self)
        self.program_change(0)

    def _compile(self, engine):
        """The rack as one graph, when the build and the patch allow it."""
        if self._pool.buses and engine == "graph":
            raise ValueError(
                "engine='graph' cannot render a patch with buses: they need the rack engine"
            )
        if not graph_available():
            if engine == "graph":
                raise ImportError("engine='graph' needs audiograph, which this build does not have")
            return
        if engine == "auto" and any(module.fragment is None for module in self.rack.modules):
            return  # a module without a fragment: the rack renders
        from .core.graph import TooManyGroups, compile_rack

        try:
            compiled = compile_rack(
                self.rack,
                groups=[voice.members for voice in self._pool.voices],
                scale=PCM_SCALE / BRIDGE_SCALE,
                channel_count=self._channel_count,
            )
        except (MemoryError, TooManyGroups):
            if engine == "graph":
                raise
            return  # no room for the graph's tables or groups: the rack renders
        if compiled.rack_side and engine == "auto":
            compiled.deinit()  # a module without a fragment: the rack renders
            return
        self._compiled = compiled

    def _block_views(self, raw):
        """For each block of a buffer: the int16 views its left and right go into."""
        pcm = np.frombuffer(raw, dtype=np.int16)
        views = []
        step = self._channel_count
        size = self._block_size
        for k in range(self._blocks):
            block = pcm[k * size * step : (k + 1) * size * step]
            if step == 2:
                views.append((block[0::2], block[1::2]))
            else:
                views.append((block, None))
        return views

    # -- the component surface ------------------------------------------------------

    def _check_live(self):
        if self._deinited:
            raise RuntimeError("instrument has been deinitialized")

    @property
    def engine(self):
        """``"graph"`` when the rack is compiled to one ``audiograph`` graph, else ``"rack"``."""
        return "rack" if self._compiled is None else "graph"

    @property
    def awake(self):
        """How many voices are being rendered now."""
        self._check_live()
        return self._pool.awake

    @property
    def output(self):
        """What audiodsp pulls. Stable for the life of the instrument."""
        self._check_live()
        return self._output

    @property
    def sample_rate(self):
        self._check_live()
        return self._sample_rate

    @property
    def channel_count(self):
        self._check_live()
        return self._channel_count

    @property
    def latency_samples(self):
        """Frames the patch delays its sound by (a chorus adds some); 0 for most,
        and 0 for a graph, whose nodes run at the block."""
        self._check_live()
        if self._compiled is not None:
            return 0
        return getattr(self.patch, "LATENCY_SAMPLES", 0)

    @property
    def tail_samples(self):
        """None: how long a release rings depends on the patch."""
        self._check_live()
        return None

    @property
    def capabilities(self):
        self._check_live()
        return (
            "monophonic" if self._mono else "polyphonic",
            "pitch_bend",
            "control_change",
            "channel_pressure",
            "poly_pressure",
        )

    @property
    def patch_index(self):
        self._check_live()
        return self._patch_index

    @property
    def macro_labels(self):
        return tuple(self.patch.MACRO_LABELS)

    @property
    def patches(self):
        return self.patch.PATCHES

    @property
    def voices(self):
        """How many notes can sound at once. Set it while notes play."""
        self._check_live()
        return self._pool.voice_count

    @voices.setter
    def voices(self, count):
        self._check_live()
        count = _positive_int(count, "voices")
        if self._mono and count != 1:
            raise ValueError("%s is monophonic: it has one voice" % self.patch.NAME)
        with self._lock:
            self._pool.voice_count = count

    @property
    def priority(self):
        """Which held key sounds on a monophonic instrument (``"last"``, ``"low"``, ``"high"``, ``"duo"``)."""
        self._check_live()
        return self._pool.priority

    @priority.setter
    def priority(self, priority):
        self._check_live()
        with self._lock:
            self._pool.priority = priority

    @property
    def retrigger(self):
        """True when every key on a monophonic instrument pulses ``trig``."""
        self._check_live()
        return self._pool.retrigger

    @retrigger.setter
    def retrigger(self, on):
        self._check_live()
        with self._lock:
            self._pool.retrigger = on

    @property
    def pads(self):
        """A drum kit's table from each key it answers to its voice; None for a keyboard."""
        return None if self._pads is None else dict(self._pads)

    @property
    def strict_pads(self):
        """True when a kit answers only its own keys, with no nearest-pad fill."""
        return self._strict_pads

    @property
    def voice_pool(self):
        """The ``VoicePool`` this instrument plays on."""
        self._check_live()
        return self._pool

    @property
    def refused(self):
        """Notes dropped because every voice was held and ``steal`` is ``"none"``."""
        self._check_live()
        return self._pool.alloc.dropped

    @property
    def schedulable(self):
        """False: notes cannot be queued on an ``audiopump.Events`` yet, and on an
        attached graph a note lands at the block after the turn that played it."""
        self._check_live()
        return False

    def scheduled(self, q, frame, tokens=None):
        self._check_live()
        raise RuntimeError("this instrument cannot be scheduled")

    def at(self, q, frame):
        self._check_live()
        raise RuntimeError("this instrument cannot be scheduled")

    # -- MIDI -------------------------------------------------------------------------

    def _at(self, sample_position, fn, *args):
        """Run ``fn(*args)`` now, or at the block that frame ``sample_position`` falls in."""
        with self._lock:
            if sample_position == 0:
                if self._attached:
                    self._compiled.settle()
                fn(*args)
            else:
                self._event_seq += 1
                self._events.append([sample_position, self._event_seq, fn, args])

    def note_on(self, pitch, velocity=127, detune=0.0, channel=0, note_id=-1, sample_position=0):
        """Play ``pitch`` at ``velocity`` (0-127). A zero velocity releases."""
        self._check_live()
        pitch = _midi_value(pitch, "pitch")
        velocity = _midi_value(velocity, "velocity")
        channel = _channel(channel)
        note_id = _note_id(note_id)
        detune = float(detune)
        sample_position = _sample_position(sample_position)
        if velocity == 0:
            self._at(sample_position, self._midi.note_off, pitch, channel, note_id)
        else:
            self._at(sample_position, self._midi.note_on, pitch, velocity, detune, channel, note_id)

    def note_off(self, pitch, channel=0, note_id=-1, sample_position=0):
        self._check_live()
        pitch = _midi_value(pitch, "pitch")
        self._at(
            _sample_position(sample_position),
            self._midi.note_off,
            pitch,
            _channel(channel),
            _note_id(note_id),
        )

    def all_notes_off(self):
        self._check_live()
        with self._lock:
            self._midi.all_notes_off()

    def pitch_bend(self, value, channel=0, sample_position=0):
        self._check_live()
        value = _midi_value(value, "pitch bend", 16383)
        _channel(channel)
        self._at(
            _sample_position(sample_position), self._midi.pitch_bend, (value - 8192.0) / 8192.0
        )

    def control_change(self, controller, value, channel=0, sample_position=0):
        self._check_live()
        controller = _midi_value(controller, "controller")
        value = int(round(_bounded_midi(value)))
        _channel(channel)
        self._at(_sample_position(sample_position), self._midi.control_change, controller, value)

    def channel_pressure(self, value, channel=0, sample_position=0):
        """Pressure on the whole keyboard, 0-127. The ``press`` jacks carry it."""
        self._check_live()
        value = int(round(_bounded_midi(value)))
        _channel(channel)
        self._at(_sample_position(sample_position), self._midi.channel_pressure, value)

    def poly_pressure(self, pitch, value, channel=0, note_id=-1, sample_position=0):
        """Pressure on one held key, 0-127: that key's voice's ``press`` jack carries it."""
        self._check_live()
        pitch = _midi_value(pitch, "pitch")
        value = int(round(_bounded_midi(value)))
        channel = _channel(channel)
        note_id = _note_id(note_id)
        self._at(
            _sample_position(sample_position),
            self._midi.poly_pressure,
            pitch,
            value,
            channel,
            note_id,
        )

    # -- macros and patches ---------------------------------------------------------

    def hold(self):
        """With ``output="graph"``, start a batch: every change made until
        ``commit()`` lands on the same block. Batches nest; without an
        attached graph this does nothing. ``program_change()``, ``set_macro()``
        and ``reset()`` hold their own changes together already; hold around a
        run of knob moves from a panel so they land as one."""
        if self._attached:
            with self._lock:
                self._compiled.hold()

    def commit(self):
        """End the batch ``hold()`` started."""
        if self._attached:
            with self._lock:
                self._compiled.commit()

    def _macro_index(self, index):
        if isinstance(index, bool) or not isinstance(index, int):
            raise IndexError("macro index must be an integer")
        if not 0 <= index < len(self._macro_values):
            raise IndexError(
                "instrument has %d macros; no index %d" % (len(self._macro_values), index)
            )
        return index

    def _apply_macro(self, index, value):
        self._macro_values[index] = value
        self.patch.set_macro(self._pool, index, value / 127.0)

    def set_macro(self, index, value, channel=0, note_id=-1, sample_position=0):
        """Move macro ``index`` to ``value`` on the MIDI scale (0-127, floats welcome)."""
        self._check_live()
        index = self._macro_index(index)
        value = _bounded_midi(value) if value == value else 0.0
        _channel(channel)
        _note_id(note_id)
        self._patch_index = None
        self.hold()
        try:
            self._at(_sample_position(sample_position), self._apply_macro, index, value)
        finally:
            self.commit()

    def get_macro(self, index):
        self._check_live()
        return self._macro_values[self._macro_index(index)]

    def program_change(self, index, channel=0, note_id=-1, sample_position=0):
        self._check_live()
        if isinstance(index, bool) or not isinstance(index, int) or index < 0:
            raise ValueError("program index must be a non-negative integer")
        _channel(channel)
        _note_id(note_id)
        sample_position = _sample_position(sample_position)
        patch = self.patch.PATCHES.get(index)
        if patch is None:
            return
        apply_patch = getattr(self.patch, "apply_patch", None)
        self.hold()
        try:
            if apply_patch is not None:
                self._at(sample_position, apply_patch, self._pool, index)
            for macro_index, macro_value in enumerate(patch[1]):
                self._at(sample_position, self._apply_macro, macro_index, float(macro_value))
        finally:
            self.commit()
        self._patch_index = index

    def transport_changed(self):
        """Nothing in the voices follows tempo yet."""
        self._check_live()

    def reset(self):
        """Every note off and parked, every module's state cleared, patch 0."""
        self._check_live()
        self.hold()
        try:
            with self._lock:
                del self._events[:]
                self._pool.reset()
                self.rack.reset()
        finally:
            self.commit()
        self.program_change(0)

    def deinit(self):
        if self._deinited:
            return
        with self._lock:
            self._deinited = True
            del self._events[:]
            if self._compiled is not None:
                self._compiled.deinit()
                self._compiled = None
            self.rack.disconnect_all()
        if self._attached:
            self._output.deinit()  # stop whatever pulls it first, or it stops on a fault
        elif isinstance(self._output, _PullSource):
            self._output.deinit()
        elif self._ring is not None:
            self._ring.deinit()
        self._output = None
        self._ring = None

    # -- changing the patch while it plays ----------------------------------------------

    def connect(self, source, dest, sample_position=0):
        """Plug a cable from ``source`` to ``dest`` (jacks, or names such as
        ``"vcf.cv"``) while the instrument plays. On a graph the patch is
        compiled again beside the running one and swapped in at the block
        ``sample_position`` falls in, with every voice, envelope and filter
        carrying on where it was. On a graph the audio pump plays, every change
        made in one turn lands together, on the block after the turn."""
        self._live(sample_position, self.rack.connect, source, dest)

    def disconnect(self, dest, sample_position=0):
        """Pull the cable into ``dest`` (the jack, its name or the cable) while
        the instrument plays, as ``connect()`` plugs one."""
        self._live(sample_position, self.rack.disconnect, dest)

    def add_module(self, module, sample_position=0):
        """Install ``module`` in the rack while the instrument plays. Patch its
        cables with ``connect()``; until then it sits unpatched. It runs in no
        voice: it is always on, as a shared effect is."""
        self._live(sample_position, self.rack.add_module, module)

    def remove_module(self, module, sample_position=0):
        """Take ``module`` and its cables out of the rack while the instrument plays."""
        self._live(sample_position, self.rack.remove_module, module)

    def _live(self, sample_position, change, *args):
        self._check_live()
        self._at(_sample_position(sample_position), self._swap, change, args)
        if self._due:
            with self._lock:
                self._recompile()

    def _swap(self, change, args):
        """Change the rack, then compile it beside the running graph and swap that in.
        On an attached graph the recompile waits for the end of the turn, so a
        turn's changes land on one block whether or not the patch changed."""
        change(*args)
        if self._compiled is not None:
            if self._attached:
                self._due = True
            else:
                self._recompile()

    def _recompile(self):
        self._due = False
        self._compiled = self._compiled.recompile(
            groups=[voice.members for voice in self._pool.voices]
        )

    # -- rendering ----------------------------------------------------------------------

    def _run_events(self, frames):
        """Apply the events that fall in the next ``frames`` frames, in time order."""
        due = [e for e in self._events if e[0] < frames]
        if due:
            due.sort(key=lambda e: (e[0], e[1]))
            self._events = [e for e in self._events if e[0] >= frames]
            for e in due:
                e[2](*e[3])
        for e in self._events:
            e[0] -= frames

    def _render(self, raw, views):
        """Render one buffer's blocks into ``raw`` (through ``views``, a pair of
        int16 views per block, when the rack renders; the graph writes ``raw``)."""
        rack = self.rack
        size = self._block_size
        if self._compiled is not None:
            for k in range(self._blocks):
                if self._events:
                    self._run_events(size)
                # read each block: an event may have swapped in a recompiled graph
                self._compiled.step(raw, k)
            return
        conv = self._conv
        mono = self._channel_count == 1
        for left_view, right_view in views:
            if self._events:
                self._run_events(size)
            rack.step()
            left = rack.output_buffer_left
            right = rack.output_buffer_right
            if mono:
                if ULAB:
                    left_view[:] = np.clip(
                        (left + right) * (PCM_SCALE * 0.5), -PCM_SCALE, PCM_SCALE
                    )
                else:
                    np.add(left, right, out=conv)
                    conv *= PCM_SCALE * 0.5
                    np.clip(conv, -PCM_SCALE, PCM_SCALE, out=conv)
                    left_view[:] = conv
            elif ULAB:
                left_view[:] = np.clip(left * PCM_SCALE, -PCM_SCALE, PCM_SCALE)
                right_view[:] = np.clip(right * PCM_SCALE, -PCM_SCALE, PCM_SCALE)
            else:
                np.multiply(left, PCM_SCALE, out=conv)
                np.clip(conv, -PCM_SCALE, PCM_SCALE, out=conv)
                left_view[:] = conv
                np.multiply(right, PCM_SCALE, out=conv)
                np.clip(conv, -PCM_SCALE, PCM_SCALE, out=conv)
                right_view[:] = conv

    def _pull(self):
        """One buffer of interleaved int16 PCM; the two buffers take turns."""
        if self._deinited:
            return memoryview(b"")
        raw, views = self._slots[self._slot]
        self._slot ^= 1
        with self._lock:
            self._render(raw, views)
        return memoryview(raw)

    def fill(self):
        """Top the ring up with rendered audio; returns the buffers written.

        Call it from a timer on a build whose output is a ring (MicroPython).
        On CPython the pull renders and this does nothing. With
        ``output="graph"`` it is one turn of the graph's Python side (see the
        module's docstring) and returns how many blocks the graph has moved on.
        """
        self._check_live()
        if self._attached:
            with self._lock:
                blocks = self._compiled.control(self._run_events if self._events else None)
                if self._due:
                    self._recompile()
                return blocks
        ring = self._ring
        if ring is None:
            return 0
        raw, views = self._slots[0]
        written = 0
        need = len(raw)
        while ring.space() >= need:
            with self._lock:
                self._render(raw, views)
            ring.write(raw)
            written += 1
        return written


def graph_available():
    """True when this build has ``audiograph``, so a rack can compile to a graph."""
    try:
        import audiograph  # noqa: F401
    except ImportError:
        return False
    return True


def _static_transport():
    return (False, 0.0, 120.0, 4, 4)


def create(sample_rate, channel_count=2, transport=None, **options):
    """A live polyphonic instrument. See ``Instrument`` for the options.

    ``voice="soundfont"`` and ``voice="soundfont_drums"`` build the sampler
    instruments instead, with the options of ``vrack.soundfont.create`` and
    ``vrack.soundfont_drums.create``: ``bank``, ``voices``, ``voice_pool``
    (and ``pad_map`` and ``strict_pads`` for the kit).

    ``engine`` picks how a patch is rendered: ``"rack"`` runs its modules in
    Python, ``"graph"`` compiles the rack to one ``audiograph`` graph and
    renders each block with one C call (and raises where the build has no
    ``audiograph``), and ``"auto"``, the default, takes the graph where the
    build has ``audiograph`` and every module of the patch has a graph
    fragment, the rack everywhere else. ``inst.engine`` says which you got.
    """
    engine = options.pop("engine", "auto")
    if engine not in ("auto", "rack", "graph"):
        raise ValueError('engine must be "auto", "rack" or "graph"')
    voice = options.get("voice")
    if isinstance(voice, str) and voice in SAMPLERS:
        del options["voice"]
        module = __import__("vrack." + voice, None, None, ("create",))
        return module.create(
            sample_rate, channel_count=channel_count, transport=transport, **options
        )
    return Instrument(
        sample_rate, channel_count=channel_count, transport=transport, engine=engine, **options
    )


__all__ = ("ALL", "Instrument", "ModuleVoice", "SAMPLERS", "VoicePatch", "create", "voice_patch")
