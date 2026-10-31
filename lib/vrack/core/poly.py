# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Polyphony: one voice patch replicated N times, an allocator, a shared section.

A voice patch is a function that builds one voice into a rack. ``VoicePool``
calls it once per voice, feeds each copy its own pitch, gate and velocity
from a ``PolyMidiCV``, sums the copies in a ``VoiceMix`` and hands the sum to
a shared section (effects, then the master jacks) that exists once.

    def build_voice(voice):
        vco = voice.add("MonoOne", "synth")
        voice.rack.connect(voice.pitch, vco.kybd_cv_in)
        voice.rack.connect(voice.gate, vco.kybd_gate_in)
        return vco.vca_out

    pool = VoicePool(rack, build_voice, voices=8)
    pool.note_on(60, 100)

``VoiceAllocator`` decides which voice plays a note and has no audio in it.
"""

from .jack import OutputJack

FREE = 0  # silent, parked or never used
HELD = 1  # its key is down
SUSTAINED = 2  # its key is up and the sustain pedal holds it
RELEASED = 3  # its gate is off and it is still sounding its release

STEAL_POLICIES = ("oldest", "lowest", "highest", "none")
ORDERS = ("free", "cycle", "reuse")


def _no_start(voice, pitch, velocity, detune, pan, stolen):
    pass


def _no_voice(voice):
    pass


class VoiceAllocator:
    """Which voice plays which note. Pure bookkeeping, no audio.

    ``max_voices`` is how many voices exist, ``count`` how many may sound
    (``set_count`` moves it while notes play), ``unison`` how many voices one
    note takes. ``order`` says which voice a new note looks at first:

    ``"free"`` (the default)
        the lowest-numbered free voice, else the voice that has been
        releasing longest.
    ``"cycle"``
        the next voice in turn after the one given last, round and round all
        of them, held voices skipped. A voice still in its release is taken
        when its turn comes, not sooner, so releases ring while others are
        free.
    ``"reuse"``
        the voice that last played this same note, if it is not held, else as
        ``"free"``.

    When every voice the order can take is held, the note steals a sounding
    one by ``steal``: ``"oldest"`` (the longest-held note), ``"lowest"`` or
    ``"highest"`` pitch, or ``"none"`` to drop the new note. The allocator
    reports what it decided through three callbacks the owner sets:

    ``on_start(voice, pitch, velocity, detune, pan, stolen)``
        ``voice`` should play ``pitch`` (a MIDI note, fractional with
        ``detune`` in semitones, which already includes the unison offset)
        at ``velocity`` 0..1 and stereo position ``pan`` -1..1. ``stolen`` is
        true when the voice was still sounding something else.
    ``on_release(voice)``
        the voice's key came up and its gate should fall.
    ``on_cut(voice)``
        the voice stops now: the count dropped below it.

    The owner tells the allocator when a releasing voice has gone quiet with
    ``silent(voice)``, which makes it free.
    """

    def __init__(
        self,
        max_voices,
        voices=None,
        unison=1,
        steal="oldest",
        detune=0.0,
        spread=0.0,
        order="free",
    ):
        max_voices = int(max_voices)
        if max_voices < 1:
            raise ValueError("a pool needs at least one voice")
        self.max_voices = max_voices
        self.state = [FREE] * max_voices
        self.key = [None] * max_voices
        self.pitch = [0] * max_voices
        self.serial = [0] * max_voices
        self.released_at = [0] * max_voices
        #: True for a voice whose key (or the pedal) holds its gate up.
        self.gated = [False] * max_voices
        self.on_start = _no_start
        self.on_release = _no_voice
        self.on_cut = _no_voice
        self.pedal = False
        #: Voices taken while still sounding, and the ones among them that
        #: were still held (a note cut short).
        self.stolen = 0
        self.cut = 0
        #: Notes that got no voice at all because the policy is "none".
        self.dropped = 0
        self._clock = 0
        self._count = max_voices
        self._unison = 1
        self._cursor = -1  # the voice a "cycle" order gave last
        self.detune = float(detune)
        self.spread = float(spread)
        self.set_steal(steal)
        self.set_order(order)
        if voices is not None:
            self.set_count(voices)
        self.set_unison(unison)

    # -- settings ------------------------------------------------------------

    @property
    def count(self):
        """How many voices may sound."""
        return self._count

    @property
    def unison(self):
        return self._unison

    @property
    def steal(self):
        return self._steal

    @property
    def order(self):
        return self._order

    def set_order(self, order):
        """Which voice a new note looks at first (``ORDERS``). Takes effect at the next note."""
        if order not in ORDERS:
            raise ValueError("order must be one of %s, not %r" % (", ".join(ORDERS), order))
        self._order = order

    def set_steal(self, policy):
        if policy not in STEAL_POLICIES:
            raise ValueError(
                "steal must be one of %s, not %r" % (", ".join(STEAL_POLICIES), policy)
            )
        self._steal = policy

    def set_unison(self, unison):
        """Voices per note, 1 up to the pool's size. Takes effect at the next note."""
        unison = int(unison)
        if not 1 <= unison <= self.max_voices:
            raise ValueError("unison must be from 1 to %d" % self.max_voices)
        self._unison = unison

    def set_count(self, count):
        """Let ``count`` voices sound. Fewer cuts the voices above it, at once."""
        count = int(count)
        if not 1 <= count <= self.max_voices:
            raise ValueError(
                "voices must be from 1 to %d (the pool was made with %d)"
                % (self.max_voices, self.max_voices)
            )
        old = self._count
        self._count = count
        for v in range(count, old):
            self._cut(v)

    def sounding(self):
        """How many voices are not free, releases included."""
        return self.max_voices - self.state.count(FREE)

    # -- notes ---------------------------------------------------------------

    def note_on(self, key, pitch, velocity, detune=0.0):
        """Start ``key`` (any hashable identity) at MIDI ``pitch``; return its voices."""
        self._clock += 1
        serial = self._clock
        for v in range(self.max_voices):
            if self.key[v] == key and self.state[v] in (HELD, SUSTAINED):
                self._release(v)  # the same key again: the old note lets go
        want = min(self._unison, self._count)
        taken = []
        for k in range(want):
            v = self._pick(taken, pitch)
            if v is None:
                if not taken:
                    self.dropped += 1
                break
            taken.append(v)
            self._cursor = v
            stolen = self.state[v] != FREE
            if stolen:
                self.stolen += 1
                if self.state[v] != RELEASED:
                    self.cut += 1
            self.state[v] = HELD
            self.key[v] = key
            self.pitch[v] = pitch
            self.serial[v] = serial
            self.gated[v] = True
            side = 2.0 * k / (want - 1) - 1.0 if want > 1 else 0.0
            self.on_start(
                v, pitch, velocity, detune + side * self.detune, side * self.spread, stolen
            )
        return taken

    def note_off(self, key):
        """Release ``key``: its voices fall now, or at the pedal's release."""
        for v in range(self.max_voices):
            if self.key[v] == key and self.state[v] == HELD:
                if self.pedal:
                    self.state[v] = SUSTAINED
                else:
                    self._release(v)

    def sustain(self, down):
        """The sustain pedal. Letting go releases every voice it was holding."""
        down = bool(down)
        if down == self.pedal:
            return
        self.pedal = down
        if not down:
            for v in range(self.max_voices):
                if self.state[v] == SUSTAINED:
                    self._release(v)

    def all_notes_off(self):
        """Release every key and the pedal's hold."""
        for v in range(self.max_voices):
            if self.state[v] in (HELD, SUSTAINED):
                self._release(v)

    def silent(self, voice):
        """The owner heard ``voice`` go quiet after its release: it is free."""
        if self.state[voice] == RELEASED:
            self.state[voice] = FREE
            self.key[voice] = None

    def reset(self):
        """Cut every voice and lift the pedal."""
        self.pedal = False
        for v in range(self.max_voices):
            self._cut(v)

    # -- internals -------------------------------------------------------------

    def _release(self, v):
        self.state[v] = RELEASED
        self.gated[v] = False
        self._clock += 1
        self.released_at[v] = self._clock
        self.on_release(v)

    def _cut(self, v):
        if self.state[v] == FREE:
            return
        if self.state[v] != RELEASED:
            self.cut += 1
        self.state[v] = FREE
        self.key[v] = None
        self.gated[v] = False
        self.on_cut(v)

    def _pick(self, taken, pitch):
        state = self.state
        best = None
        if self._order == "cycle":
            n = self._count
            for i in range(n):
                v = (self._cursor + 1 + i) % n
                if v not in taken and state[v] not in (HELD, SUSTAINED):
                    return v
        else:
            if self._order == "reuse":
                for v in range(self._count):
                    if v in taken or state[v] in (HELD, SUSTAINED):
                        continue
                    if self.serial[v] and self.pitch[v] == pitch:  # noqa: SIM102
                        if best is None or self.serial[v] > self.serial[best]:
                            best = v
                if best is not None:
                    return best
            for v in range(self._count):
                if state[v] == FREE and v not in taken:
                    return v
            for v in range(self._count):
                if state[v] == RELEASED and v not in taken:  # noqa: SIM102
                    if best is None or self.released_at[v] < self.released_at[best]:
                        best = v
            if best is not None:
                return best
        policy = self._steal
        if policy == "none":
            return None
        for v in range(self._count):
            if v in taken or state[v] not in (HELD, SUSTAINED):
                continue
            if best is None:
                best = v
            elif policy == "oldest":
                if self.serial[v] < self.serial[best]:
                    best = v
            elif policy == "lowest":
                if (self.pitch[v], self.serial[v]) < (self.pitch[best], self.serial[best]):
                    best = v
            elif (self.pitch[v], -self.serial[v]) > (self.pitch[best], -self.serial[best]):
                best = v
        return best


