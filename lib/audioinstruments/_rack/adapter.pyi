# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
from collections.abc import Callable, Iterable, Mapping
from typing import Any, NoReturn, Protocol

from .soundfont import SoundFontInstrument

class _AudioSource(Protocol):
    """Anything audiodsp can pull: it names its format, as every audiodsp node does."""

    @property
    def sample_rate(self) -> int: ...
    @property
    def channel_count(self) -> int: ...

class _Playable(Protocol):
    """Something notes can be sent to, as every instrument is."""

    def note_on(self, pitch: int, velocity: int, /) -> object: ...
    def note_off(self, pitch: int, /) -> object: ...
    def all_notes_off(self) -> object: ...

_Transport = Callable[[], tuple[bool, float, float, int, int]]
"""Reads the host's transport as `(playing, position, bpm, numerator, denominator)`."""

__all__ = ("ALL", "Instrument", "ModuleVoice", "SAMPLERS", "VoicePatch", "create", "voice_patch")
SAMPLERS: tuple[str, ...]
ALL: tuple[str, ...]

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

    NAME: str
    DISPLAY_NAME: str | None
    CATEGORIES: tuple[str, ...]
    VENDOR: str
    MONO: bool
    VOICES: int
    LATENCY_SAMPLES: int
    BUSES: tuple[str, ...]
    MACRO_LABELS: tuple[str, ...]
    MACRO_MODES: dict[int, str]
    PATCHES: dict[int, tuple[str, tuple[int, ...]]]

    def build(self, voice: Any) -> Any: ...
    def build_global(self, rack: Any, midi: Any) -> None:
        """Modules every voice reads that exist once (one LFO for all), built first."""

    def build_shared(self, rack: Any, left: Any, right: Any) -> Any: ...
    def apply_patch(self, pool: Any, index: int) -> None:
        """Set what patch ``index`` sets beyond its macros. ``program_change`` calls it."""

    def set_macro(self, pool: Any, index: int, norm: float) -> None: ...

class ModuleVoice(VoicePatch):
    """One module as a voice, with the module's own macros and patches.

    Patch 0 is the module's defaults, called "Init". A module with ``PRESETS``
    (see ``Module``) has those as its patches too. A change of patch resets every
    parameter the new patch doesn't name, and plugs and pulls the cables the two
    patches differ by. Only a change of cables compiles the graph again.
    """

    NAME: str
    MONO: bool
    VOICES: int
    MACRO_LABELS: tuple[str, ...]
    DISPLAY_NAME: str | None
    MACRO_MODES: dict[int, str]
    PATCHES: dict[int, tuple[str, tuple[int, ...]]]

    def __init__(self, name: str) -> None: ...
    def build(self, voice) -> Any: ...
    def build_shared(self, rack, left, right) -> Any:
        """The module's ``VOICE_SHARED`` section, if it names one: a module after the voices'
        mix, built once, and the parameters of the voice that it takes over."""

    def set_macro(self, pool: Any, index: int, norm: float) -> None: ...
    def set_control(self, pool: Any, name: str, value: float) -> None:
        """Set one of the module's parameters in every voice, in its own units."""

    def apply_patch(self, pool: Any, index: int) -> None: ...
    def cables_differ(self, index: int) -> bool:
        """True when patch ``index`` plugs other cables than the patch that is up."""

    def plug_patch(self, pool: Any, index: int) -> None:
        """Pull the cables of the patch that is up and plug those of patch ``index``."""

