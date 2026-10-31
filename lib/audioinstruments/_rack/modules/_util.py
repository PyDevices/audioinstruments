# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Small helpers the module panels share."""

from ..core.signal import mix_into


def knob_hz(norm, low_hz, high_hz):
    """A 0..1 knob mapped exponentially across a frequency range."""
    return low_hz * ((high_hz / low_hz) ** norm)


def switch_index(value, count):
    """A switch parameter as a position 0..count-1."""
    return int(value) % count


def jack_signal(jack):
    """The jack's block when something feeds it (a cable or a normal), else None."""
    if jack.is_connected or jack.is_normalled:
        return jack.get_buffer()
    return None


class InputMixer:
    """Sums several input jacks, each through a level parameter, into one block.

    Holds its source and level lists across blocks so the per-block call
    builds nothing. An unfed jack contributes nothing.
    """

    def __init__(self, module, jacks, level_params):
        self.module = module
        self.jacks = jacks
        self.level_params = level_params
        n = len(jacks)
        self._srcs = [None] * n
        self._levels = [0.0] * n

    def render(self, dst, tmp):
        params = self.module.params
        for i in range(len(self.jacks)):
            self._srcs[i] = jack_signal(self.jacks[i])
            self._levels[i] = params[self.level_params[i]]
        mix_into(dst, tmp, self._srcs, self._levels)

    def any_fed(self):
        # a plain loop: a generator here would be an allocation per block
        for jack in self.jacks:  # noqa: SIM110
            if jack.is_connected or jack.is_normalled:
                return True
        return False
