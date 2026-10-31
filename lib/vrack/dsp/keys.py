# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Struck keys: a hammer, a bank of tuned modes it rings, and a magnetic pickup.

The parts every electromechanical or struck-string keyboard shares, each
modelled by what it is rather than by one instrument:

- ``HammerExciter``: the force of a hammer (or a tangent, or a pluck) on the
  vibrating part, a half-sine push whose contact time shortens as the blow
  gets harder.
- ``StruckBarCore``: the vibrating part as a table of modes over audiodsp's
  ``audiomodal.Bank``, each mode a frequency ratio, a decay time and a gain,
  set per key. A tine and its tonebar, a reed, a bar or a string is a
  different table.
- ``PickupCore``: a pickup's nonlinearity, electromagnetic (a coil and magnet)
  or electrostatic (a charged comb), where the part sits against it
  (``offset``) and how far it swings (``drive``).
- ``key_curve``: a per-key value read off a few anchor keys, for the decay
  times, gains and ratios that change along a keyboard.
"""

import math

import audiomodal

from ..core.bridge import ChunkedBridge
from ..core.signal import copy_into, create_buffer, np
from .blocks import EdgeDetector, Ramp

#: Modes are kept below this fraction of the sample rate; a mode above it is muted.
TOP_FREQ_FACTOR = 0.45

#: The bank's input gain. The hammer pulse is large on the int16 wire, so its
#: shape survives the trip, and the bank scales it down.
BANK_GAIN = 1.0 / 16.0


def key_curve(note, points):
    """The value at MIDI ``note`` on a curve through ``points``.

    ``points`` is a sequence of ``(note, value)`` anchors in rising note
    order, every value above zero. Between two anchors the value moves by
    a constant ratio per semitone (a straight line in dB or octaves); below
    the first or above the last it holds the end value.
    """
    n = float(note)
    first = points[0]
    if n <= first[0]:
        return first[1]
    prev = first
    for point in points:
        if n <= point[0]:
            frac = (n - prev[0]) / (point[0] - prev[0])
            return prev[1] * (point[1] / prev[1]) ** frac
        prev = point
    return prev[1]


class HammerExciter:
    """The push of a hammer on a vibrating part, as a half-sine pulse.

    A soft blow is a long, round push that mostly moves the fundamental; a
    hard one is short and sharp, so it reaches the high modes too. The
    pulse's area (the push it gives the fundamental) is ``level`` times the
    hardest pulse's, so a shorter pulse is a taller one: hardness moves the
    brightness, and the caller sets the loudness. The contact time also
    shortens up the keyboard (a smaller, stiffer part throws the hammer off
    sooner), keeping the same area.
    """

    #: Contact time in samples at 48 kHz for the softest and the hardest blow.
    SOFT = 128.0
    HARD = 16.0

    def __init__(self, block_size, sample_rate=48000):
        self.block_size = block_size
        self.sample_rate = sample_rate
        self.ramp = Ramp(block_size)
        self.pulse_active = False
        self.pulse_len = 0
        self.pulse_pos = 0
        self.pulse_amp = 0.0

    def set_block_size(self, block_size):
        self.block_size = block_size
        self.ramp = Ramp(block_size)

    def reset(self):
        self.pulse_active = False
        self.pulse_len = 0
        self.pulse_pos = 0
        self.pulse_amp = 0.0

    def strike(self, hardness=0.5, level=1.0, f0=None, contact=0.5):
        """Start a blow.

        ``hardness`` (0..1) sets the contact time, from ``SOFT`` to ``HARD``;
        ``level`` is the height of the hardest pulse, and every other pulse
        has its area. With ``f0``, the contact time is held under
        ``contact`` periods of that frequency.
        """
        h = max(0.0, min(1.0, float(hardness)))
        scale = self.sample_rate / 48000.0
        length = self.SOFT * scale * (self.HARD / self.SOFT) ** h
        amp = float(level) * self.HARD * scale / length
        if f0:
            limit = contact * self.sample_rate / max(1.0, float(f0))
            if length > limit:
                amp *= length / limit
                length = limit
        self.pulse_len = max(4, int(round(length)))
        self.pulse_pos = 0
        self.pulse_amp = amp
        self.pulse_active = True

    def render_into(self, dst, start_index=0):
        """Write the pulse's next samples into ``dst`` from ``start_index`` on."""
        if not self.pulse_active:
            return
        n = len(dst)
        if start_index >= n:
            return
        k = min(n - start_index, self.pulse_len - self.pulse_pos)
        if k <= 0:
            self.pulse_active = False
            return
        view = dst[start_index : start_index + k]
        copy_into(view, self.ramp.view(k))
        view += self.pulse_pos - 1
        view *= math.pi / float(self.pulse_len)
        np.sin(view, out=view)
        view *= self.pulse_amp
        self.pulse_pos += k
        if self.pulse_pos >= self.pulse_len:
            self.pulse_active = False