def voice_patch(name: str) -> VoicePatch:
    """The ``VoicePatch`` that ``create(voice=name)`` plays, built fresh."""

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
    ``audiograph`` graph (``audioinstruments._rack.core.graph``) and renders each block with
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
    has one voice per sound and ``voices`` is how many sounds it has, so it
    refuses any other count, at ``create()`` and when set: fewer would silence
    the sounds past it, and a sound that isn't playing costs nothing. Each
    other pad key from 36 to 51 sounds the nearest key the kit has, the
    lower on a tie, as ``soundfont_drums`` does. ``strict_pads=True`` turns
    that off, so the kit answers only its own keys; ``pad_map=`` (a dict or
    ``(key, key)`` pairs) replaces it with your own table, each key sounding
    the kit key it names. The two cannot be combined.
    """

    patch: VoicePatch
    transport: _Transport
    rack: Any  # the virtual rack the patch is built on
    def __init__(
        self,
        sample_rate: int,
        channel_count: int = 2,
        transport: _Transport | None = None,
        voice: str | VoicePatch = "mono_one",
        voices: int | None = None,
        max_voices: int | None = None,
        unison: int = 1,
        unison_detune: float = 0.1,
        unison_spread: float = 0.5,
        steal: str = "oldest",
        order: str = "free",
        level: float = 0.5,
        block_size: int = 128,
        buffer_frames: int = 256,
        output: str = "auto",
        ring_blocks: int = 6,
        priority: str = "last",
        retrigger: bool = False,
        engine: str = "auto",
        pad_map: Mapping[int, int] | Iterable[tuple[int, int]] | None = None,
        strict_pads: bool = False,
        _ring_if_no_graph: bool = False,
    ) -> None: ...
    @property
    def engine(self) -> str:
        """``"graph"`` when the rack is compiled to one ``audiograph`` graph, else ``"rack"``."""
    @property
    def awake(self) -> int:
        """How many voices are being rendered now."""
    @property
    def output(self) -> _AudioSource:
        """What audiodsp pulls. Stable for the life of the instrument."""
    @property
    def sample_rate(self) -> int: ...
    @property
    def channel_count(self) -> int: ...
    @property
    def latency_samples(self) -> int:
        """Frames the patch delays its sound by (a chorus adds some); 0 for most,
        and 0 for a graph, whose nodes run at the block."""
    @property
    def tail_samples(self) -> None:
        """None: how long a release rings depends on the patch."""
    @property
    def capabilities(self) -> tuple[str, str, str, str, str]: ...
    @property
    def patch_index(self) -> int | None: ...
    @property
    def macro_labels(self) -> tuple[str, ...]: ...
    @property
    def patches(self) -> dict[int, tuple[str, tuple[int, ...]]]: ...
    @property
    def voices(self) -> int:
        """How many notes can sound at once. Set it while notes play."""
    @voices.setter
    def voices(self, count: int) -> None: ...
    @property
    def priority(self) -> str:
        """Which held key sounds on a monophonic instrument (``"last"``, ``"low"``, ``"high"``, ``"duo"``)."""
    @priority.setter
    def priority(self, priority: str) -> None: ...
    @property
    def retrigger(self) -> bool:
        """True when every key on a monophonic instrument pulses ``trig``."""
    @retrigger.setter
    def retrigger(self, on: bool) -> None: ...
    @property
    def pads(self) -> dict[int, int] | None:
        """A drum kit's table from each key it answers to its voice; None for a keyboard."""
    @property
    def strict_pads(self) -> bool:
        """True when a kit answers only its own keys, with no nearest-pad fill."""
    @property
    def voice_pool(self) -> Any:
        """The ``VoicePool`` this instrument plays on."""
    @property
    def refused(self) -> int:
        """Notes dropped because every voice was held and ``steal`` is ``"none"``."""
    @property
    def schedulable(self) -> bool:
        """False: notes cannot be queued on an ``audiopump.Events`` yet."""
    def scheduled(self, q: Any, frame: int, tokens: Any = None) -> NoReturn: ...
    def at(self, q: Any, frame: int) -> NoReturn: ...
    def note_on(
        self,
        pitch: int,
        velocity: int = 127,
        detune: float = 0.0,
        channel: int = 0,
        note_id: int = -1,
        sample_position: int = 0,
    ) -> None:
        """Play ``pitch`` at ``velocity`` (0-127). A zero velocity releases."""
    def note_off(
        self, pitch: int, channel: int = 0, note_id: int = -1, sample_position: int = 0
    ) -> None: ...
    def all_notes_off(self) -> None: ...
    def pitch_bend(self, value: float, channel: int = 0, sample_position: int = 0) -> None: ...
    def control_change(
        self, controller: int, value: float, channel: int = 0, sample_position: int = 0
    ) -> None: ...
    def channel_pressure(
        self, value: float, channel: int = 0, sample_position: int = 0
    ) -> None: ...
    def poly_pressure(
        self,
        pitch: int,
        value: float,
        channel: int = 0,
        note_id: int = -1,
        sample_position: int = 0,
    ) -> None: ...
    def hold(self) -> None:
        """With ``output="graph"``, start a batch: every change made until ``commit()`` lands
        on the same block. Batches nest; without an attached graph this does nothing."""
    def commit(self) -> None:
        """End the batch ``hold()`` started."""
    def set_macro(
        self,
        index: int,
        value: float,
        channel: int = 0,
        note_id: int = -1,
        sample_position: int = 0,
    ) -> None:
        """Set macro ``index`` from the 0-127 MIDI scale."""
    def get_macro(self, index: int) -> float: ...
    def program_change(
        self, index: int, channel: int = 0, note_id: int = -1, sample_position: int = 0
    ) -> None: ...
    def transport_changed(self) -> None: ...
    def reset(self) -> None: ...
    def deinit(self) -> None: ...
    def connect(self, source: Any, dest: Any, sample_position: int = 0) -> None:
        """Plug a cable from ``source`` to ``dest`` (jacks, or names such as
        ``"vcf.cv"``) while the instrument plays."""
    def disconnect(self, dest: Any, sample_position: int = 0) -> None:
        """Pull the cable into ``dest`` (the jack, its name or the cable) while
        the instrument plays, as ``connect()`` plugs one."""
    def add_module(self, module: Any, sample_position: int = 0) -> None:
        """Install ``module`` in the rack while the instrument plays."""
    def remove_module(self, module: Any, sample_position: int = 0) -> None:
        """Take ``module`` and its cables out of the rack while the instrument plays."""
    def fill(self) -> int:
        """Top the ring up with rendered audio; returns the buffers written."""

_AnyInstrument = Instrument | SoundFontInstrument
"""What `create` returns: the rack instrument, or the SoundFont sampler."""

def create(
    sample_rate: int,
    channel_count: int = 2,
    transport: _Transport | None = None,
    **options: Any,
) -> Instrument | SoundFontInstrument:
    """A live polyphonic instrument. See ``Instrument`` for the options.

    ``voice="soundfont"`` and ``voice="soundfont_drums"`` build the sampler
    instruments instead, with the options of ``audioinstruments._rack.soundfont.create`` and
    ``audioinstruments._rack.soundfont_drums.create``: ``bank``, ``voices``, ``voice_pool``
    (and ``pad_map`` and ``strict_pads`` for the kit).

    ``engine`` picks how a patch is rendered: ``"rack"`` runs its modules in
    Python, ``"graph"`` compiles the rack to one ``audiograph`` graph and
    renders each block with one C call (and raises where the build has no
    ``audiograph``), and ``"auto"``, the default, takes the graph where the
    build has ``audiograph`` and every module of the patch has a graph
    fragment, the rack everywhere else. ``inst.engine`` says which you got.
    """
