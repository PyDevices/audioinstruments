"""Render a SoundFont instrument and measure what came out, for the
`soundfont` tests. No numpy: these run wherever audiodsp builds."""

import math

import audiocore

FRAMES = 256


def _fft(real, imaginary):
    """In-place radix-2 FFT. No numpy: these tests run wherever audiodsp
    builds, and the parity interpreters have no third-party packages."""
    size = len(real)
    j = 0
    for i in range(1, size):
        bit = size >> 1
        while j & bit:
            j ^= bit
            bit >>= 1
        j |= bit
        if i < j:
            real[i], real[j] = real[j], real[i]
            imaginary[i], imaginary[j] = imaginary[j], imaginary[i]
    length = 2
    while length <= size:
        angle = -2.0 * math.pi / length
        step_real, step_imaginary = math.cos(angle), math.sin(angle)
        for start in range(0, size, length):
            wr, wi = 1.0, 0.0
            for offset in range(length // 2):
                a, b = start + offset, start + offset + length // 2
                tr = real[b] * wr - imaginary[b] * wi
                ti = real[b] * wi + imaginary[b] * wr
                real[b], imaginary[b] = real[a] - tr, imaginary[a] - ti
                real[a], imaginary[a] = real[a] + tr, imaginary[a] + ti
                wr, wi = wr * step_real - wi * step_imaginary, wr * step_imaginary + wi * step_real
        length *= 2


def render(inst, seconds, channel=None):
    """The next `seconds` of `inst` as a list of ints: one channel, or
    every channel interleaved when `channel` is None."""
    out = []
    blocks = int(seconds * inst.sample_rate / FRAMES + 0.5)
    step = inst.channel_count
    for _ in range(blocks):
        data = memoryview(bytes(audiocore.get_buffer(inst.output)[1])).cast("h")
        out.extend(data if channel is None else data[channel::step])
    return out


def peak(values):
    """Loudest sample, 0.0-1.0."""
    loudest = 0
    for value in values:
        if value < 0:
            value = -value
        if value > loudest:
            loudest = value
    return loudest / 32768.0


def rms(values):
    """Root mean square, 0.0-1.0."""
    if not values:
        return 0.0
    total = 0
    for value in values:
        total += value * value
    return math.sqrt(total / float(len(values))) / 32768.0


def silent_after(inst, limit, floor, step=0.1):
    """Seconds until `inst`'s output stays under `floor` for a whole
    `step`, rendering up to `limit` seconds; None if it never does."""
    elapsed = 0.0
    while elapsed < limit:
        if peak(render(inst, step)) < floor:
            return elapsed
        elapsed += step
    return None


def fundamental_hz(values, sample_rate, expected, spread=0.06, size=16384):
    """The frequency of the strongest spectral line within `spread` of
    `expected`, refined by parabolic interpolation, and that line's level
    in dB below the spectrum's loudest line. A tone with no partial near
    `expected` returns a line far down."""
    values = values[:size]
    window = [0.5 - 0.5 * math.cos(2.0 * math.pi * i / size) for i in range(size)]
    real = [values[i] * window[i] for i in range(size)]
    imaginary = [0.0] * size
    _fft(real, imaginary)
    half = size // 2
    magnitude = [math.hypot(real[i], imaginary[i]) for i in range(half)]
    bin_hz = sample_rate / float(size)
    low = int(expected * (1.0 - spread) / bin_hz)
    high = int(expected * (1.0 + spread) / bin_hz) + 1
    best = low
    for i in range(low, high + 1):
        if magnitude[i] > magnitude[best]:
            best = i
    a, b, c = magnitude[best - 1], magnitude[best], magnitude[best + 1]
    denominator = 2.0 * (2.0 * b - a - c)
    offset = (c - a) / denominator if denominator else 0.0
    loudest = max(magnitude[1:])
    level_db = 20.0 * math.log10((b + 1e-9) / (loudest + 1e-9))
    return (best + offset) * bin_hz, level_db


def note_hz(key):
    return 440.0 * 2.0 ** ((key - 69) / 12.0)
