# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""A rack compiled to one ``audiograph`` graph, rendered by one C call a block.

A module that can run as graph nodes declares them in ``fragment(f)``: the
nodes, how they are wired to its jacks, and how its parameters reach them.
``compile_rack(rack)`` walks the rack in its processing order, asks every
module for its fragment, joins the fragments along the cables and returns a
``CompiledRack`` whose ``step()`` renders a block straight into an int16
buffer. The rack's Python then runs only where something changes: a knob,
a note, a steal.

    class Filter(Module):
        def _build(self):
            self.audio_in = self.add_input("in", signal_type=SignalType.AUDIO)
            self.cv_in = self.add_input("cv")
            self.audio_out = self.add_output("out", signal_type=SignalType.AUDIO)
            self.add_param("cutoff", default=0.5)

        def fragment(self, f):
            import audiograph as ag

            node = f.add(ag.LADDER, (f.input(self.audio_in), f.input(self.cv_in)),
                         f.output(self.audio_out))
            f.bind(("cutoff",), lambda: f.set(node, ag.LADDER_CUTOFF_HZ,
                                               knob_hz(self.params["cutoff"], 16.0, 18000.0)))

What a fragment can say (every call is on ``f``):

- ``input(jack)`` is the buffer feeding one of the module's input jacks:
  the cable's source, or the jack's normal, or ``None`` when the jack is
  open (so a node's input can be left open too). ``output(jack)`` is the
  buffer the module's node must write for an output jack; ``buffer()`` is
  a buffer of the module's own.
- ``add(kind, inputs, output, arg=0.0)`` adds a node in the module's group;
  ``set``, ``get``, ``table`` and ``reset`` reach it as on the graph.
- ``bind(names, fn)`` runs ``fn`` now and again whenever ``set_param`` moves
  one of the parameters ``names``: that is how a knob reaches a node.
- ``control(jack)`` declares an output that carries one value a block, set
  from Python (a MIDI module's pitch or gate). A reader that takes it as a
  buffer gets a ``CONST`` node, one that calls ``watch(jack, fn)`` gets
  ``fn(value)`` on every change and no node at all, so a velocity can fold
  into a gain. Values are in the rack's units (1.0 is 10 V).
- ``switch(name)`` is a group of the module's own that ``enable(name, on)``
  turns on and off: a sub-oscillator a patch has no use for is skipped.
- ``before_run(fn)`` and ``after_run(fn)`` run every block around the graph
  call; the latter gets the mask of groups whose envelopes are sounding.
  ``on_reset(fn)`` runs in place of the module's ``reset()``.
- ``prime(fn)`` runs ``fn(run)`` once before the first block, ``run(mask)``
  rendering one block of some groups into nothing, for state a node has no
  parameter for (an oscillator's starting phase).
- ``source_group(jack)`` is the group of the module feeding an input, for a
  mixer that parks voices by what ``after_run`` reports. ``is_control(jack)``
  says whether an input is fed by a control, so a module can take its value
  by ``watch`` in floats (a pitch, say) and use the buffer only otherwise.
- ``take_master_scale(outs)`` hands a fragment the output node's scale, and
  leaves that node at unity, when ``outs`` are all the master hears (straight or
  through modules that declare ``graph_linear``); ``only_reader(jack)`` says
  whether the module is the only reader of what feeds a jack. ``VoiceMix`` uses
  them to fold its gain and the scale into each voice's VCA through the voice's
  ``graph_fold(gain)``, so the signal is rounded once, as the rack's is.

Buffers are shared. A buffer ids a fragment hands out is a name for a wire:
the compiler gives a wire a graph buffer from its first write to its last read
and lends the buffer to the next wire after that, so a voice of forty nodes
needs the buffers of its widest point, not forty. A wire is never shared when
it must hold its value outside that span: one that Python touches (a feed, a
read-back, a ``watch``, a control, anything the fragment ``keep``s), one read
before it is written in node order (a ``late`` cable, a feedback), one written
twice or never, one read from another group than the one that writes it (a
parked group's output is zeroed once, and must stay zero), and one nothing
reads. A node never writes a buffer it reads. ``REUSE`` turns sharing off.

A module with no ``fragment`` stays on the rack: its ``process()`` runs
before the graph each block, the outputs the graph reads are written into
graph buffers, and the inputs it reads from the graph are copied back after
the run, so it hears the graph's previous block. ``fragment`` may return
``False`` before touching ``f`` to decline for this build of the module
(a MIDI module in a mode it has no fragment for).

Cables keep their order: a module's nodes come after the nodes of every
module feeding it, so a cable carries the block its source just rendered.
A cable that closes a loop (``Rack.late_cables``) carries the previous
block, as on the rack, because its source's nodes come after its reader's.

The caller may hand modules out in groups (``VoicePool``'s voices): a group
is masked out of the run while none of its modules is ``enabled``, and its
nodes then cost nothing. Everything else is in the always-on group.

Two ways to run it. ``step(out, block)`` renders a block on the caller's
thread, as above. ``attach()`` instead hands the graph to something that
pulls it (the audio pump, an output's ``play()``): the graph renders where
it is pulled, and the caller runs ``control()`` once a turn of its own loop.
``control()`` runs the ``after_run`` hooks with the sounding mask the graph
last published, then the ``before_run`` hooks, then passes on the groups to
enable, all as one batch the graph applies at the top of one block. A turn
may cover several blocks or none: ``f.blocks`` says how many blocks the
``before_run`` hooks are moving on, so a hook that counts time counts by it.
It is 1 under ``step()``. ``settle()`` runs the ``after_run`` hooks on the blocks they have not heard, for a
note that goes in between turns. A rack with a module that still runs in Python
cannot be attached, because nothing would run that module between blocks.
"""

from array import array

from .jack import InputJack, OutputJack
from .signal import BRIDGE_SCALE, create_buffer, create_int16_buffer, fill, from_int16, to_int16

UNIT = BRIDGE_SCALE

# A graph keeps its parameters as float32. Where Python's float is wider,
# a value is rounded through _F32 before it is compared with the graph's.
_F32 = array("f", [0.0])
_F32[0] = 0.1
_DOUBLE = _F32[0] != 0.1

ALWAYS = 255
MAX_GROUPS = 32

#: Share graph buffers between wires that are not live together. A test that
#: reads a wire by its id after a run sets this False to keep every wire.
REUSE = True


def _outputs(output):
    """A node's outputs as a tuple: none, one, or the pair a ``PAN`` writes."""
    if output is None:
        return ()
    return output if type(output) is tuple else (output,)


def plan_buffers(nodes, count, pinned):
    """Which graph buffer each wire gets: ``(physical ids, buffers needed)``.

    ``nodes`` is the graph's nodes in run order as ``(group, inputs, output)``,
    ``count`` the wires handed out, ``pinned`` the wires that must keep a buffer of
    their own. A wire shares a buffer only with wires live at other times: from
    the node that writes it to the last node that reads it. See the module
    docstring for what is pinned. A node's output is allocated before its inputs
    are released, so a node never writes a buffer it reads.
    """
    writer = [-1] * count  # the node that writes each wire
    wgroup = [0] * count
    last = [-1] * count  # the last node that reads it
    keep = bytearray(count)
    for b in pinned:
        keep[b] = 1
    for i, (group, inputs, output) in enumerate(nodes):
        outs = _outputs(output)
        for b in inputs:
            if b is None:
                continue
            if writer[b] < 0 or wgroup[b] != group or b in outs:
                keep[b] = 1  # read before written, across groups, or its own output
            last[b] = i
        for out in outs:
            if writer[out] >= 0:
                keep[out] = 1  # written twice
            else:
                writer[out] = i
                wgroup[out] = group
    phys = [-1] * count
    free = []
    used = 0
    for i, (_group, inputs, output) in enumerate(nodes):
        for out in _outputs(output):
            if phys[out] < 0 and not keep[out] and last[out] >= 0:
                if free:
                    phys[out] = free.pop()
                else:
                    phys[out] = used
                    used += 1
        for b in inputs:
            if b is not None and last[b] == i and phys[b] >= 0 and not keep[b]:
                free.append(phys[b])
                last[b] = -2  # released once, however many inputs name it
    for b in range(count):
        if phys[b] < 0:
            phys[b] = used
            used += 1
    return phys, used


class TooManyGroups(ValueError):
    """The rack has more voices (and switches) than a graph has groups."""


class Control:
    """One value a block on an output jack, set from Python.

    ``set(value)`` passes the value to the ``CONST`` node that readers
    taking a buffer share, to every ``watch`` on the jack, and to the jack's
    own block when a rack-side module reads it.
    """

    def __init__(self, compiler, jack, value):
        self._c = compiler
        self.jack = jack
        self.value = value
        self.node = None
        self.buffer = None
        self.watchers = []
        self.to_rack = False
        self.groups = set()  # the groups whose nodes hear this control

    def set(self, value):
        if value == self.value:
            return
        self.value = value
        c = self._c
        if c.pumped and self.groups:
            c._turn.update(self.groups)
        if self.node is not None:
            c.graph.set(self.node, 0, value * UNIT)
        for fn in self.watchers:
            fn(value)
        if self.to_rack:
            fill(self.jack.buffer, value)


class Fragment:
    """What one module tells the compiler. See the module docstring."""

    def __init__(self, compiler, module, group):
        self._c = compiler
        self.module = module
        self.group = group
        self.nodes = []
        self.before = []
        self.after = []
        self.resets = []
        self.primers = []
        self.binds = {}
        self.switches = {}
        self.bits = 0 if group == ALWAYS else 1 << group

    @property
    def blocks(self):
        """How many blocks the ``before_run`` hooks are moving on: 1 under ``step()``,
        and under ``control()`` the blocks since the last turn (0 when none has passed)."""
        return self._c.elapsed

    @property
    def rendered(self):
        """How many blocks the graph rendered since the ``after_run`` hooks last ran: 1
        under ``step()``, and under ``control()`` the blocks the pump rendered between turns."""
        return self._c.rendered

    # -- wiring ----------------------------------------------------------------

    def input(self, jack):
        """The buffer feeding ``jack``, or None when nothing does."""
        return self._c.feed(jack)

    def output(self, jack):
        """The buffer the module writes for its output ``jack``."""
        return self._c.buffer_for(jack, claim=True)

    def buffer(self):
        """A buffer of the module's own."""
        return self._c.graph.buffer()

    def keep(self, buf):
        """Give wire ``buf`` a graph buffer of its own, for a module that reads it from Python
        (with ``read``) or relies on it holding its value between blocks."""
        self._c.kept.add(buf)

    def read(self, buf, dst):
        """Copy a block of wire ``buf`` (one the fragment ``keep``s) into ``dst``."""
        c = self._c
        c.graph.read(buf if c.phys is None else c.phys[buf], dst)

    def peak(self, buf):
        """The peak, in counts, of the last block of wire ``buf`` (one the fragment ``keep``s)."""
        c = self._c
        return c.graph.peak(buf if c.phys is None else c.phys[buf])

    def add(self, kind, inputs, output, arg=0.0, group=None):
        """A node in the module's group (or ``group``, from ``switch``). A node with two
        outputs (``PAN``) takes them as a pair, ``(left, right)``."""
        graph = self._c.graph
        if type(output) is tuple and not isinstance(graph, (_Sizer, _Mapped)):
            output, arg = output  # the graph itself: the second output is the node's arg
        node = graph.add(kind, self.group if group is None else group, inputs, output, arg)
        self.nodes.append(node)
        return node

    def set(self, node, index, value):
        c = self._c
        # On the pump every set is a record on the queue, and a patch change
        # recomputes the same values many times over: send only the ones that
        # differ from the last value sent.
        if c.pumped:
            sent = value
            if _DOUBLE:  # the graph keeps float32: compare what it would keep
                _F32[0] = value
                sent = _F32[0]
            if c.graph.get(node, index) == sent:
                return
        c.graph.set(node, index, value)

    def get(self, node, index):
        return self._c.graph.get(node, index)

    def table(self, node, shape):
        self._c.graph.table(node, shape)

    def reset(self, node):
        self._c.graph.reset(node)

    # -- controls ---------------------------------------------------------------

    def control(self, jack, value=0.0):
        """Declare output ``jack`` as one value a block; returns its ``Control``."""
        return self._c.control_for(jack, value)

    def watch(self, jack, fn):
        """``fn(value)`` whenever the control feeding input ``jack`` changes."""
        self._c.watch(jack, fn)

    def is_control(self, jack):
        """True when input ``jack`` is fed by a control, whose value ``watch`` hands over exactly."""
        src = self._c._source(jack)
        return src is not None and src in self._c.controls

    def source_group(self, jack):
        """The group of the module feeding input ``jack`` (None when nothing does)."""
        return self._c.source_group(jack)

    def source_module(self, jack):
        """The module feeding input ``jack`` (None when nothing does)."""
        src = self._c._source(jack)
        return None if src is None else src.module

    def only_reader(self, jack):
        """True when input ``jack`` is the one place its source's wire goes: a cable, and the
        source has no other. A module may then change the wire's scale for itself."""
        return jack.cable is not None and len(jack.cable.source.cables) == 1

    def take_master_scale(self, outs):
        """The master output's scale, for a fragment whose output jacks ``outs`` are all the
        master hears (straight, or through modules that declare ``graph_linear``) and go nowhere
        else, to apply itself in its last gain; the output node is then left at 1. None when
        they are not, or when a fragment has taken it already. A wire rounded once, at the end,
        is rounded at the output's resolution; a gain left to the output node rounds again."""
        return self._c.take_master_scale(outs)

    # -- groups ---------------------------------------------------------------------

    def switch(self, name, on=True):
        """A group of the module's own; ``enable(name, on)`` turns it on and off."""
        group = self._c.new_group()
        self.switches[name] = [group, bool(on)]
        self._refresh_bits()
        return group

    def enable(self, name, on):
        entry = self.switches[name]
        if entry[1] != bool(on):
            entry[1] = bool(on)
            self._refresh_bits()

    def _refresh_bits(self):
        bits = 0 if self.group == ALWAYS else 1 << self.group
        for group, on in self.switches.values():
            if on:
                bits |= 1 << group
        self.bits = bits

    # -- hooks ------------------------------------------------------------------------

    def bind(self, names, fn):
        """Run ``fn`` now and whenever one of the parameters ``names`` is set."""
        for name in names:
            self.binds.setdefault(name, []).append(fn)
        fn()

    def before_run(self, fn):
        self.before.append(fn)

    def after_run(self, fn):
        self.after.append(fn)

    def on_reset(self, fn):
        self.resets.append(fn)

    def prime(self, fn):
        """``fn(run)`` once, after the graph is built and before it renders.

        ``run(mask, keep)`` renders one block of the groups in ``mask`` (and the
        always-on nodes) into nothing, to move state a node has no parameter
        for: the Poly6 voice scatters its oscillators' phases this way, as the
        rack does. Every node is reset afterwards except the ``keep`` nodes, so
        the block leaves no trace but what ``fn`` meant to leave.
        """
        self.primers.append(fn)

    # -- what the module and the compiler call ----------------------------------------

    def changed(self, name):
        fns = self.binds.get(name)
        if fns:
            for fn in fns:
                fn()

    def do_reset(self):
        for fn in self.resets:
            fn()


class _Sizer:
    """Stands in for the graph on the first pass, to count buffers and nodes."""

    def __init__(self):
        self.buffers = 0
        self.nodes = 0
        self.log = []  # (group, inputs, output) of every node, in order

    def buffer(self):
        self.buffers += 1
        return self.buffers - 1

    def add(self, kind, group, inputs, output, arg=0.0):
        self.log.append((group, tuple(inputs), output))
        self.nodes += 1
        return self.nodes - 1

    def set(self, node, index, value):
        pass

    def get(self, node, index):
        return 0.0

    def table(self, node, shape):
        pass

    def reset(self, node):
        pass


class _Mapped:
    """Stands in for the graph on the second pass: wires in, graph buffers out."""

    def __init__(self, graph, phys):
        self._g = graph
        self._phys = phys
        self._count = 0
        self.set = graph.set
        self.get = graph.get
        self.table = graph.table
        self.reset = graph.reset

    def buffer(self):
        self._count += 1
        return self._count - 1

    def add(self, kind, group, inputs, output, arg=0.0):
        p = self._phys
        ins = tuple(None if b is None else p[b] for b in inputs)
        if type(output) is tuple:  # a PAN: its right side is its arg
            return self._g.add(kind, group, ins, p[output[0]], p[output[1]])
        return self._g.add(kind, group, ins, None if output is None else p[output], arg)


class CompiledRack:
    """A rack as one graph. ``step(out, block)`` renders one block.

    ``graph`` is the ``audiograph.Graph``; ``rack_side`` the modules that
    had no fragment and still run in Python; ``late`` the cables that carry
    the previous block. ``reset()`` resets every fragment and rack-side
    module; ``deinit()`` drops the graph.
    """

    def __init__(self, rack, groups=(), scale=1.0, channel_count=2, graph=None):
        self.rack = rack
        self.scale = scale
        self._scale0 = scale
        self._scale_taken = False
        self.channel_count = channel_count
        import audiograph as ag

        self._const = ag.CONST
        self._out = ag.OUT
        size = rack.block_size
        self._tmp = create_buffer(size)
        self._i16 = create_int16_buffer(size)
        self.pumped = False
        self.elapsed = 1
        self.rendered = 1
        self._turn = set()
        self._build(groups, graph)
        self._prime()

    # -- compiling ------------------------------------------------------------------------

    def _build(self, groups, graph):
        rack = self.rack
        order = rack.order
        if graph is None:
            # one pass to size the graph, a second to build it
            import audiograph as ag

            sizer = self.graph = _Sizer()
            self._compile(order, groups)
            wires = sizer.buffers
            self.phys = None
            buffers = wires
            if REUSE:
                self.phys, buffers = plan_buffers(sizer.log, wires, self._pinned())
            self.wires = wires
            options = {
                "sample_rate": rack.sample_rate,
                "frames": rack.block_size,
                "channel_count": self.channel_count,
                "buffers": max(1, buffers),
                "nodes": max(1, sizer.nodes),
            }
            sizer = None
            try:
                try:
                    # room for a whole patch change as one batch
                    self.graph = ag.Graph(queue=max(1024, 8 * options["nodes"]), **options)
                except TypeError:  # an audiograph from before the queue
                    self.graph = ag.Graph(**options)
            except MemoryError:
                self.deinit()  # the sizing pass bound the modules: unbind them
                raise
            self.buffer_count = buffers
        else:
            self.graph = graph
            self.phys = None
            self.buffer_count = self.wires = None
        real = self.graph
        if self.phys is not None:
            for _ in range(self.buffer_count):
                real.buffer()
            self.graph = _Mapped(real, self.phys)
        self._compile(order, groups)
        self.graph = real
        if self.phys is not None:
            self._to_buffers(self.phys)

    def _pinned(self):
        """The wires Python touches, as the sizing pass left them."""
        pinned = set(self.kept)
        pinned.update(buf for _, buf in self.feeds)
        pinned.update(buf for _, buf in self.readbacks)
        pinned.update(buf for buf, _, _ in self._watch_buffers)
        for control in self.controls.values():
            if control.buffer is not None:
                pinned.add(control.buffer)
        return pinned

    def _to_buffers(self, phys):
        """Move what Python reads and writes by wire id onto the graph's buffers."""
        self.feeds = [(jack, phys[buf]) for jack, buf in self.feeds]
        self.readbacks = [(jack, phys[buf]) for jack, buf in self.readbacks]
        self._watch_buffers = [(phys[buf], fn, last) for buf, fn, last in self._watch_buffers]

    def _prime(self):
        primers = [(f, fn) for f in self.fragments for fn in f.primers]
        if not primers:
            return
        graph = self.graph
        kept = set()

        def run(mask, keep=()):
            graph.run(None, 0, mask)
            kept.update(keep)

        for _, fn in primers:
            fn(run)
        # the blocks that ran moved the always-on nodes too: put every node back as it
        # was, a mixer's gains unprimed, except the ones whose state was the point
        for f in self.fragments:
            for node in f.nodes:
                if node not in kept:
                    graph.reset(node)

    def _compile(self, order, groups):
        self.scale = self._scale0  # a fragment may take it, in each pass
        self._scale_taken = False
        self.late = list(self.rack.late_cables)
        self.buffers = {}  # OutputJack -> buffer id
        self.controls = {}  # OutputJack -> Control
        self.fragments = []
        self.rack_side = []
        self.grouped = []  # fragment modules whose bits can change
        self.before = []
        self.after = []
        self.claimed = set()  # output jacks a fragment writes
        self.feeds = []  # (OutputJack of a rack-side module, buffer id)
        self.readbacks = []  # (OutputJack of a graph module read by the rack, buffer id)
        self._read_back = set()
        self.kept = set()  # wires a fragment asked to keep to itself
        self._watch_buffers = []  # (buffer id, fn, [last]) for a watch on a signal
        self._watch_jacks = []  # the input jack of each of those watches
        self._groups = 0
        group_of = {}
        for members in groups:
            group = self.new_group()
            for module in members:
                group_of[module] = group
        self.group_of = group_of
        self._graph_modules = set()
        for module in order:
            if getattr(module, "fragment", None) is not None:
                self._graph_modules.add(module)
        for module in order:
            if module in self._graph_modules:
                f = Fragment(self, module, group_of.get(module, ALWAYS))
                module._fragment = f
                if module.fragment(f) is False:
                    module._fragment = None
                    self._graph_modules.discard(module)
                    self.rack_side.append(module)
                    continue
                module.reset = f.do_reset
                self.fragments.append(f)
                self.before.extend(f.before)
                self.after.extend(f.after)
                if f.group != ALWAYS or f.switches:
                    self.grouped.append(module)
            else:
                self.rack_side.append(module)
        self._master()
        self._rack_readers()
        self._check_outputs()

    def new_group(self):
        if self._groups >= MAX_GROUPS:
            raise TooManyGroups("a graph has %d groups and this rack needs more" % MAX_GROUPS)
        self._groups += 1
        return self._groups - 1

    def _source(self, jack):
        """The OutputJack feeding an input jack: its cable's, or its normal's.

        A normal may be another input (WestCoastSynth's pitch inputs are
        normalled to its keyboard input), which is followed to what feeds it.
        None when nothing does.
        """
        while jack is not None:
            if jack.cable is not None:
                return jack.cable.source
            normal = jack.normal
            if isinstance(normal, OutputJack):
                return normal
            jack = normal if isinstance(normal, InputJack) else None
        return None

    def feed(self, jack):
        src = self._source(jack)
        if src is None:
            return None
        control = self.controls.get(src)
        if control is not None:
            group = self.group_of.get(jack.module, ALWAYS)
            if group != ALWAYS:
                control.groups.add(group)
            if control.node is None:
                control.buffer = self.graph.buffer()
                # a control with one reader, by cable, runs in that reader's group
                group = ALWAYS
                if jack.cable is not None and len(src.cables) == 1:
                    group = self.group_of.get(jack.module, ALWAYS)
                control.node = self.graph.add(self._const, group, (), control.buffer)
                self.graph.set(control.node, 0, control.value * UNIT)
            return control.buffer
        if src.module in self._graph_modules:
            return self.buffer_for(src)
        # a rack-side module: its block is written into the graph before each run
        if src not in self.buffers:
            self.buffers[src] = self.graph.buffer()
            self.feeds.append((src, self.buffers[src]))
        return self.buffers[src]

    def buffer_for(self, jack, claim=False):
        buf = self.buffers.get(jack)
        if buf is None:
            buf = self.buffers[jack] = self.graph.buffer()
        if claim:
            self.claimed.add(jack)
        return buf

    def control_for(self, jack, value):
        control = self.controls.get(jack)
        if control is None:
            control = self.controls[jack] = Control(self, jack, value)
            if jack in self.buffers:
                raise ValueError(
                    "%s is a control, but a module ahead of it in the rack's order"
                    " already reads it as a buffer" % jack.qualified_name
                )
        return control

    def watch(self, jack, fn):
        src = self._source(jack)
        if src is None:
            return
        control = self.controls.get(src)
        if control is not None:
            group = self.group_of.get(jack.module, ALWAYS)
            if group != ALWAYS:
                control.groups.add(group)
            control.watchers.append(fn)
            fn(control.value)
            return
        # a signal: its first sample each block, after the run
        self._watch_buffers.append((self.feed(jack), fn, [None]))
        self._watch_jacks.append(jack)

    def source_group(self, jack):
        src = self._source(jack)
        if src is None:
            return None
        return self.group_of.get(src.module, ALWAYS)

    def _check_outputs(self):
        for jack in self.buffers:
            if (
                jack.module in self._graph_modules
                and jack not in self.controls
                and jack not in self.claimed
            ):
                raise ValueError(
                    "%s has a fragment, but nothing in it writes its output %s"
                    % (jack.module.id, jack.qualified_name)
                )

    def _rack_readers(self):
        """Cables from the graph into rack-side modules: copied back after each run."""
        for cable in self.rack.cables:
            if not cable.is_connected:
                continue
            src, dst = cable.source, cable.dest.module
            if dst is None or dst in self._graph_modules:
                continue
            control = self.controls.get(src)
            if control is not None:
                control.to_rack = True
                fill(src.buffer, control.value)
            elif src.module in self._graph_modules and src not in self._read_back:
                self._read_back.add(src)
                self.readbacks.append((src, self.buffer_for(src)))

    def take_master_scale(self, outs):
        if self._scale_taken or not self._feeds_master_only(outs):
            return None
        self._scale_taken = True
        self.scale = 1.0
        return self._scale0

    def _feeds_master_only(self, outs):
        """True when the master hears ``outs`` and nothing else, straight or through modules
        whose output is a linear function of their inputs (``graph_linear``), and ``outs``
        go nowhere else: a gain may then move from the output node to before ``outs``."""
        rack = self.rack
        masters = (rack.master_left_in, rack.master_right_in)

        def linear(module):
            return getattr(module, "graph_linear", False) and module in self._graph_modules

        def heard_only_from(src, seen):
            if src in outs:
                return True
            module = src.module
            if not linear(module) or module in seen:
                return False
            seen.add(module)
            fed = False
            for jack in module.inputs.values():
                feeder = self._source(jack)
                if feeder is None:
                    continue
                if not heard_only_from(feeder, seen):
                    return False
                fed = True
            return fed

        def goes_only_on(jack, seen):
            for cable in jack.cables:
                dest = cable.dest
                if dest in masters:
                    continue
                module = dest.module
                if not linear(module):
                    return False
                if module in seen:
                    continue
                seen.add(module)
                for out in module.outputs.values():
                    if not goes_only_on(out, seen):
                        return False
            return True

        left = self._source(rack.master_left_in)
        right = self._source(rack.master_right_in)
        if left is None or not heard_only_from(left, set()):
            return False
        if right is not None and not heard_only_from(right, set()):
            return False
        seen = set()
        return all(goes_only_on(jack, seen) for jack in outs)

    def _master(self):
        rack = self.rack
        left = self.feed(rack.master_left_in)
        right = self.feed(rack.master_right_in)
        if right is None:
            right = left
        self.out_node = self.graph.add(self._out, ALWAYS, (left, right), None)
        self.graph.set(self.out_node, 0, self.scale)

    # -- running ----------------------------------------------------------------------------

    def step(self, out, block):
        """Render one block into ``out`` at ``block``; returns the sounding mask."""
        if self.pumped:
            raise RuntimeError(
                "this graph is attached: whatever pulls it renders, and control() drives it"
            )
        size = self.rack.block_size
        for module in self.rack_side:
            if module.enabled:
                module.process(size)
        g = self.graph
        i16 = self._i16
        tmp = self._tmp
        for jack, buf in self.feeds:
            to_int16(i16, jack.buffer, tmp)
            g.write(buf, i16)
        for fn in self.before:
            fn()
        mask = 0
        for module in self.grouped:
            if module.enabled:
                mask |= module._fragment.bits
        sounding = g.run(out, block, mask)
        for fn in self.after:
            fn(sounding)
        for jack, buf in self.readbacks:
            g.read(buf, i16)
            from_int16(jack.buffer, i16)
        for buf, fn, last in self._watch_buffers:
            g.read(buf, i16)
            value = i16[0] / UNIT
            if value != last[0]:
                last[0] = value
                fn(value)
        return sounding

    # -- attached: the graph renders where it is pulled ----------------------------------

    def attach(self):
        """Hand the graph over to be pulled; returns the ``audiograph.Graph``.

        From here on whatever pulls the graph renders it, ``step()`` refuses,
        and ``control()`` runs the Python side once a turn. Refuses a rack with
        a module that still runs in Python, naming it.
        """
        if self.pumped:
            return self.graph
        for module in self.rack_side:
            raise ValueError(
                "%s has no graph fragment and would run in Python every block,"
                " which an attached graph cannot wait for" % module.id
            )
        for jack, _ in self.feeds:
            raise ValueError(
                "%s feeds the graph from Python every block, which an attached graph"
                " cannot wait for" % jack.qualified_name
            )
        for jack, _ in self.readbacks:
            raise ValueError(
                "%s is read back into Python every block, which an attached graph"
                " cannot do" % jack.qualified_name
            )
        for jack in self._watch_jacks:
            raise ValueError(
                "%s watches a signal block by block, which an attached graph cannot"
                " do; feed it from a control" % jack.qualified_name
            )
        g = self.graph
        if not hasattr(g, "hold"):
            raise RuntimeError("this audiograph cannot be pulled: it has no change queue")
        _, frame, _, _ = g.sounding()
        self._seen = frame
        self._credited = frame
        self._mask = None
        self._touched = {}  # group -> changes queued when its last note went in
        self._depth = 0
        self.pumped = True
        self.elapsed = 0
        return g

    def hold(self):
        """Start a batch: the graph applies everything until ``commit()`` on one block.
        Batches nest; only the outermost commits."""
        if self.pumped:
            if self._depth == 0:
                self.graph.hold()
            self._depth += 1

    def commit(self):
        if self.pumped:
            self._depth -= 1
            if self._depth == 0:
                self.graph.commit()

    def _heard(self):
        """Run the ``after_run`` hooks on the blocks rendered since they last ran, if any;
        the graph's ``sounding()`` as it then stands."""
        g = self.graph
        size = self.rack.block_size
        sounding, frame, applied, queued = g.sounding()
        if frame != self._seen:
            self.rendered = ((frame - self._seen) & 0xFFFFFFFF) // size
            self._seen = frame
            touched = self._touched
            for group in list(touched):
                if (applied - touched[group]) & 0xFFFFFFFF >= 0x80000000:
                    sounding |= 1 << group  # not heard yet
                else:
                    del touched[group]
            for fn in self.after:
                fn(sounding)
        return sounding, frame, applied, queued

    def settle(self):
        """Run the ``after_run`` hooks on any blocks they have not heard, now. A note that
        goes in between two turns would otherwise wake a voice the rack had parked in the
        block before: ``step()`` runs the hooks as each block ends, so a note after it finds
        the voice parked, and a pump's note must find it so too."""
        if self.pumped:
            self.hold()
            try:
                self._heard()
            finally:
                self.commit()

    def control(self, events=None):
        """One turn of the Python side of an attached graph; returns the blocks it moved on.

        The ``after_run`` hooks get the sounding mask the graph last published
        (when a block has rendered since the last turn), ``events(frames)``
        runs what falls in the frames the turn moves on, then the
        ``before_run`` hooks run and the groups to enable are passed on, all in
        one batch. A group with a note queued after the changes the mask had
        heard counts as sounding: that mask is from before the note.
        """
        g = self.graph
        size = self.rack.block_size
        self.hold()
        try:
            sounding, frame, applied, _ = self._heard()
            # the hooks move on to the end of the block the pump renders next
            ahead = (frame + size - self._credited) & 0xFFFFFFFF
            blocks = 0 if ahead >= 0x80000000 else ahead // size
            self._credited = (self._credited + blocks * size) & 0xFFFFFFFF
            self.elapsed = blocks
            if events is not None:
                events(blocks * size)
            for fn in self.before:
                fn()
            mask = 0
            for module in self.grouped:
                if module.enabled:
                    mask |= module._fragment.bits
            if mask != self._mask:
                woken = mask & ~(self._mask or 0)
                group = 0
                while woken:
                    if woken & 1:
                        self._turn.add(group)
                    woken >>= 1
                    group += 1
                self._mask = mask
                g.enable(mask)
        finally:
            self.commit()
        if self._turn:
            pushed = g.sounding()[3]
            for group in self._turn:
                self._touched[group] = pushed
            self._turn.clear()
        return blocks

    def reset(self):
        self.hold()
        try:
            for f in self.fragments:
                f.do_reset()
            for module in self.rack_side:
                module.reset()
        finally:
            self.commit()

    def deinit(self):
        """Drop the graph; the modules get their own ``reset()`` back."""
        for f in self.fragments:
            f.module._fragment = None
            try:
                delattr(f.module, "reset")
            except AttributeError:
                pass
        self.graph = None


def compile_rack(rack, groups=(), scale=1.0, channel_count=2):
    """Compile ``rack`` into a ``CompiledRack``.

    ``groups`` is a list of module lists, each a group that is masked out
    while none of its modules is enabled (``VoicePool`` hands its voices).
    ``scale`` is what the master output is multiplied by on its way into
    the int16 block (``PCM_SCALE / UNIT`` to match the rack's output), and
    ``channel_count`` 1 or 2.
    """
    return CompiledRack(rack, groups=groups, scale=scale, channel_count=channel_count)