class Voice:
    """One copy of the voice patch, as a patch builder sees it.

    ``bus(name, jack)`` sends one of the voice's output jacks to the pool's
    mono bus ``name`` (see ``VoicePool``).

    ``add`` puts a module in the rack under an id that carries the voice
    number (``v3_synth``), and keeps it so ``VoicePool.set_param`` can reach
    the same module in every copy. ``pitch``, ``gate``, ``velocity`` and
    ``pressure`` are this voice's own jacks on the pool's PolyMidiCV; ``bend``, ``mod`` and
    ``pedal`` are the shared wheels and pedal, the same jacks in every voice.
    ``note`` is this voice's pitch without the bend, which is what a
    portamento should slide (``dsp.glide.GlideCore``) before the bend is added
    back.

    In a mono pool ``pitch``, ``note``, ``gate``, ``velocity`` and ``pressure`` carry the
    line with its priority and legato, and two more jacks say how it is
    played: ``trig``, a pulse when a note starts (a fresh press, or every
    press with ``retrigger``), and ``legato``, a gate that is high while the
    sounding note was reached with the gate already up. They are the same
    jacks in every voice and follow the keys as one line, so read them only
    while the pool is mono.
    """

    def __init__(self, pool, index):
        self.pool = pool
        self.rack = pool.rack
        self.index = index
        self.modules = {}
        midi = pool.midi
        self.pitch = midi.pitch_outs[index]
        self.gate = midi.gate_outs[index]
        self.velocity = midi.vel_outs[index]
        self.pressure = midi.press_outs[index]
        self.bend = midi.bend_out
        self.mod = midi.mod_out
        self.pedal = midi.pedal_out
        self.note = midi.note_outs[index]
        self.trig = midi.trig_out
        self.legato = midi.legato_out
        self.output = None
        self.members = []

    def add(self, module_type, name):
        """Install a module in this voice. ``module_type`` is a class or a module name."""
        if isinstance(module_type, str):
            from ..modules import get_module_class

            module_type = get_module_class(module_type)
        rack = self.rack
        module = module_type(
            "v%d_%s" % (self.index + 1, name),
            sample_rate=rack.sample_rate,
            block_size=rack.block_size,
        )
        rack.add_module(module)
        self.modules[name] = module
        return module

    def connect(self, source, dest):
        """Patch a cable inside the rack; the same as ``rack.connect``."""
        return self.rack.connect(source, dest)

    def bus(self, name, jack):
        """Send ``jack`` to the pool's bus ``name``, which the shared section sums once."""
        ins = self.pool.mix.bus_ins.get(name)
        if ins is None:
            raise ValueError(
                "no bus %r; this pool's buses are %s"
                % (name, ", ".join(self.pool.mix.buses) or "none")
            )
        return self.rack.connect(jack, ins[self.index])


