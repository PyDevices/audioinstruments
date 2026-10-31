# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Voice mix: sums the voices of a polyphonic patch into a stereo pair.

Each voice has an audio input (``in1``..``inN``), a gain that ramps between
blocks (so a stolen voice fades out and the next note fades in without a
step) and a stereo balance that unison spread sets. A voice that is not held
and has been quiet for 30 ms is reported through ``on_quiet`` so the pool can
stop processing it, after a one-block fade to zero; a parked voice is skipped
here.

``VoicePool`` owns the gains, balances and the park list. Patched by hand the
module is a plain mixer: every voice at unity, centred.

``buses`` names extra mono sums. Each name has an input per voice
(``<name>1``..``<name>N``, ``bus_ins[name][i]``) and one output (``<name>``,
``bus_outs[name]``). A bus input with a cable is added to its bus output
with exactly the gain the voice's main input gets that block (the same ramp,
the same ``level``), centred: a stolen voice fades on every bus as it does on
the main sum, and a parked voice adds nothing to any. Whether a voice is quiet
is decided on its main input alone, so that must carry everything the voice
sounds. A mix with buses has no graph fragment.

Compiled to a graph (``audioinstruments._rack.core.graph``), the mix is a ``PAN`` node (two
``MIX`` nodes, one a side, where the graph has no ``PAN``) whose gains ramp
across a block when they move, which is the fade. The park
rule is the rack's: after each block the mix takes the peak of every awake
voice's input wire, and a voice quiet for 30 ms parks as above.
"""

from ..core.jack import SignalType
from ..core.module import Module
from ..core.signal import BRIDGE_SCALE, add_scaled, copy_into, np

# 20 mV on the 10 V scale: twice the highest idle level measured on the voices
# (quantisation noise and DC offsets of 3 to 10 mV from the audiodsp nodes),
# 54 dB under a full-scale voice.
QUIET_LEVEL = 2e-3
QUIET_SECONDS = 0.03


def _is_name(name):
    """True for a plain ASCII identifier."""
    if not isinstance(name, str) or not name:
        return False
    for i, c in enumerate(name):
        if ord(c) > 127 or not (c.isalpha() or c == "_" or (i > 0 and c.isdigit())):
            return False
    return True


def _check_buses(buses, voices):
    """The bus names as a tuple, or ValueError for a name that cannot be one."""
    buses = tuple(buses)
    taken = {"left", "right", "level"}
    for i in range(voices):
        taken.add("in%d" % (i + 1))
    for name in buses:
        if not _is_name(name):
            raise ValueError("a bus name must be a plain identifier, not %r" % (name,))
        names = [name] + ["%s%d" % (name, i + 1) for i in range(voices)]
        for n in names:
            if n in taken:
                raise ValueError(
                    "bus name %r is taken or clashes with another jack (%s)" % (name, n)
                )
        taken.update(names)
    return buses


def _peak(buf):
    hi = np.max(buf)
    lo = np.min(buf)
    return hi if hi > -lo else -lo


class VoiceMix(Module):
    NAME = "VoiceMix"
    DISPLAY_NAME = "Voice Mix"
    HP = 12

    def __init__(self, id_tag=None, sample_rate=48000, block_size=64, voices=8, buses=()):
        self.max_voices = int(voices)
        if self.max_voices < 1:
            raise ValueError("voices must be at least 1")
        self.buses = _check_buses(buses, self.max_voices)
        super().__init__(id_tag, sample_rate=sample_rate, block_size=block_size)

    def _build(self):
        n = self.max_voices
        self.audio_ins = [
            self.add_input("in%d" % (i + 1), "Voice %d" % (i + 1), SignalType.AUDIO)
            for i in range(n)
        ]
        self.left_out = self.add_output("left", "Left", SignalType.AUDIO)
        self.right_out = self.add_output("right", "Right", SignalType.AUDIO)
        #: ``bus_ins[name][i]`` is voice ``i``'s input to bus ``name``; ``bus_outs[name]`` its sum.
        self.bus_ins = {}
        self.bus_outs = {}
        for name in self.buses:
            self.bus_ins[name] = [
                self.add_input("%s%d" % (name, i + 1), "%s %d" % (name, i + 1), SignalType.AUDIO)
                for i in range(n)
            ]
            self.bus_outs[name] = self.add_output(name, name, SignalType.AUDIO)
        if self.buses:
            self.fragment = None  # the graph has no buses: the rack renders this mix
        self.add_param("level", "Level", default=0.5, min_val=0.0, max_val=2.0)
        for name in ("_mid", "_tmp", "_tmp2", "_ramp", "_unit"):
            self.add_scratch(name)
        self.gain = [1.0] * n
        self.target = [1.0] * n
        self.pan = [0.0] * n
        self.parked = [False] * n
        self.quiet = [0] * n
        #: A list of flags, True for a voice whose key holds it: those never
        #: count as quiet. ``VoicePool`` shares the allocator's list.
        self.gated = [False] * n
        #: Called with a voice number when it has been quiet and unheld long
        #: enough; returns True if the voice was parked.
        self.on_quiet = None
        self._fill_unit()

    def _fill_unit(self):
        n = self.block_size
        unit = self._unit
        for i in range(n):
            unit[i] = (i + 1) / n

    def set_block_size(self, block_size):
        super().set_block_size(block_size)
        self._fill_unit()

    def process(self, block_size):
        left = self.left_out.buffer
        right = self.right_out.buffer
        mid = self._mid
        tmp = self._tmp
        tmp2 = self._tmp2
        ramp = self._ramp
        left[:] = 0.0
        right[:] = 0.0
        mid[:] = 0.0
        buses = self.buses
        if buses:
            for name in buses:
                self.bus_outs[name].buffer[:] = 0.0
        level = self.params["level"]
        quiet_blocks = int(QUIET_SECONDS * self.sample_rate / block_size) + 1
        for i in range(self.max_voices):
            if self.parked[i]:
                continue
            src = self.audio_ins[i].get_buffer()
            if self.gated[i]:
                self.quiet[i] = 0
            elif _peak(src) < QUIET_LEVEL:
                self.quiet[i] += 1
                if self.quiet[i] >= quiet_blocks:
                    if self.target[i] != 0.0:
                        self.target[i] = 0.0  # fade it out this block, park it the next
                    elif self.gain[i] == 0.0:
                        self.quiet[i] = 0
                        if self.on_quiet is not None and self.on_quiet(i):
                            continue
            else:
                self.quiet[i] = 0
            g0 = self.gain[i]
            g1 = self.target[i]
            self.gain[i] = g1
            if g0 == 0.0 and g1 == 0.0:
                continue
            pan = self.pan[i]
            if g0 == g1:
                k = g1 * level
                if pan == 0.0:
                    add_scaled(mid, src, k, tmp)
                else:
                    add_scaled(left, src, k * (1.0 if pan <= 0.0 else 1.0 - pan), tmp)
                    add_scaled(right, src, k * (1.0 if pan >= 0.0 else 1.0 + pan), tmp)
                if buses:
                    self._add_buses(i, k, None)
                continue
            # a gain ramp across the block: src * (g0 .. g1) * level
            copy_into(ramp, self._unit)
            ramp *= (g1 - g0) * level
            ramp += g0 * level
            copy_into(tmp, src)
            tmp *= ramp
            if pan == 0.0:
                mid += tmp
            else:
                add_scaled(left, tmp, 1.0 if pan <= 0.0 else 1.0 - pan, tmp2)
                add_scaled(right, tmp, 1.0 if pan >= 0.0 else 1.0 + pan, tmp2)
            if buses:
                self._add_buses(i, 0.0, ramp)
        left += mid
        right += mid

    def _add_buses(self, i, k, ramp):
        """Voice ``i``'s cabled bus inputs into the bus sums: gain ``k``, or the block's ``ramp``."""
        tmp = self._tmp
        for name in self.buses:
            jack = self.bus_ins[name][i]
            if jack.cable is None:
                continue
            src = jack.get_buffer()
            out = self.bus_outs[name].buffer
            if ramp is None:
                add_scaled(out, src, k, tmp)
            else:
                copy_into(tmp, src)
                tmp *= ramp
                out += tmp

    def reset(self):
        for i in range(self.max_voices):
            self.gain[i] = self.target[i]

    # -- as a graph fragment ------------------------------------------------------------

    def fragment(self, f):
        import audiograph as ag

        n = self.max_voices
        ins = tuple(f.input(jack) for jack in self.audio_ins)
        # One PAN node mixes eight voices into both sides; a graph without PAN takes a MIX
        # a side, whose gains carry the balance. More voices mix in eights, then once more.
        self._pan = getattr(ag, "PAN", None)
        self._slots = [None] * n  # voice -> (nodes, input index): (PAN,) or (left, right)

        def mix(chunk, b_left, b_right):
            if self._pan is not None:
                return (f.add(self._pan, chunk, (b_left, b_right)),)
            return (f.add(ag.MIX, chunk, b_left), f.add(ag.MIX, chunk, b_right))

        if n <= 8:
            nodes = mix(ins, f.output(self.left_out), f.output(self.right_out))
            for i in range(n):
                self._slots[i] = (nodes, i)
        else:
            partials = []
            for start in range(0, n, 8):
                chunk = ins[start : start + 8]
                b_left, b_right = f.buffer(), f.buffer()
                nodes = mix(chunk, b_left, b_right)
                for i in range(len(chunk)):
                    self._slots[start + i] = (nodes, i)
                partials.append((b_left, b_right))
            if len(partials) > 8:
                raise ValueError("a voice mix takes at most 64 voices as a graph")
            left = f.add(ag.MIX, tuple(b for b, _ in partials), f.output(self.left_out))
            right = f.add(ag.MIX, tuple(b for _, b in partials), f.output(self.right_out))
            for i in range(len(partials)):
                f.set(left, i, 1.0)
                f.set(right, i, 1.0)
        # a voice nobody is playing sits at the gain a new note opens it at, so
        # the note does not fade in across a block the rack's does not
        level = self.params["level"]
        for i in range(n):
            nodes, slot = self._slots[i]
            for node in nodes:
                f.set(node, slot, level)
        # Round once. When every voice can (``graph_fold``) and nothing but linear effects
        # stands between this mix and the output, each voice takes the mix's level and the
        # master's scale into its own last gain: its wire is rounded once, at the resolution
        # it is heard at, and the mix sums the wires at unity, which is exact (a fade or a
        # balance still rounds). Left to the mix and the output node, the two gains were two
        # more roundings. Without the master's scale the level stays here: a voice's wire at
        # the level alone is coarser than the output, and a chord of them would be the worse.
        self._fold = None
        voices = [
            f.source_module(jack) if wire is not None else None
            for jack, wire in zip(self.audio_ins, ins)
        ]
        cabled = [v for v in voices if v is not None]
        for v in cabled:
            if getattr(v, "graph_fold", None) is not None:
                v.graph_fold(1.0)
        if (
            cabled
            and all(
                getattr(v, "graph_fold", None) is not None and v._fragment is not None
                for v in cabled
            )
            and all(f.only_reader(jack) for jack, v in zip(self.audio_ins, voices) if v)
        ):
            scale = f.take_master_scale((self.left_out, self.right_out))
            if scale is not None:
                self._fold = voices
                self._fold_scale = scale
                self._fold_level = None
                self._fold_gain = 1.0
        self._wires = ins
        for wire in ins:
            if wire is not None:
                f.keep(wire)  # peaked after each block, for the park rule
        self._pushed = [None] * n
        self._pan_index = getattr(ag, "PAN_PAN", 0)
        f.bind(("level",), self._graph_block)
        f.before_run(self._graph_block)
        f.after_run(self._graph_after)

    def _graph_block(self):
        """Every voice's gain to the nodes, when it moved. A parked voice's input is
        silent, so it waits at the gain a note opens it at (full, centred): the
        rack opens a woken voice with no ramp, and so does a gain already there.

        A voice that parks in the block before a note wakes it has not been pushed
        to that gain yet, and the node would ramp the note in across its first block.
        The rack gives such a voice its gain in one step (``open_channel``), so when
        nothing else is ramping the nodes are reset and take every gain as it stands."""
        level = self.params["level"]
        f = self._fragment
        unit = level  # what the mix's own gains carry of the level
        if self._fold is not None:
            unit = self._graph_fold(level)
        snapped = []
        ramping = False
        for i in range(self.max_voices):
            rack_gain = self.gain[i]
            if self.parked[i]:
                g1, pan = 1.0, 0.0
            else:
                g1, pan = self.target[i], self.pan[i]
                self.gain[i] = g1
            key = (g1, pan, level)
            was = self._pushed[i]
            if key != was:
                self._pushed[i] = key
                k = g1 * unit
                nodes, slot = self._slots[i]
                if len(nodes) == 1:
                    f.set(nodes[0], slot, k)
                    f.set(nodes[0], self._pan_index + slot, pan)
                else:
                    f.set(nodes[0], slot, k * (1.0 if pan <= 0.0 else 1.0 - pan))
                    f.set(nodes[1], slot, k * (1.0 if pan >= 0.0 else 1.0 + pan))
                if self.parked[i] or (was is not None and was[0] == g1) or rack_gain != g1:
                    ramping = ramping or not self.parked[i]
                else:
                    snapped.append(nodes)
        if snapped and not ramping:
            for nodes in snapped:
                for node in nodes:
                    f.reset(node)

    def _graph_fold(self, level):
        """The level (and the master's scale) to the voices, when it moved; the share of the
        level the mix's gains still carry: 1, or 0 for a level of 0, which the voices leave to
        the mix so a voice's wire still says whether it sounds."""
        gain = self._fold_scale * (level if level > 0.0 else 1.0)
        if level != self._fold_level:
            self._fold_level = level
            self._fold_gain = gain
            for voice in self._fold:
                if voice is not None:
                    voice.graph_fold(gain)
        return 1.0 if level > 0.0 else 0.0

    def _graph_after(self, sounding):
        """The rack's park rule on the graph's wires: a voice whose input has peaked under
        ``QUIET_LEVEL`` for 30 ms and is not held fades (the next block, since this one has
        rendered), then parks the block after. Each awake voice costs a ``peak()`` a block.
        Under ``control()`` the blocks between two turns count as the one block read."""
        on_quiet = self.on_quiet
        if on_quiet is None:
            return
        f = self._fragment
        blocks = f.rendered
        if blocks < 1:
            return
        quiet_blocks = int(QUIET_SECONDS * self.sample_rate / self.block_size) + 1
        threshold = QUIET_LEVEL * BRIDGE_SCALE
        if self._fold is not None:
            # The wire carries the level and the master's scale the voice took (not the fade).
            # At the default level the threshold is then a whole count (27), and a peak of
            # exactly that was anything from 26.5 to 27.5 before it was rounded: as likely
            # quiet as not. It counts as quiet, so the comparison is strict.
            threshold = threshold * self._fold_gain + 1e-6
        for i in range(self.max_voices):
            if self.parked[i]:
                continue
            if self.gated[i]:
                self.quiet[i] = 0
                continue
            wire = self._wires[i]
            if wire is not None and f.peak(wire) >= threshold:
                self.quiet[i] = 0
                continue
            self.quiet[i] += blocks
            if self.quiet[i] >= quiet_blocks:
                if self.target[i] != 0.0:
                    self.target[i] = 0.0  # the next block fades it, the one after parks it
                elif self.gain[i] == 0.0:
                    self.quiet[i] = 0
                    on_quiet(i)

    def get_state(self):
        state = super().get_state()
        state["voices"] = self.max_voices
        if self.buses:
            state["buses"] = list(self.buses)
        return state
