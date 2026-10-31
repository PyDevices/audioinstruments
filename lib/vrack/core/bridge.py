# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Run audiodsp nodes on vrack's float blocks.

audiodsp nodes pull signed 16-bit PCM from a source and hand out blocks of
their own. A ``NodeBridge`` owns one ``audiocore.RawSample`` over an int16
array the size of a vrack block, chains one or more nodes onto it, and per
block: converts the float input into that array, pulls one block from the
last node, and converts the result back. With the RawSample looping and the
nodes' ``buffer_size`` set to one block, every pull consumes exactly the
block written before it, so the chain runs in lockstep with the rack.

Only nodes that accept a ``buffer_size`` can run at vrack's block size: the
CircuitPython-ported effects (``audiofilters``, ``audiodelays``,
``audiofreeverb``, ``audiomixer``), and from audiodsp 0.6.8
``audioladder.Ladder`` and ``audiooscillator.Oscillator``. synthio and the
rest of audiodsp's own nodes (``audioshaper``, ``audioverb``, ``audiomodal``,
``audiomath``) always hand out 256 frames; ``ChunkedBridge`` runs those at
the cost of 256 frames of latency and 256-frame parameter steps.

``OscillatorBridge`` drives ``audiooscillator`` nodes, whose pitch, FM, PWM
and sync are audio inputs: each CV goes into an int16 block of its own that a
looping RawSample hands to the node, so the node reads it per sample.