class VoicePool:
    """N copies of a voice patch, played from MIDI, summed into a shared section.

    ``build_voice(voice)`` gets a ``Voice`` and returns the OutputJack that
    carries that voice's audio. ``build_shared(rack, left, right)`` is the
    section after the voices that exists once; it gets the voices' sum as
    two jacks and returns the two jacks to patch to the master. Without one
    the sum goes to the master as it is. ``build_global(rack, midi)`` runs
    before the voices are built, for what every voice reads and that exists
    once, such as one LFO for the whole instrument; it is never parked.

    ``buses`` names mono sums beside the main one: a voice sends a jack to a
    bus with ``voice.bus(name, jack)`` and the shared section gets each bus's
    sum as a fourth argument, ``build_shared(rack, left, right, buses)``, a
    dict from each name to the OutputJack that carries it (``pool.buses``).
    A bus fades, parks and is scaled by the mix's ``level`` exactly as the
    main jack is, so the main jack, which alone decides when a voice has gone
    quiet, must carry everything the voice sounds. Buses are mono: a unison
    spread's pan does not reach them, and a pool with buses renders on the rack.

    ``voice_count`` is how many voices may sound (an Instrument's ``voices``).
    It can change while notes play, down to 1 and up to ``max_voice_count``,
    the number of copies built (``max_voices=``, which is ``voices`` unless
    you ask for more). A copy that is not
    playing and has gone quiet is not processed, so a pool of 16 with two
    notes held costs two voices.

    ``order`` (``"free"``, ``"cycle"`` or ``"reuse"``, settable while notes
    play) says which voice a new note looks at first; see ``VoiceAllocator``.

    A note that needs a voice still sounding something else takes it
    without a click: the old note fades over one block, the voice's pitch and
    gate move while it is silent, and the new note fades in over the next.

    ``mono=True`` makes a monophonic pool: one voice, which never fades, gaps
    or restarts for a second key. Keys go on a stack and ``priority`` says
    which one sounds (``"last"``, ``"low"``, ``"high"`` or ``"duo"``); letting go of the
    sounding key returns to one still held, without a new gate. A key pressed
    over another is legato (``voice.legato`` is high, ``voice.trig`` does not
    pulse); ``retrigger=True`` pulses ``trig`` on every press. The voice
    stays awake for as long as a key or the sustain pedal holds the gate.

    A mono pool plays its line on ``unison`` voices (one unless you ask for
    more, and no more than ``voice_count``), each detuned and panned by its
    share of ``unison_detune`` and ``unison_spread``; ``voices`` defaults to
    ``unison`` there. The whole stack moves on every key, with no fade or gap.
    ``mono`` can be set while notes play: every note lets go, each voice fades
    out over a block, and the next key plays in the new mode.
    """

    def __init__(
        self,
        rack,
        build_voice,
        voices=None,
        max_voices=None,
        unison=1,
        steal="oldest",
        order="free",
        unison_detune=0.1,
        unison_spread=0.5,
        build_shared=None,
        build_global=None,
        midi_id="midi",
        mix_id="voices",
        mono=False,
        priority="last",
        retrigger=False,
        buses=(),
    ):
        from ..modules import get_module_class

        if voices is None:
            voices = int(unison) if mono else 8
        voices = int(voices)
        max_voices = voices if max_voices is None else max(voices, int(max_voices))
        self.rack = rack
        self.shared = False
        mono = bool(mono)
        midi = get_module_class("PolyMidiCV")(
            midi_id, sample_rate=rack.sample_rate, block_size=rack.block_size, voices=max_voices
        )
        mix = get_module_class("VoiceMix")(
            mix_id,
            sample_rate=rack.sample_rate,
            block_size=rack.block_size,
            voices=max_voices,
            buses=buses,
        )
        rack.add_module(midi)
        rack.add_module(mix)
        self.midi = midi
        self.mix = mix
        #: Each bus name to the OutputJack that carries its sum (empty without buses).
        self.buses = dict(mix.bus_outs)
        self.alloc = midi.alloc
        midi.mono = mono
        if mono:
            midi.priority = priority
            midi.retrigger = retrigger
        elif priority != "last" or retrigger:
            raise ValueError("priority and retrigger are for a monophonic pool")
        self.alloc.detune = float(unison_detune)
        self.alloc.spread = float(unison_spread)
        self.alloc.set_count(voices)
        self.alloc.set_unison(unison)
        self.alloc.set_steal(steal)
        self.alloc.set_order(order)
        if build_global is not None:
            build_global(rack, midi)
        self.voices = []
        for i in range(max_voices):
            voice = Voice(self, i)
            before = len(rack.modules)
            out = build_voice(voice)
            if not isinstance(out, OutputJack):
                raise TypeError(
                    "build_voice must return the voice's audio OutputJack, got %r" % (out,)
                )
            voice.output = out
            voice.members = rack.modules[before:]
            rack.connect(out, mix.audio_ins[i])
            self.voices.append(voice)
        midi.listener = self
        mix.gated = self.alloc.gated
        mix.on_quiet = self.park
        for i in range(max_voices):
            self._park(i)  # an idle copy costs nothing until a note wakes it
        left, right = mix.left_out, mix.right_out
        if build_shared is not None:
            if self.buses:
                left, right = build_shared(rack, left, right, self.buses)
            else:
                left, right = build_shared(rack, left, right)
        rack.connect(left, rack.master_left_in)
        rack.connect(right, rack.master_right_in)
        self.output_left = left
        self.output_right = right

    # -- the component-contract numbers ------------------------------------------

    @property
    def voice_count(self):
        """How many voices may sound. Settable while notes play."""
        return self.alloc.count

    @voice_count.setter
    def voice_count(self, count):
        self.alloc.set_count(int(count))

    @property
    def mono(self):
        """True when the pool plays one line, on ``unison`` voices. Settable while notes play."""
        return self.midi.mono

    @mono.setter
    def mono(self, on):
        self.midi.mono = on

    @property
    def max_voice_count(self):
        """The most ``voice_count`` can be raised to: the copies built."""
        return self.alloc.max_voices

    @property
    def priority(self):
        """Which held key sounds in a mono pool: ``"last"``, ``"low"``, ``"high"`` or ``"duo"``."""
        return self.midi.priority

    @priority.setter
    def priority(self, priority):
        self._need_mono()
        self.midi.priority = priority

    @property
    def retrigger(self):
        """True when every key press pulses ``trig`` in a mono pool, not only a fresh one."""
        return self.midi.retrigger

    @retrigger.setter
    def retrigger(self, on):
        self._need_mono()
        self.midi.retrigger = on

    def _need_mono(self):
        if not self.mono:
            raise ValueError("priority and retrigger are for a monophonic pool")

    @property
    def order(self):
        """Which voice a new note takes first: ``"free"``, ``"cycle"`` or ``"reuse"``."""
        return self.alloc.order

    @order.setter
    def order(self, order):
        self.alloc.set_order(order)

    @property
    def unison(self):
        return self.alloc.unison

    @unison.setter
    def unison(self, count):
        self.alloc.set_unison(count)

    def sounding(self):
        """How many voices are sounding now, releases included."""
        return self.alloc.sounding()

    @property
    def stolen(self):
        """Voices taken while still sounding another note."""
        return self.alloc.stolen

    @property
    def cut(self):
        """The stolen or dropped voices that were still held."""
        return self.alloc.cut

    @property
    def awake(self):
        """How many copies the rack is processing."""
        return len(self.voices) - sum(1 for flag in self.mix.parked if flag)

    # -- notes and controls -------------------------------------------------------

    def note_on(self, pitch, velocity=100, detune=0.0, channel=0, note_id=-1):
        self.midi.note_on(pitch, velocity, detune, channel, note_id)

    def note_off(self, pitch, channel=0, note_id=-1):
        self.midi.note_off(pitch, channel, note_id)

    def all_notes_off(self):
        self.midi.all_notes_off()

    # -- the copies ---------------------------------------------------------------

    def modules(self, name):
        """The module called ``name`` in every copy, in voice order."""
        return [voice.modules[name] for voice in self.voices if name in voice.modules]

    def set_param(self, name, param, value):
        """Set one parameter on the module called ``name`` in every copy."""
        for module in self.modules(name):
            module.set_param(param, value)

    def set_macro(self, name, index, value):
        """``Module.set_macro`` on the module called ``name`` in every copy."""
        for module in self.modules(name):
            module.set_macro(index, value)

    def reset(self):
        """Cut every note and reset every copy."""
        self.alloc.reset()
        self.midi.reset_voices()
        for i in range(len(self.voices)):
            self._park(i)

    # -- what the PolyMidiCV and VoiceMix ask for -------------------------------------

    def wake(self, i):
        """Voice ``i`` is about to play: process it and open its mixer channel."""
        if self.mix.parked[i]:
            for module in self.voices[i].members:
                module.enabled = True
            self.mix.parked[i] = False
        self.mix.quiet[i] = 0

    def park(self, i):
        """Voice ``i`` is quiet and not held: stop processing it. False if it is busy."""
        if self.alloc.gated[i] or self.midi.busy(i):
            return False
        self._park(i)
        self.alloc.silent(i)
        return True

    def _park(self, i):
        for module in self.voices[i].members:
            module.enabled = False
            module.reset()
            for jack in module.outputs.values():
                jack.buffer[:] = 0.0
        self.mix.parked[i] = True
        self.mix.quiet[i] = 0
        self.mix.gain[i] = self.mix.target[i] = 0.0

    def fade_out(self, i):
        self.mix.target[i] = 0.0

    def fade_in(self, i, pan):
        self.mix.pan[i] = pan
        self.mix.target[i] = 1.0

    def open_channel(self, i, pan):
        self.mix.pan[i] = pan
        self.mix.gain[i] = self.mix.target[i] = 1.0
