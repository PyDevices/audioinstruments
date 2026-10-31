# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Signal conventions and in-place buffer kernels.

Every jack carries one block of floats, whatever the signal type. Audio,
control voltage, gates and clocks share one scale:

- 1.0 is +10 V and -1.0 is -10 V.
- Audio and bipolar CV at Eurorack level (±5 V) is ±0.5.
- Gates and triggers are 0.0 or 1.0.
- Pitch is 1 V per octave: 0.1 per octave, 0.0 at C4 (MIDI 60).

The kernels below are the only array arithmetic a module should use in its
block path. Each writes into a buffer the caller owns and none builds a new
array: ``a * b`` on two arrays allocates a third, so it stays out of
process(). Under ulab even ``dst[:] = src`` copies through a temporary; the
float-to-int16 cast at the audiodsp bridge goes through audiodsp's
``audiomath.cast_into`` instead, which does not. See docs/allocation.md for
what is and is not avoidable on each interpreter.
"""

import math

try:
    from ulab import numpy as np

    FLOAT_DTYPE = np.float
    ULAB = True
except ImportError:
    import numpy as np

    FLOAT_DTYPE = np.float32
    ULAB = False

INT16_DTYPE = np.int16

DEFAULT_SAMPLE_RATE = 48000
DEFAULT_BLOCK_SIZE = 64

VOLTS_PER_OCTAVE = 1.0
NORM_PER_VOLT = 0.1
BASE_FREQ_C4 = 261.625565  # Hz, MIDI note 60, 0 V

# The audiodsp bridge maps 1.0 (10 V) to half of int16 full scale, which
# leaves 6 dB of headroom for hot patches instead of a clipper.
BRIDGE_SCALE = 16384.0
BRIDGE_INV = 1.0 / 16384.0


# Tests may install a factory that returns an ndarray subclass which records
# every array an operation creates; see tests/test_allocation.py.
BUFFER_FACTORY = None


def set_buffer_factory(factory):
    """Make create_buffer() build blocks with factory(size) instead of np.zeros."""
    global BUFFER_FACTORY
    BUFFER_FACTORY = factory


def create_buffer(size=DEFAULT_BLOCK_SIZE, fill=0.0):
    """Allocate a float block. Do this once, never inside process()."""
    buf = BUFFER_FACTORY(size) if BUFFER_FACTORY is not None else np.zeros(size, dtype=FLOAT_DTYPE)
    if fill != 0.0:
        buf[:] = fill
    return buf


def create_int16_buffer(size=DEFAULT_BLOCK_SIZE):
    """Allocate an int16 block for the audiodsp bridge."""
    return np.zeros(size, dtype=INT16_DTYPE)


# -- in-place kernels ---------------------------------------------------------


def fill(dst, value):
    """dst[:] = value."""
    dst[:] = value


def clear_buffer(dst):
    """dst[:] = 0."""
    dst[:] = 0.0


if ULAB:

    def copy_into(dst, src):
        """dst[:] = src without a temporary (ulab's slice copy makes one)."""
        dst *= 0.0
        dst += src

else:

    def copy_into(dst, src):
        """dst[:] = src without a temporary."""
        np.copyto(dst, src)


def scale(dst, k):
    """dst *= k."""
    dst *= k


def add(dst, src):
    """dst += src."""
    dst += src


def sub(dst, src):
    """dst -= src."""
    dst -= src


def mul(dst, src):
    """dst *= src: a VCA when src is unipolar, a ring modulator when bipolar."""
    dst *= src


def offset(dst, k):
    """dst += k."""
    dst += k


def scaled_into(dst, src, k):
    """dst = src * k."""
    copy_into(dst, src)
    if k != 1.0:
        dst *= k


def add_scaled(dst, src, k, tmp):
    """dst += src * k, with tmp as scratch."""
    if k == 1.0:
        dst += src
    elif k != 0.0:
        copy_into(tmp, src)
        tmp *= k
        dst += tmp


def mix_into(dst, tmp, srcs, levels):
    """dst = sum of src * level over two lists the module owns.

    Both lists persist across blocks and are updated in place, so the call
    builds nothing. A None source is skipped.
    """
    dst[:] = 0.0
    for i in range(len(srcs)):
        src = srcs[i]
        if src is not None:
            add_scaled(dst, src, levels[i], tmp)


def crossfade_into(dst, a, b, t, tmp):
    """dst = a * (1 - t) + b * t."""
    scaled_into(dst, a, 1.0 - t)
    add_scaled(dst, b, t, tmp)


try:
    # audiodsp 0.6.9.dev2: the cast in C, straight into dst, on every interpreter.
    from audiomath import cast_into as _cast_into
except ImportError:
    _cast_into = None


if _cast_into is not None:

    def to_int16(dst_i16, src, tmp):
        """Float block to int16 at bridge scale, allocating nothing.

        audiodsp rounds half away from zero, as ulab's cast does, and clamps
        at the int16 rails (+-2.0) where ulab's wraps. tmp is unused.
        """
        _cast_into(dst_i16, src, BRIDGE_SCALE)

elif ULAB:

    def to_int16(dst_i16, src, tmp):
        """Float block to int16 at bridge scale, for an audiodsp before cast_into.

        ulab casts through a temporary and wraps past +-2.0: it has no clip
        with ``out=``, so clamping here would allocate as well.
        """
        scaled_into(tmp, src, BRIDGE_SCALE)
        dst_i16[:] = tmp

else:

    def to_int16(dst_i16, src, tmp):
        """Float block to int16 at bridge scale, clamped at the rails (+-2.0).

        numpy's cast wraps a value past int16, so a cutoff CV over +2.0 would
        arrive as a large negative one; the clip keeps it at the top. The cast
        truncates, so half a count is added away from zero first: it rounds as
        audiodsp's cast_into does.
        """
        scaled_into(tmp, src, BRIDGE_SCALE)
        np.clip(tmp, -32768.0, 32767.0, out=tmp)
        tmp += np.copysign(0.5, tmp)
        dst_i16[:] = tmp


if ULAB:

    def from_int16(dst, src_i16):
        """int16 block at bridge scale to float. ulab casts through a temporary."""
        dst *= 0.0
        dst += src_i16
        dst *= BRIDGE_INV

else:

    def from_int16(dst, src_i16):
        """int16 block at bridge scale to float."""
        np.multiply(src_i16, BRIDGE_INV, out=dst)


# -- scalar helpers ------------------------------------------------------------


def clip_sample(x, min_val=-1.0, max_val=1.0):
    """Clamp one value."""
    if x < min_val:
        return min_val
    if x > max_val:
        return max_val
    return x


def pitch_to_frequency(cv_norm, base_freq=BASE_FREQ_C4):
    """1 V/oct CV to Hz: 0.0 is base_freq, 0.1 one octave up."""
    return base_freq * (2.0 ** (cv_norm * 10.0))


def frequency_to_pitch(freq, base_freq=BASE_FREQ_C4):
    """Hz to 1 V/oct CV."""
    if freq <= 0.0:
        return -1.0
    return math.log(freq / base_freq, 2.0) * 0.1


def midi_note_to_pitch(note_num, root_note=60):
    """MIDI note to 1 V/oct CV relative to root_note (60 = C4 = 0.0)."""
    return (note_num - root_note) / 120.0


def one_pole_coeff(time_sec, sample_rate):
    """Per-sample retention coefficient of a one-pole lag with time constant time_sec."""
    if time_sec <= 0.0:
        return 0.0
    return math.exp(-1.0 / (time_sec * sample_rate))


def rising_edge_index(buf, previous, threshold=0.1):
    """Index of the first rising edge through threshold, or -1.

    ``previous`` is the last sample of the preceding block. A scalar scan,
    kept for gates and clocks where only the first edge in a block matters.
    """
    last = previous
    for i in range(len(buf)):
        v = buf[i]
        if v > threshold and last <= threshold:
            return i
        last = v
    return -1