On MicroPython the pull goes through ``audiopump.pull`` and ``drain`` into a
bytearray the bridge owns, which allocates nothing. On CPython
``audiocore.get_buffer`` returns a fresh bytes object each block; that
allocation is audiodsp's, not vrack's.
"""

import array

import audiocore
import audiofilters

from .signal import (
    INT16_DTYPE,
    copy_into,
    create_buffer,
    from_int16,
    np,
    to_int16,
)

try:
    import audiobiquad
except ImportError:
    audiobiquad = None

try:
    import audiooscillator
except ImportError:
    audiooscillator = None

try:
    import audiopump

    _PUMP = hasattr(audiopump, "pull") and hasattr(audiopump, "drain")
except ImportError:
    audiopump = None
    _PUMP = False


def _pump_free():
    """True when ``audiopump.pull`` may be used: no pump is playing.

    audiopump has one context. A ``pull()`` while a player has the pump
    running replaces it and stops the player, so a rack that is itself being
    played through the pump (an Instrument's output) pulls its nodes with
    ``audiocore.get_buffer`` instead, which allocates a block per pull.
    """
    return _PUMP and not audiopump.running()


def effect_kwargs(block_size, sample_rate, channels=1):
    """Constructor keywords that put a CircuitPython-ported effect at vrack's block size."""
    return {
        "buffer_size": block_size * channels * 2,
        "sample_rate": sample_rate,
        "bits_per_sample": 16,
        "samples_signed": True,
        "channel_count": channels,
    }


#: The largest block audiodsp's own nodes hand out (their default).
NODE_MAX_FRAMES = 256


def node_kwargs(block_size, sample_rate, channels=1):
    """Constructor keywords that put one of audiodsp's own nodes at vrack's block size."""
    return {
        "buffer_size": block_size * channels * 2,
        "sample_rate": sample_rate,
        "channel_count": channels,
    }


_SIZED = {}


def sized_node(module, name):
    """True when ``module.name`` takes a ``buffer_size`` (audiodsp 0.6.8 and later)."""
    key = (module, name)
    if key not in _SIZED:
        try:
            getattr(module, name)(**node_kwargs(64, 48000))
            _SIZED[key] = True
        except (TypeError, ValueError, AttributeError):
            _SIZED[key] = False
    return _SIZED[key]


def biquad_kwargs(block_size):
    """The keyword that puts a mono audiobiquad node at vrack's block size.

    A NodeBridge feeds its chain one block per pull. An audiobiquad node that
    hands out 256 frames a pull takes the same block twice to fill them, and
    so filters every block twice. Where audiobiquad takes a ``buffer_size``
    each block goes through once; where it does not, these are empty.
    """
    if audiobiquad is not None and sized_node(audiobiquad, "AllPass"):
        return {"buffer_size": block_size * 2}
    return {}


def oscillator_available():
    """True when audiodsp has an Oscillator that runs at vrack's block size."""
    return audiooscillator is not None and sized_node(audiooscillator, "Oscillator")


class NodeBridge:
    """One block in, one block out, through a chain of audiodsp nodes."""

    def __init__(self, block_size, sample_rate, frames=None):
        self.block_size = block_size
        self.sample_rate = sample_rate
        self.frames = frames or block_size
        n = self.frames
        self._in = array.array("h", bytes(n * 2))
        self._in_view = np.frombuffer(self._in, dtype=INT16_DTYPE)
        self._tmp = create_buffer(n)
        self.source = audiocore.RawSample(self._in, channel_count=1, sample_rate=sample_rate)
        self.nodes = []
        self.tail = None
        self._passthrough = None
        if _PUMP:
            self._status = bytearray(audiopump.STATUS_BYTES)
            self._ring = bytearray(max(4096, n * 8))
            self._out = bytearray(n * 2)
            self._out_view = np.frombuffer(self._out, dtype=INT16_DTYPE)

    def chain(self, *nodes, direct=False):
        """Play the RawSample into the first node and each node into the next.

        ``direct`` plays the RawSample straight into the first node, for a
        node that takes a source reporting DONE on every pull (audioladder
        does; an audiofilters node loops it), and saves the passthrough.
        """
        prev = self.source
        for node in nodes:
            if not hasattr(node, "play"):
                # a source of its own (synthio.Synthesizer): it heads the chain
                # and ignores the RawSample
                prev = node
                self.nodes.append(node)
                continue
            if prev is self.source and direct:
                if isinstance(node, audiofilters.Filter):
                    node.play(prev, loop=True)
                else:
                    node.play(prev)
            elif prev is self.source:
                # A passthrough Filter sits between the RawSample and the first
                # node. A looping RawSample reports DONE on every pull and some
                # of audiodsp's own nodes (audioecho.FeedbackDelay) drop a
                # source that does; the Filter never reports DONE, loops the
                # RawSample itself, and keeps the chain in lockstep.
                self._passthrough = audiofilters.Filter(
                    filter=None, **effect_kwargs(self.frames, self.sample_rate)
                )
                self._passthrough.play(prev, loop=True)
                node.play(self._passthrough)
            else:
                node.play(prev)
            prev = node
            self.nodes.append(node)
        self.tail = prev
        self._prime()
        return self

    def _prime(self):
        # The CPython shims return one empty block on the first pull; the
        # MicroPython nodes do not. One throwaway pull of silence aligns them.
        self._pull()

    def _pull(self):
        """Pull one block from the tail; returns an int16 view of it."""
        if _pump_free():
            audiopump.pull(self.tail, 1, self._status, None, self._ring)
            audiopump.drain(self._out)
            return self._out_view
        _, mv = audiocore.get_buffer(self.tail)
        return np.frombuffer(mv, dtype=INT16_DTYPE)

    def process(self, src, dst):
        """Run one block: float src in, float dst out."""
        to_int16(self._in_view, src, self._tmp)
        from_int16(dst, self._pull())

    def reset(self):
        """Clear the input; node state is the nodes' own business."""
        for i in range(len(self._in)):
            self._in[i] = 0


class ChunkedBridge(NodeBridge):
    """A NodeBridge for nodes that only hand out 256-frame blocks.

    vrack blocks are accumulated into a 256-frame input, one pull happens
    every 256 frames, and the result is handed back a block at a time. The
    output therefore trails the input by 256 frames (5.3 ms at 48 kHz) and
    the nodes' parameters can only move once per 256 frames.
    """

    FRAMES = 256

    def __init__(self, block_size, sample_rate):
        if self.FRAMES % block_size != 0:
            raise ValueError("block size must divide %d" % self.FRAMES)
        super().__init__(block_size, sample_rate, frames=self.FRAMES)
        self._pos = 0
        self._in_f = create_buffer(self.FRAMES)
        self._out_f = create_buffer(self.FRAMES)
        self._steps = self.FRAMES // block_size
        # a view of each block's place in the chunk, made once: slicing in
        # process would make a copy (ulab) or a view object every block
        self._in_at = [
            self._in_f[i * block_size : (i + 1) * block_size] for i in range(self._steps)
        ]
        self._out_at = [
            self._out_f[i * block_size : (i + 1) * block_size] for i in range(self._steps)
        ]

    def process(self, src, dst):
        pos = self._pos
        copy_into(self._in_at[pos], src)
        copy_into(dst, self._out_at[pos])
        self._pos += 1
        if self._pos == self._steps:
            self._pos = 0
            to_int16(self._in_view, self._in_f, self._tmp)
            from_int16(self._out_f, self._pull())


#: vrack CV scales on the int16 wire (BRIDGE_SCALE: 1.0 is 16384 counts, half
#: of full scale). Pitch: 0.1 is an octave, so full scale is twenty. Linear FM:
#: OscillatorCore adds ``fm_cv * fm_depth * 1000`` Hz, so full scale is
#: ``2000 * fm_depth`` Hz. PWM: ``pwm_cv * 0.8``, so full scale is 1.6. The
#: outputs are +-0.5, a quarter of full scale.
PITCH_OCTAVES = 20.0
FM_HZ_PER_DEPTH = 2000.0
PWM_DEPTH = 1.6
OSC_LEVEL = 0.25
_INPUTS = ("pitch", "fm", "pwm", "sync")


class OscillatorBridge:
    """OscillatorCore's ``render()`` on audiooscillator nodes.

    One stereo node gives two waveforms from one phase; a third or fourth
    output adds a second node driven by the same inputs. Asking for a
    different set of outputs reconfigures the nodes in place, so the phase
    carries on. The node hands each sample out one frame late, which is what
    lets it band-limit a sync edge.
    """

    #: Waveform flags in the order render() takes its buffers.
    WAVES = (1, 2, 4, 8)

    def __init__(self, block_size, sample_rate):
        self.block_size = block_size
        self.sample_rate = sample_rate
        n = block_size
        self._tmp = create_buffer(n)
        self._cv = []
        self._cv_view = []
        self._raw = []
        for _ in _INPUTS:
            buf = array.array("h", bytes(n * 2))
            self._cv.append(buf)
            self._cv_view.append(np.frombuffer(buf, dtype=INT16_DTYPE))
            self._raw.append(audiocore.RawSample(buf, channel_count=1, sample_rate=sample_rate))
        self._nodes = []
        self._left = []
        self._right = []
        self._wired = [False] * len(_INPUTS)
        self._frequency = None
        self._fm_depth = None
        self._pulse_width = None
        # this block's outputs: waveform flag and buffer, filled in place
        self._flags = [0, 0, 0, 0]
        self._bufs = [None, None, None, None]
        if _PUMP:
            self._status = bytearray(audiopump.STATUS_BYTES)
            self._ring = bytearray(max(4096, n * 16))
            self._out = bytearray(n * 4)
            out_view = np.frombuffer(self._out, dtype=INT16_DTYPE)
            self._out_l = out_view[0::2]
            self._out_r = out_view[1::2]

    def _grow(self, count):
        # A new node starts at phase zero, so every node restarts with it and
        # they stay in step. Once, the first time this many are asked for.
        kwargs = node_kwargs(self.block_size, self.sample_rate, 2)
        while len(self._nodes) < count:
            self._nodes.append(
                audiooscillator.Oscillator(
                    level=OSC_LEVEL,
                    pitch_octaves=PITCH_OCTAVES,
                    pwm_depth=PWM_DEPTH,
                    waveform=0,
                    waveform_right=0,
                    **kwargs,
                )
            )
            self._left.append(0)
            self._right.append(0)
        for node in self._nodes:
            node.clear()
            for index, name in enumerate(_INPUTS):
                if self._wired[index]:
                    node.modulate(**{name: self._raw[index]})
        self._frequency = None

    def reset(self):
        for node in self._nodes:
            node.clear()

    def _wire(self, index, cv):
        wired = cv is not None
        if wired:
            to_int16(self._cv_view[index], cv, self._tmp)
        if wired != self._wired[index]:
            self._wired[index] = wired
            sample = self._raw[index] if wired else None
            for node in self._nodes:
                node.modulate(**{_INPUTS[index]: sample})

    def _pull(self, node):
        """Pull one block; leaves its two channels in _out_l and _out_r."""
        if _pump_free():
            audiopump.pull(node, 1, self._status, None, self._ring)
            audiopump.drain(self._out)
            return
        _, mv = audiocore.get_buffer(node)
        if _PUMP:
            self._out[:] = mv  # into the buffer _out_l and _out_r are views of
            return
        block = np.frombuffer(mv, dtype=INT16_DTYPE)
        self._out_l = block[0::2]
        self._out_r = block[1::2]

    def render(
        self,
        base_freq_hz,
        pitch_cv,
        fm_cv,
        fm_depth,
        pwm_cv,
        pulse_width,
        sync,
        saw,
        pulse,
        tri,
        sine,
    ):
        """One block into whichever of saw, pulse, tri and sine are given."""
        flags = self._flags
        bufs = self._bufs
        used = 0
        if saw is not None:
            flags[used] = 1
            bufs[used] = saw
            used += 1
        if pulse is not None:
            flags[used] = 2
            bufs[used] = pulse
            used += 1
        if tri is not None:
            flags[used] = 4
            bufs[used] = tri
            used += 1
        if sine is not None:
            flags[used] = 8
            bufs[used] = sine
            used += 1
        count = (used + 1) // 2
        if count > len(self._nodes):
            self._grow(count)
        self._wire(0, pitch_cv)
        self._wire(1, fm_cv if fm_depth != 0.0 else None)
        self._wire(2, pwm_cv)
        self._wire(3, sync)
        if (
            base_freq_hz != self._frequency
            or fm_depth != self._fm_depth
            or pulse_width != self._pulse_width
        ):
            self._frequency = base_freq_hz
            self._fm_depth = fm_depth
            self._pulse_width = pulse_width
            for node in self._nodes:
                node.set(
                    frequency=base_freq_hz,
                    fm_depth=fm_depth * FM_HZ_PER_DEPTH,
                    pulse_width=pulse_width,
                )
        for k in range(len(self._nodes)):
            node = self._nodes[k]
            left = flags[2 * k] if 2 * k < used else 0
            right = flags[2 * k + 1] if 2 * k + 1 < used else 0
            if left != self._left[k] or right != self._right[k]:
                self._left[k] = left
                self._right[k] = right
                node.set(waveform=left, waveform_right=right)
            self._pull(node)
            if left:
                from_int16(bufs[2 * k], self._out_l)
            if right:
                from_int16(bufs[2 * k + 1], self._out_r)
        for i in range(used):
            bufs[i] = None