class StruckBarCore:
    """A struck part ringing in its modes, over ``audiomodal.Bank``.

    ``tune(f0, table)`` sets every mode from a table of ``(ratio, decay,
    gain)`` rows: a frequency ratio to ``f0``, a decay time in seconds (to
    -60 dB) and a gain. Modes at or above ``TOP_FREQ_FACTOR`` of the sample
    rate are muted. A rising gate strikes the bank with ``HammerExciter``.
    A strike starts from rest: the voice pool fades a sounding voice out
    before it gives it a new note, so the old ring is cleared, not carried
    into the new pitch. The bank hands out 256-frame blocks through a
    ``ChunkedBridge``, so the output trails the gate by ``LATENCY`` frames.
    Damping is the owner's: multiply the output by an envelope.
    """

    LATENCY = ChunkedBridge.FRAMES

    def __init__(self, sample_rate, block_size, modes=4):
        self.sample_rate = sample_rate
        self.block_size = block_size
        self.modes = modes
        self.bank = audiomodal.Bank(
            sample_rate=sample_rate, modes=modes, channel_count=1, mix=1.0, gain=BANK_GAIN
        )
        self.bridge = ChunkedBridge(block_size, sample_rate).chain(self.bank)
        self.exciter = HammerExciter(block_size, sample_rate)
        self.edges = EdgeDetector(block_size)
        self._in = create_buffer(block_size)
        self._mute = 0

    def set_block_size(self, block_size):
        self.block_size = block_size
        self.bridge = ChunkedBridge(block_size, self.sample_rate).chain(self.bank)
        self.exciter.set_block_size(block_size)
        self.edges = EdgeDetector(block_size)
        self._in = create_buffer(block_size)

    def reset(self):
        self.exciter.reset()
        self.edges.high = False
        self.bank.clear()
        self.bridge.reset()
        self._mute = 0

    @property
    def ringing(self):
        return self.bank.ringing or self.exciter.pulse_active

    def tune(self, f0, table):
        """Set the modes from ``table``, rows of ``(ratio, decay, gain)``.

        Rows past ``modes`` are ignored; modes past the table's end are muted.
        Ringing modes keep their energy and move to the new settings.
        """
        top = self.sample_rate * TOP_FREQ_FACTOR
        f0 = max(20.0, float(f0))
        for m in range(self.modes):
            if m < len(table):
                ratio, decay, gain = table[m]
                f = f0 * ratio
                if f >= top:
                    f, gain = top, 0.0
                self.bank.set_mode(m, f, max(0.001, decay), max(0.0, gain))
            else:
                self.bank.set_mode(m, f0, 0.001, 0.0)

    def render(self, gate, dst, hardness=0.5, level=1.0, f0=None):
        """Render one block into ``dst``; a rising edge in ``gate`` strikes.

        ``hardness``, ``level`` and ``f0`` go to ``HammerExciter.strike``.
        """
        exc = self._in
        exc[:] = 0.0
        rising = -1
        if gate is not None:
            rising, _ = self.edges.scan(gate)
            if rising >= 0:
                self.bank.clear()
                self.exciter.strike(hardness, level, f0)
                self.exciter.render_into(exc, start_index=rising)
            elif self.exciter.pulse_active:
                self.exciter.render_into(exc)
        elif self.exciter.pulse_active:
            self.exciter.render_into(exc)
        self.bridge.process(exc, dst)
        # what the bridge still holds from before a strike is the old ring:
        # silence it until the strike comes through
        n = len(dst)
        start = 0
        if rising >= 0:
            start = rising
            self._mute = self.LATENCY
        if self._mute > 0:
            stop = min(n, start + self._mute)
            dst[start:stop] = 0.0
            self._mute -= stop - start


class PickupCore:
    """A pickup's nonlinearity, with ``offset`` and ``drive``.

    A steel tine or reed swinging past a magnet (``curve="electromagnetic"``)
    changes the flux through the coil by a curve, not a line:
    ``y(u) = u / (1 + u*u/2)``. A reed swinging in the slot of a charged comb
    (``curve="electrostatic"``) is a variable capacitor whose response rises
    more steeply than a line as the reed nears the comb, peaks, and falls as it
    swings past: ``y(u) = u / (u**4 - u**2 + 1)``, steepest-rising to its peak
    at ``u`` about 0.88. A blow that swings the reed beyond the peak folds the
    wave back on itself, which is the snarl of a hard-played reed piano.

    In both, ``u = drive * x + offset``, less the curve's resting value, so
    silence stays silent. With the part centred the curve is symmetric and adds
    odd harmonics; set off centre (``offset``) it is lopsided and adds even
    ones, more the further it swings (``drive`` times the input). The slope at
    rest moves with the offset; ``gain_at`` gives it, for a caller that wants
    the level to hold as the offset moves. A lopsided curve also shifts its
    output's average while a note sounds, following the note's envelope: block
    it with a high-pass after the mix.
    """

    #: The curve shapes ``curve`` can name.
    CURVES = ("electromagnetic", "electrostatic")

    def __init__(self, block_size, curve="electromagnetic"):
        if curve not in self.CURVES:
            raise ValueError("unknown pickup curve %r" % (curve,))
        self.block_size = block_size
        self.curve = curve

    def set_block_size(self, block_size):
        self.block_size = block_size

    @staticmethod
    def gain_at(offset, curve="electromagnetic"):
        """The curve's small-signal gain at ``offset``."""
        if curve == "electrostatic":
            o2 = offset * offset
            o4 = o2 * o2
            denom = o4 - o2 + 1.0
            return (1.0 + o2 - 3.0 * o4) / (denom * denom)
        o2 = 0.5 * offset * offset
        return (1.0 - o2) / ((1.0 + o2) * (1.0 + o2))

    def render(self, src, dst, tmp, drive=1.0, offset=0.0):
        """Shape ``src`` through the pickup curve into ``dst`` using scratch ``tmp``."""
        copy_into(dst, src)
        if drive != 1.0:
            dst *= drive
        if offset != 0.0:
            dst += offset
        copy_into(tmp, dst)
        tmp *= dst
        if self.curve == "electrostatic":
            tmp -= 1.0
            tmp *= dst
            tmp *= dst
            tmp += 1.0
            dst /= tmp
            if offset != 0.0:
                o2 = offset * offset
                dst -= offset / (o2 * o2 - o2 + 1.0)
        else:
            tmp *= 0.5
            tmp += 1.0
            dst /= tmp
            if offset != 0.0:
                dst -= offset / (1.0 + 0.5 * offset * offset)
